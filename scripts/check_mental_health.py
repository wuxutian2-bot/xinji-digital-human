"""Read-only startup checks; never prints API keys or loads model weights."""

import argparse
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402
from open_llm_vtuber.config_manager import Config, read_yaml  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "conf.yaml")
    parser.add_argument(
        "--offline", action="store_true", help="Skip model API and port checks"
    )
    args = parser.parse_args()
    failures = []

    def check(label, ready):
        print(f"[{'OK' if ready else 'FAIL'}] {label}")
        if not ready:
            failures.append(label)

    try:
        config = Config.model_validate(read_yaml(str(args.config)))
    except Exception as error:
        print(
            f"[FAIL] Configuration could not be loaded ({type(error).__name__}); inspect conf.yaml"
        )
        return 1
    character = config.character_config
    check(
        "Selected frontend index.html",
        (ROOT / config.system_config.frontend_dir / "index.html").is_file(),
    )
    check(
        "MentalHealthAgent selected",
        character.agent_config.conversation_agent_choice == "mental_health_agent",
    )
    settings = character.agent_config.agent_settings.mental_health_agent
    if settings is None:
        return 1
    print(f"[INFO] Context rules version: {settings.context_version}")
    if settings.memory.enabled and settings.memory.mode == "local_user":
        print(
            f"[INFO] Long-term statistics: {settings.memory.trend.version}, timezone={settings.memory.trend.timezone}"
        )
    print(
        "[INFO] Decision: "
        + (
            "independent API configured; use scripts/check_decision.py to verify"
            if settings.decision.enabled
            else "local rules; independent API disabled"
        )
    )
    asr = character.asr_config
    if (
        asr.enabled
        and asr.asr_model == "sherpa_onnx_asr"
        and asr.sherpa_onnx_asr.model_type == "sense_voice"
    ):
        for name in ("sense_voice", "tokens"):
            value = getattr(asr.sherpa_onnx_asr, name)
            path = ROOT / (value or "__missing__")
            check(f"ASR {name} file", path.is_file() and path.stat().st_size > 0)
    else:
        print(f"[INFO] ASR enabled={asr.enabled}, backend={asr.asr_model}")
    api_template = read_yaml(str(ROOT / "config_templates/mental_health_orpo_api.yaml"))
    for key in ("model_name_or_path", "adapter_name_or_path"):
        check(f"ORPO template {key}", (ROOT / api_template[key]).is_dir())
    try:
        import imageio_ffmpeg

        check("FFmpeg binary", Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file())
    except Exception:
        check("FFmpeg binary", False)
    if not args.offline:
        try:
            with httpx.Client(timeout=5) as client:
                result = client.get(
                    settings.dialogue.base_url.rstrip("/") + "/models",
                    headers={
                        "Authorization": "Bearer " + settings.dialogue.llm_api_key
                    },
                )
                result.raise_for_status()
                check(
                    "Dialogue model advertised by API",
                    settings.dialogue.model
                    in {item["id"] for item in result.json().get("data", [])},
                )
        except Exception as error:
            check(f"Dialogue API reachable ({type(error).__name__})", False)
        try:
            with socket.create_connection(
                (config.system_config.host, config.system_config.port), timeout=2
            ):
                print("[INFO] Web port is occupied; avoid launching a duplicate server")
        except OSError:
            print("[INFO] Web port is available; start run_server.py")
    print(f"Completed: {len(failures)} failed check(s)")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
