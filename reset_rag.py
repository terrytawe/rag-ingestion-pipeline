"""
Reset or reinitialize local RAG state.

Usage examples:
  python reset_rag.py
  python reset_rag.py --force
  python reset_rag.py --force --rebuild
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from config import CHROMA_DIR, MANIFEST_PATH


def _confirm_reset() -> bool:
    answer = input(
        "This will delete chroma_db and manifest.json. Continue? [y/N]: "
    ).strip().lower()
    return answer in {"y", "yes"}


def _remove_path(path: Path) -> bool:
    if not path.exists():
        print(f"skip: {path} not found")
        return False

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()

    print(f"deleted: {path}")
    return True


def _run_rebuild() -> int:
    print("Running fresh ingest...")
    result = subprocess.run([sys.executable, "ingest.py"], check=False)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clear vector DB state and optionally rebuild embeddings."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Run ingest.py immediately after reset.",
    )
    args = parser.parse_args()

    if not args.force and not _confirm_reset():
        print("Cancelled.")
        return 0

    _remove_path(CHROMA_DIR)
    _remove_path(MANIFEST_PATH)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"initialized: {CHROMA_DIR}")

    if args.rebuild:
        return _run_rebuild()

    print("Reset complete. Run ingest.py to repopulate the vector store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())