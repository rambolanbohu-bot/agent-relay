#!/usr/bin/env python3
"""Resolve a path to its long form (HOTFIX 4, P1).

Prints the long form of the given path to stdout and exits 0 when
the resolved path exists and is accessible. Exits 1 otherwise
(prints the reason to stderr).

Uses GetLongPathNameW via ctypes on Windows — the Windows-verified
way to convert an 8.3 short path such as HIHOME~1 to its long form.
%~f in a BAT only converts to an absolute path; it does NOT
guarantee the short name is expanded. Falls back to
os.path.realpath when GetLongPathNameW is unavailable.

The BAT calls this to resolve %TEMP% before building the isolated
test dir, so no stage ever works through a short-form path.

Usage: python resolve_long_path.py <path>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_manifest import long_path  # noqa: E402


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: resolve_long_path.py <path>", file=sys.stderr)
        return 2
    resolved = long_path(argv[0])
    if os.path.exists(resolved):
        print(resolved)
        return 0
    print(f"resolved path does not exist: {resolved!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
