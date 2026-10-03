"""Build a source-only submission, excluding runtime data and local credentials."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = (
    "src/",
    "scripts/",
    "tests/",
    "docs/",
    "prompts/",
    "config_templates/",
    "frontend-src/",
    "upgrade_codes/",
    "web_tool/",
    "backgrounds/",
    "avatars/",
    "assets/",
)
ROOT_FILES = {
    "run_server.py",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "model_dict.json",
    "LICENSE",
    "LICENSE-Live2D.md",
    "README.md",
    "README.CN.md",
    ".gitignore",
    ".gitmodules",
}
FORBIDDEN = {
    "node_modules",
    ".venv",
    ".git",
    "__pycache__",
    "dist",
    "out",
    "private",
    "logs",
    "chat_history",
}
REQUIRED_FILES = {
    "run_server.py",
    "pyproject.toml",
    "uv.lock",
    "upgrade_codes/upgrade_manager.py",
    "upgrade_codes/upgrade_core/constants.py",
    "src/open_llm_vtuber/server.py",
    "web_tool/index.html",
    "frontend-src/package.json",
    "frontend-src/package-lock.json",
    "config_templates/conf.default.yaml",
    "docs/companion_product.md",
    "LICENSE",
    "LICENSE-Live2D.md",
}


def selected_files():
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    )
    for name in sorted({n.decode("utf-8") for n in names.split(b"\0") if n}):
        path = ROOT / name
        if (name in ROOT_FILES or name.startswith(PREFIXES)) and not (
            set(path.relative_to(ROOT).parts) & FORBIDDEN
        ):
            if (
                path.is_file()
                and not path.is_symlink()
                and path.name != "user_credentials.json"
                and not path.name.startswith(".env.")
                and path.suffix not in {".sqlite3", ".db", ".pyc", ".env"}
            ):
                yield name, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = list(selected_files())
    missing = REQUIRED_FILES - {name for name, _ in files}
    if missing:
        raise ValueError(f"Required submission files are missing: {sorted(missing)}")
    manifest = {
        "version": "companion-2026-10-01",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        .decode()
        .strip(),
        "files": {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files
        },
        "excluded": [
            "conf.yaml",
            "private",
            "chat_history",
            "logs",
            "databases",
            "models",
            "Live2D model assets",
            "builds",
            "environments",
        ],
        "entry": "docs/companion_product.md",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, path in files:
            archive.write(path, name)
        archive.writestr(
            "MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip():
            raise ValueError("Corrupt ZIP")
        for name, digest in manifest["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError(f"Hash mismatch: {name}")
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
