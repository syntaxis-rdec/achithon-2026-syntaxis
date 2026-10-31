"""One-command automated submission packager for PS08 AGENTGATE.

Creates a clean, reproducible submission zip file strictly adhering to docs/SUBMISSION.md.
Validates that no virtualenvs, temporary caches, or unredacted secrets are packaged.
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

OUTPUT_ZIP = ROOT / "agentgate-PS08-submission.zip"

INCLUDED_DIRS = [
    "agentgate",
    "benchmark",
    "data",
    "demo",
    "docs",
    "presentation",
    "redteam",
    "scripts",
    "tests",
    "web",
]

INCLUDED_FILES = [
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "app.py",
    "LICENSE",
    "log.txt",
    "pyproject.toml",
    "pytest.ini",
    "README.md",
    "refine.py",
    "requirements.txt",
    "SECURITY.md",
    "start.py",
]

# Prohibited paths/extensions
FORBIDDEN_EXTENSIONS = {".pyc", ".pyo", ".sqlite", ".db", ".sqlite-wal", ".sqlite-shm"}
FORBIDDEN_DIR_NAMES = {".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".git", "exports"}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=\-]{20,}", re.IGNORECASE),
]


def check_secrets_in_text(text: str, filename: str) -> bool:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            print(f"ERROR: Secret pattern detected in {filename}: {match.group()[:10]}...", file=sys.stderr)
            return False
    return True


def collect_files() -> list[Path]:
    files_to_pack: list[Path] = []

    # 1. Root files
    for fname in INCLUDED_FILES:
        p = ROOT / fname
        if p.exists() and p.is_file():
            files_to_pack.append(p)

    # 2. Directories
    for dname in INCLUDED_DIRS:
        dpath = ROOT / dname
        if not dpath.exists():
            continue
        for root, dirs, files in os.walk(dpath):
            dirs[:] = [d for d in dirs if d not in FORBIDDEN_DIR_NAMES]
            for file in files:
                if file.startswith("~$"):
                    continue
                fpath = Path(root) / file
                if fpath.suffix.lower() in FORBIDDEN_EXTENSIONS:
                    continue
                files_to_pack.append(fpath)

    # 3. Optional agent-trace if present
    trace_dir = ROOT / "agent-trace"
    if trace_dir.exists():
        for root, dirs, files in os.walk(trace_dir):
            for file in files:
                if file.startswith("~$"):
                    continue
                fpath = Path(root) / file
                if fpath.suffix.lower() not in FORBIDDEN_EXTENSIONS:
                    files_to_pack.append(fpath)

    return sorted(files_to_pack)


def main() -> int:
    print("Collecting files for submission archive...")
    files = collect_files()

    print(f"Found {len(files)} files to validate and package.")

    # Validate secrets
    for f in files:
        if f.suffix in {".py", ".md", ".json", ".txt", ".ini", ".csv"}:
            try:
                content = f.read_text(encoding="utf-8")
                # Whitelist test strings that test redaction
                if f.name not in {"test_export.py", "export.py"}:
                    if not check_secrets_in_text(content, str(f.relative_to(ROOT))):
                        return 1
            except UnicodeDecodeError:
                pass

    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    print(f"Creating archive: {OUTPUT_ZIP.name}...")
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zipf:
        for f in files:
            arcname = f.relative_to(ROOT)
            zipf.write(f, arcname)

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"SUCCESS: Package created ({size_mb:.2f} MB, {len(files)} files).")
    print(f"Archive path: {OUTPUT_ZIP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

