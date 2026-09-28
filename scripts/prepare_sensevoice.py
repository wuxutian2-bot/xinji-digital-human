"""Install the official SenseVoice INT8 assets after SHA256 verification.

Run with the project Python. Does not edit conf.yaml or execute archive contents.
"""

import hashlib
from pathlib import Path
import tarfile
import time

import requests


ROOT = Path(__file__).resolve().parents[1]
NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
URL = (
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{NAME}.tar.bz2"
)
# Digest/size published by the upstream GitHub release asset API, 2026-09-22.
SHA256 = "7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e"
SIZE = 163002883
FILES = ("model.int8.onnx", "tokens.txt", "test_wavs/zh.wav", "LICENSE")


def install() -> None:
    destination = ROOT / "models" / NAME
    archive = ROOT / "models" / f"{NAME}.tar.bz2.part"
    archive.parent.mkdir(parents=True, exist_ok=True)
    offset = archive.stat().st_size if archive.exists() else 0
    if offset < SIZE:
        with requests.get(
            URL,
            headers={"Range": f"bytes={offset}-"} if offset else {},
            stream=True,
            timeout=(20, 60),
        ) as response:
            response.raise_for_status()
            resume = response.status_code == 206 and offset > 0
            if resume and not response.headers.get("Content-Range", "").startswith(
                f"bytes {offset}-"
            ):
                raise ValueError(
                    "Unexpected download range; existing partial file preserved"
                )
            total = offset if resume else 0
            last_report = time.monotonic()
            with archive.open("ab" if resume else "wb") as out:
                for chunk in response.iter_content(1024 * 256):
                    out.write(chunk)
                    total += len(chunk)
                    if time.monotonic() - last_report >= 10:
                        print(
                            f"Downloaded {total / 1024**2:.1f} / {SIZE / 1024**2:.1f} MiB",
                            flush=True,
                        )
                        last_report = time.monotonic()

    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if archive.stat().st_size != SIZE or digest.hexdigest() != SHA256:
        raise ValueError(
            f"Download checksum mismatch; not installed. Inspect {archive}"
        )

    # Select named regular files only; never extract links or archive paths.
    with tarfile.open(archive, "r:bz2") as bundle:
        for relative in FILES:
            member = bundle.getmember(f"{NAME}/{relative}")
            if not member.isfile() or member.size <= 0:
                raise ValueError(f"Invalid model asset: {relative}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(target.suffix + ".part")
            with bundle.extractfile(member) as source, partial.open("wb") as out:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    out.write(chunk)
            partial.replace(target)
            print(f"Verified asset: {relative} ({member.size} bytes)", flush=True)
    (destination / "archive.sha256").write_text(SHA256 + "\n", encoding="ascii")
    print(
        "SenseVoice assets ready. Configure model.int8.onnx and tokens.txt before enabling ASR."
    )


if __name__ == "__main__":
    install()
