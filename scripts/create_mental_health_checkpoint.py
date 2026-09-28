"""Archive modified project source with hashes, excluding local user data."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("src/", "tests/", "scripts/", "docs/", "config_templates/", "frontend-src/")
ROOT_FILES = {
    ".gitignore",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "model_dict.json",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(
            "Choose a new checkpoint name; existing checkpoints are immutable"
        )
    names = set()
    for raw in (
        git("diff", "--name-only", "HEAD", "-z"),
        git("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        names.update(name.decode("utf-8") for name in raw.split(b"\0") if name)
    selected = sorted(
        name for name in names if name.startswith(PREFIXES) or name in ROOT_FILES
    )
    files, deleted = {}, []
    for name in selected:
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Path outside workspace")
        if not path.exists():
            deleted.append(name)
        elif path.is_file():
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upstream_commit": git("rev-parse", "HEAD").decode().strip(),
        "frontend_source_commit": "3d57a9a0125a0ca13e5d096f7092e4e494ed389e",
        "frontend_build_commit": git("-C", "frontend", "rev-parse", "HEAD")
        .decode()
        .strip(),
        "files": files,
        "deleted": deleted,
        "excluded": [
            "conf.yaml",
            "models",
            "logs",
            "chat_history",
            "mental_health_memory",
            "node_modules",
            "frontend build output",
            "private",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(ROOT / name, name)
        archive.writestr(
            "CHECKPOINT.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive validation failed")
        for name, digest in files.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Checkpoint hash mismatch")
    print(
        json.dumps(
            {
                "path": str(args.output.resolve()),
                "files": len(files),
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
