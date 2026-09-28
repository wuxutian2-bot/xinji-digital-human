import sys
import os
import asyncio

import edge_tts
from loguru import logger
from .tts_interface import TTSInterface

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


# Check out doc at https://github.com/rany2/edge-tts
# Use `edge-tts --list-voices` to list all available voices


class TTSEngine(TTSInterface):
    supported_controls = frozenset({"speed"})

    async def async_generate_audio_with_options(
        self, text: str, file_name_no_ext=None, *, speed: float = 1.0
    ) -> str:
        from .voice_controls import resolve_voice_controls
        from types import SimpleNamespace

        speed = resolve_voice_controls(self, SimpleNamespace(voice_speed=speed))[
            "speed"
        ]
        path = self.generate_cache_file_name(file_name_no_ext, self.file_extension)
        rate = f"{round((speed - 1.0) * 100):+d}%"
        try:
            await edge_tts.Communicate(text, self.voice, rate=rate).save(path)
            return path
        except (Exception, asyncio.CancelledError):
            if os.path.exists(path):
                self.remove_file(path, verbose=False)
            raise

    def __init__(self, voice="en-US-AvaMultilingualNeural"):
        self.voice = voice

        self.temp_audio_file = "temp"
        self.file_extension = "mp3"
        self.new_audio_dir = "cache"

        if not os.path.exists(self.new_audio_dir):
            os.makedirs(self.new_audio_dir)

    def generate_audio(self, text, file_name_no_ext=None):
        """
        Generate speech audio file using TTS.
        text: str
            the text to speak
        file_name_no_ext: str
            name of the file without extension


        Returns:
        str: the path to the generated audio file

        """
        file_name = self.generate_cache_file_name(file_name_no_ext, self.file_extension)

        try:
            communicate = edge_tts.Communicate(text, self.voice)
            communicate.save_sync(file_name)
        except Exception as e:
            logger.critical(f"\nError: edge-tts unable to generate audio: {e}")
            logger.critical("It's possible that edge-tts is blocked in your region.")
            return None

        return file_name


# en-US-AvaMultilingualNeural
# en-US-EmmaMultilingualNeural
# en-US-JennyNeural
