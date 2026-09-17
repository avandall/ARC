"""Backward-compatibility shim for arc.execution."""
import sys

import arc.execution as _exec
from arc.execution import *

sys.modules[__name__] = _exec
