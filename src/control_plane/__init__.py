"""Backward-compatibility shim for arc.control_plane."""
import sys

import arc.control_plane as _cp
from arc.control_plane import *

sys.modules[__name__] = _cp
