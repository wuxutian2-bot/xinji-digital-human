"""Sequentially start/evaluate/stop SFT and ORPO using owned local processes only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import httpx  # noqa: E402
from open_llm_vtuber.config_manager import Config, read_yaml  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "conf.yaml")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(
            "Choose a new output directory to preserve earlier results"
        )
    settings = Config.model_validate(
        read_yaml(str(args.config))
    ).character_config.agent_config.agent_settings.mental_health_agent.dialogue
    url = urlsplit(settings.base_url)
    if url.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Only a dedicated local endpoint is supported")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", url.port or 8000))
    args.output_dir.mkdir(parents=True)
    failures = []
    for adapter in ("sft", "orpo"):
        served = f"mental-health-{adapter}"
        template = ROOT / f"config_templates/mental_health_{adapter}_api.yaml"
        adapter_path = Path(read_yaml(str(template))["adapter_name_or_path"])
        fingerprints = {
            "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
            "adapter_config_sha256": hashlib.sha256(
                (adapter_path / "adapter_config.json").read_bytes()
            ).hexdigest(),
            "adapter_weights_sha256": hashlib.sha256(
                (adapter_path / "adapter_model.safetensors").read_bytes()
            ).hexdigest(),
        }
        with (args.output_dir / f"{adapter}-service.log").open(
            "w", encoding="utf-8"
        ) as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_dialogue_api.py"),
                    "--adapter",
                    adapter,
                    "--config",
                    str(args.config.resolve()),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + 180
                with httpx.Client(
                    timeout=3,
                    headers={"Authorization": "Bearer " + settings.llm_api_key},
                ) as client:
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(
                                "Owned model service exited during startup"
                            )
                        try:
                            response = client.get(
                                settings.base_url.rstrip("/") + "/models"
                            )
                            if response.status_code == 200 and served in {
                                item["id"] for item in response.json().get("data", [])
                            }:
                                break
                        except (httpx.HTTPError, ValueError):
                            pass
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Model startup timed out")
                        time.sleep(1)
                    warmup = client.post(
                        settings.base_url.rstrip("/") + "/chat/completions",
                        json={
                            "model": served,
                            "messages": [
                                {"role": "user", "content": "你好，请简短回答。"}
                            ],
                            "temperature": 0,
                            "max_tokens": 16,
                        },
                        timeout=60,
                    )
                    warmup.raise_for_status()
                report_path = args.output_dir / f"{adapter}.json"
                print(
                    f"Evaluating {adapter}; dedicated sequential service after warmup",
                    flush=True,
                )
                status = subprocess.call(
                    [
                        sys.executable,
                        str(ROOT / "scripts/evaluate_mental_health.py"),
                        "--config",
                        str(args.config.resolve()),
                        "--dialogue",
                        "model",
                        "--model",
                        served,
                        "--run-note",
                        "Sequential single model service after one warmup; no automated browser interaction during this run",
                        "--output",
                        str(report_path.resolve()),
                    ],
                    cwd=ROOT,
                )
                if report_path.exists():
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    report["model_artifacts"] = fingerprints
                    report_path.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                if status:
                    failures.append(adapter)
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            check=True,
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    else:
                        process.terminate()
                    process.wait(timeout=15)
    print(
        f"Pair complete; failures={failures}. Restart scripts/run_dialogue_api.py --adapter orpo for interactive use."
    )
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
