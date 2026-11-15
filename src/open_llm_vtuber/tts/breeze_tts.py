"""Breeze-TTS-2 voice direction. Model weights are for non-commercial use only."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import io
from pathlib import Path
import re
import threading
import time
from uuid import uuid4
import wave

import httpx
from loguru import logger

from .tts_interface import TTSInterface

DEFAULT_STYLE_INSTRUCTIONS = {
    "calm": "语气平静、柔和",
    "warm": "语气温暖、带着关切",
    "steady": "语气沉稳、清晰、让人安心",
}
PREVIEW_TEXT = "你好呀，今天过得怎么样？不管发生了什么，我都在这里，慢慢说给我听就好。"
VOICE_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def build_instruction(base, style, speed, energy, mapping=None) -> str:
    """Translate validated per-sentence decisions into native delivery directions."""
    mapping = {**DEFAULT_STYLE_INSTRUCTIONS, **(mapping or {})}
    parts = [mapping.get(style, "") if style in DEFAULT_STYLE_INSTRUCTIONS else ""]
    if speed < 0.95:
        parts.append("语速稍慢")
    elif speed > 1.05:
        parts.append("语速稍快")
    if energy is not None:
        if energy < 0.9:
            parts.append("声音轻一些")
        elif energy > 1.1:
            parts.append("更有活力")
    sentences = [base.strip().rstrip("。 ，,"), "，".join(p for p in parts if p)]
    return "。".join(p for p in sentences if p) + ("。" if any(sentences) else "")


def pcm_to_wav(pcm: bytes) -> bytes:
    if not pcm or len(pcm) % 2:
        raise ValueError("Breeze returned empty or incomplete s16le PCM")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(pcm)
    return output.getvalue()


class TTSEngine(TTSInterface):
    supported_controls = frozenset(
        {"speed", "style", "energy", "voice_id", "instruction"}
    )

    def __init__(
        self,
        voice_id: str,
        base_url="http://127.0.0.1:8080",
        base_instruction="自然、温柔的中文陪伴者",
        cfg_scale=1.0,
        seed=42,
        timeout=60.0,
        max_concurrency=1,
        style_instructions=None,
        presets=None,
        voices_dir=None,
        *,
        transport=None,
    ):
        if not VOICE_NAME.fullmatch(voice_id or ""):
            raise ValueError("A saved Breeze voice_id is required")
        if isinstance(max_concurrency, bool) or max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.voice_id = voice_id
        self.base_url = base_url.rstrip("/")
        self.base_instruction = base_instruction
        self.cfg_scale = cfg_scale
        self.seed = seed
        self.timeout = timeout
        self.style_instructions = style_instructions
        self.presets = presets or {}
        self.voices_dir = Path(voices_dir).resolve() if voices_dir else None
        self._transport = transport
        self._semaphore = asyncio.Semaphore(max_concurrency)
        # A common gate also protects against synchronous callers and previews.
        self._slots = threading.BoundedSemaphore(max_concurrency)
        try:
            with self._sync_client(timeout=min(timeout, 3.0)) as client:
                client.get("/health").raise_for_status()
        except (httpx.HTTPError, OSError):
            logger.warning("Breeze health check failed; speech will degrade to silence")

    def _sync_client(self, **kwargs):
        return httpx.Client(
            base_url=self.base_url,
            timeout=kwargs.get("timeout", self.timeout),
            transport=self._transport,
            trust_env=False,
        )

    def _async_client(self, **kwargs):
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=kwargs.get("timeout", self.timeout),
            transport=self._transport,
            trust_env=False,
        )

    @asynccontextmanager
    async def _generation_slot(self):
        async with self._semaphore:
            while not self._slots.acquire(blocking=False):
                await asyncio.sleep(0.01)
            try:
                yield
            finally:
                self._slots.release()

    @contextmanager
    def _sync_slot(self):
        with self._slots:
            yield

    async def available(self):
        try:
            async with self._async_client(timeout=2.0) as client:
                response = await client.get("/health")
                response.raise_for_status()
            return True
        except (httpx.HTTPError, OSError):
            return False

    async def _request(self, method, path, *, allow_missing=False, **kwargs):
        async with self._generation_slot(), self._async_client() as client:
            for attempt in range(4):
                response = await client.request(method, path, **kwargs)
                if response.status_code == 409 and attempt < 3:
                    await asyncio.sleep(0.2 * 2**attempt)
                    continue
                if not (allow_missing and response.status_code == 404):
                    response.raise_for_status()
                return response

    def _fields(self, text, *, voice_id=None, instruction=None, seed=None):
        fields = {
            "text": text,
            "instruction": self.base_instruction
            if instruction is None
            else instruction,
            "cfg_scale": str(self.cfg_scale),
            "seed": str(self.seed if seed is None else seed),
        }
        # Empty id is used ONLY for explicit voice-design previews.
        if voice_id != "":
            selected = voice_id or self.voice_id
            if not VOICE_NAME.fullmatch(selected):
                raise ValueError("Invalid Breeze voice_id")
            fields["voice_id"] = selected
        return fields

    async def synthesize_wav(self, text, *, voice_id=None, instruction=None, seed=None):
        fields = self._fields(
            text, voice_id=voice_id, instruction=instruction, seed=seed
        )
        logger.debug(
            "Breeze synthesis: length={}, voice_id={}",
            len(text),
            fields.get("voice_id", "design"),
        )
        response = await self._request("POST", "/v1/audio/speech", data=fields)
        return pcm_to_wav(response.content)

    async def register_voice(self, name, wav, ref_text=PREVIEW_TEXT):
        if not VOICE_NAME.fullmatch(name):
            raise ValueError("Invalid Breeze voice name")
        response = await self._request(
            "POST",
            "/v1/voices",
            data={"name": name, "ref_text": ref_text},
            files={"ref_audio": ("reference.wav", wav, "audio/wav")},
        )
        return response.json()

    async def delete_voice(self, name):
        if not VOICE_NAME.fullmatch(name) or not name.startswith("user_"):
            raise ValueError("Only owned custom voices can be removed")
        await self._request("DELETE", f"/v1/voices/{name}", allow_missing=True)
        # Upstream DELETE only evicts memory. Remove the saved file when explicitly
        # configured on the same machine; never derive a directory from API input.
        if self.voices_dir:
            path = self.voices_dir / f"{name}.breeze"
            if path.resolve().parent != self.voices_dir:
                raise ValueError("Voice path escaped voices_dir")
            path.unlink(missing_ok=True)
        return {"deleted": name, "file_kept": self.voices_dir is None}

    def _save(self, wav, file_name_no_ext):
        path = Path(
            self.generate_cache_file_name(file_name_no_ext or uuid4().hex, "wav")
        )
        try:
            path.write_bytes(wav)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return str(path)

    async def async_generate_audio(self, text, file_name_no_ext=None):
        return await self.async_generate_audio_with_options(text, file_name_no_ext)

    async def async_generate_audio_with_options(
        self,
        text,
        file_name_no_ext=None,
        *,
        speed=1.0,
        style=None,
        energy=None,
        voice_id=None,
        instruction=None,
    ):
        direction = build_instruction(
            self.base_instruction if instruction is None else instruction,
            style,
            speed,
            energy,
            self.style_instructions,
        )
        try:
            wav = await self.synthesize_wav(
                text, voice_id=voice_id, instruction=direction
            )
            return self._save(wav, file_name_no_ext)
        except (httpx.HTTPError, OSError, ValueError) as error:
            logger.warning(
                "Breeze synthesis failed: length={}, voice_id={}, error={}",
                len(text),
                voice_id or self.voice_id,
                type(error).__name__,
            )
            return None

    def generate_audio(self, text, file_name_no_ext=None):
        try:
            with self._sync_slot(), self._sync_client() as client:
                for attempt in range(4):
                    response = client.post("/v1/audio/speech", data=self._fields(text))
                    if response.status_code == 409 and attempt < 3:
                        time.sleep(0.2 * 2**attempt)
                        continue
                    response.raise_for_status()
                    return self._save(pcm_to_wav(response.content), file_name_no_ext)
        except (httpx.HTTPError, OSError, ValueError) as error:
            logger.warning(
                "Breeze synthesis failed: length={}, voice_id={}, error={}",
                len(text),
                self.voice_id,
                type(error).__name__,
            )
            return None
