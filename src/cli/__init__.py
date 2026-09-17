"""Backward-compatibility shim for arc.cli."""
import sys

import arc.cli as _cli
from arc.cli import *

sys.modules[__name__] = _cli
