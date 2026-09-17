"""Pytest configuration and sys.path setup for ARC."""

import sys
from pathlib import Path

# Add src to sys.path so 'arc' and 'arc_sdk' are directly importable in all test runners
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
