"""Start one local SFT/ORPO API using the prepared LLaMA-Factory environment."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from open_llm_vtuber.config_manager import Config, read_yaml  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", choices=["sft", "orpo"], default="orpo")
    parser.add_argument("--config", type=Path, default=ROOT / "conf.yaml")
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path("D:/模型微调/.venv-train/Scripts/llamafactory-cli.exe"),
    )
    args = parser.parse_args()
    settings = Config.model_validate(
        read_yaml(str(args.config))
    ).character_config.agent_config.agent_settings.mental_health_agent.dialogue
    url = urlsplit(settings.base_url)
    if url.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("This launcher only supports a local IPv4 endpoint")
    if not args.executable.is_file():
        raise FileNotFoundError(
            "Prepared LLaMA-Factory executable missing; use --executable"
        )
    port = url.port or 8000
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    env = os.environ.copy()
    env.update(
        API_HOST="127.0.0.1",
        API_PORT=str(port),
        API_MODEL_NAME=f"mental-health-{args.adapter}",
        API_KEY=settings.llm_api_key,
        PYTHONIOENCODING="utf-8",
    )
    print(
        f"Starting {args.adapter.upper()} on local port {port}; use one model service at a time.",
        flush=True,
    )
    return subprocess.call(
        [
            str(args.executable),
            "api",
            str(ROOT / f"config_templates/mental_health_{args.adapter}_api.yaml"),
        ],
        cwd=ROOT,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
