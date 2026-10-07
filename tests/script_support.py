"""Load a script of ``scripts/`` as a module, for tests of the maintenance scripts whose names carry hyphens."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def load_script(filename: str) -> ModuleType:
    """``scripts/<filename>`` imported under the name ``script_<stem with underscores>``."""

    path = REPO_ROOT / "scripts" / filename
    name = "script_" + path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
