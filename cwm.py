#!/usr/bin/env python3
"""Comply With Me — run with: python3 cwm.py"""

import sys
from pathlib import Path

# Make the project root importable without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from comply_with_me.cli import main

if __name__ == "__main__":
    main()
