"""Argument parsing that behaves the same on every supported Python version.

Before Python 3.12, ``argparse`` consumes an optional positional (such as a
trailing ``[path]``) as empty as soon as the positionals before it match, so
``prism app add ID --stack S PATH`` rejects ``PATH``. ``IntermixedParser`` reads
options and positionals in any order, which is what Python 3.12 does.
"""

from __future__ import annotations

import argparse


class IntermixedParser(argparse.ArgumentParser):
    """A parser that accepts options between and after its positionals on every Python version.

    A parser with sub-commands parses as usual; only its leaf sub-commands are intermixed.
    """

    _intermixed_active = False

    def parse_known_args(self, args=None, namespace=None):
        if self._intermixed_active or any(isinstance(action, argparse._SubParsersAction) for action in self._actions):
            return super().parse_known_args(args, namespace)
        self._intermixed_active = True
        try:
            return self.parse_known_intermixed_args(args, namespace)
        finally:
            self._intermixed_active = False
