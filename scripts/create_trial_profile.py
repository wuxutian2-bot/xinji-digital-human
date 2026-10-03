"""Create a new local profile without copying personal memory or chat history."""

import argparse
from pathlib import Path
import sys
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from open_llm_vtuber.config_manager import validate_config  # noqa: E402


def create_profile(source, output, label, *, port=12393, synthetic=False):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Output directory already exists; use a new private directory")
    config = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
    identity = "trial_" + uuid4().hex
    system = config["system_config"]
    system.update(
        host="localhost",
        port=port,
        enable_proxy=False,
        trial_mode=True,
        synthetic_demo=synthetic,
        trial_label=label,
        frontend_dir=str(ROOT / "frontend-src" / "dist" / "web"),
        config_alts_dir=str(output / "characters"),
    )
    character = config["character_config"]
    character["conf_uid"] = identity
    character["conf_name"] = "心迹 · " + label
    agent = character["agent_config"]
    agent["conversation_agent_choice"] = "mental_health_agent"
    settings = agent["agent_settings"]["mental_health_agent"]
    settings["context_version"] = 2
    settings.setdefault("decision", {})["enabled"] = False
    settings["memory"].update(
        mode="local_user",
        enabled=True,
        user_id=identity,
        sqlite_path=str(output / "states.sqlite3"),
        storage_path=str(output / "legacy-unused.jsonl"),
        trend={
            "version": "daily_v2",
            "timezone": "Asia/Shanghai",
            "min_observed_days": 3,
            "min_topic_days": 3,
            "stale_after_days": 7,
        },
    )
    validate_config(config)
    output.mkdir(parents=True)
    (output / "characters").mkdir()
    path = output / "conf.yaml"
    path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="conf.yaml")
    parser.add_argument(
        "--output",
        required=True,
        help="New directory under private/trials; contains local API credentials",
    )
    parser.add_argument("--label", required=True, help="Anonymous label, e.g. P01")
    parser.add_argument("--port", type=int, default=12393)
    parser.add_argument("--synthetic-demo", action="store_true")
    args = parser.parse_args()
    allowed = (ROOT / "private" / "trials").resolve()
    target = Path(args.output).resolve()
    if allowed not in target.parents:
        parser.error(
            "Profiles must be inside private/trials to keep local credentials out of submissions"
        )
    path = create_profile(
        args.source, target, args.label, port=args.port, synthetic=args.synthetic_demo
    )
    print(
        f'Profile created. From project root run: .\\.venv\\Scripts\\python.exe run_server.py --config "{path}"'
    )


if __name__ == "__main__":
    main()
