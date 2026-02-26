#!/usr/bin/env python3
"""Comply With Me — run with: python3 comply_with_me.py"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = SCRIPT_DIR / ".cwm-venv"
VENV_PYTHON = VENV_DIR / "bin" / "python3"

REQUIRED = [
    ("requests",       "requests"),
    ("beautifulsoup4", "bs4"),
]


def _missing(python: Path) -> list[str]:
    missing = []
    for pkg_name, import_name in REQUIRED:
        r = subprocess.run(
            [str(python), "-c", f"import {import_name}"],
            capture_output=True,
        )
        if r.returncode != 0:
            missing.append(pkg_name)
    return missing


def _has_pip() -> bool:
    r = subprocess.run([str(VENV_PYTHON), "-m", "pip", "--version"], capture_output=True)
    return r.returncode == 0


def _venv_ok() -> bool:
    """True if venv exists and has a working pip."""
    return VENV_DIR.exists() and VENV_PYTHON.exists() and _has_pip()


def _can_create_venv() -> bool:
    try:
        import ensurepip  # noqa: F401
        return True
    except ImportError:
        return False


def _bootstrap() -> None:
    """Ensure a local venv exists with required packages, then re-exec inside it."""
    import shutil

    # Detect and remove a broken venv (has Python but no pip)
    if VENV_DIR.exists() and not _venv_ok():
        shutil.rmtree(VENV_DIR)

    if not VENV_DIR.exists():
        if not _can_create_venv():
            ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            print("Comply With Me needs a local environment but cannot create one.\n")
            print("On Debian/Ubuntu, install the missing package first:")
            print(f"  sudo apt install python{ver}-venv")
            print("\nThen run the script again.")
            sys.exit(1)

        print("Comply With Me needs a local environment to run.\n")
        print(f"It will be created at: {VENV_DIR}\n")
        try:
            answer = input("Set it up now? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(1)

        print("Creating environment...", end="", flush=True)
        import venv as _venv
        try:
            _venv.create(str(VENV_DIR), with_pip=True)
            print(" done.")
        except BaseException:
            print(" failed.")
            if VENV_DIR.exists():
                shutil.rmtree(VENV_DIR)
            ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            print("\nCould not create a virtual environment.")
            print("On Debian/Ubuntu, install the missing package first:")
            print(f"  sudo apt install python{ver}-venv")
            sys.exit(1)

    missing = _missing(VENV_PYTHON)
    if missing:
        print(f"Installing: {', '.join(missing)}...", end="", flush=True)
        result = subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "--quiet"] + missing
        )
        if result.returncode != 0:
            print(" failed.")
            print(f"\nTry manually: {VENV_PYTHON} -m pip install {' '.join(missing)}")
            sys.exit(1)
        print(" done.")
        print()

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__] + sys.argv[1:])


def _in_managed_venv() -> bool:
    return Path(sys.executable).resolve().is_relative_to(VENV_DIR)


if not _in_managed_venv():
    _bootstrap()

# Running inside .cwm-venv — all deps are present
sys.path.insert(0, str(SCRIPT_DIR))
from comply_with_me.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
