"""Run the verified local GGUF Decision service alongside the ORPO service."""

import argparse
import os
from pathlib import Path
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-dir", type=Path, default=ROOT / "private/decision/llama-b10964-cpu"
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models/decision/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    )
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--gpu-layers", type=int, default=0)
    args = parser.parse_args()
    executable = args.runtime_dir.resolve() / "llama-server.exe"
    if not executable.is_file() or not args.model.is_file():
        parser.error(
            "Install the documented, checksum-verified runtime and weights first"
        )
    if (
        not 1024 <= args.port <= 65535
        or not 1 <= args.threads <= 64
        or not 0 <= args.gpu_layers <= 99
    ):
        parser.error("Invalid port, thread count or GPU layer count")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    command = [
        str(executable),
        "--model",
        str(args.model.resolve()),
        "--alias",
        "mental-health-decision-qwen2.5-1.5b",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
        "--ctx-size",
        "8192",
        "--parallel",
        "1",
        "--threads",
        str(args.threads),
        "--threads-batch",
        str(args.threads),
        "--n-gpu-layers",
        str(args.gpu_layers),
        "--no-webui",
        "--log-disable",
    ]
    print(
        f"Starting local Decision on port {args.port}; GPU layers={args.gpu_layers}",
        flush=True,
    )
    return subprocess.call(
        command,
        cwd=ROOT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
