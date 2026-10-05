"""Make ``tempfile`` hand out real paths, so a test's workspace path equals its resolved path.

Prism rejects a workspace whose path crosses a symlink, junction or reparse
point, and its code compares resolved paths. Some systems return a temporary
directory that is not its own real path: macOS puts it under the ``/var``
symlink, and Windows can return an 8.3 short name such as ``RUNNER~1``. A test
that builds its paths from such a name would then be rejected for the wrong
reason, or would fake a reparse point on a path the code never sees.

Every test module that creates temporary directories imports this module
before it uses ``tempfile``.
"""

from __future__ import annotations

import os
import tempfile

tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
