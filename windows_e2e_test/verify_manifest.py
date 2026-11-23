#!/usr/bin/env python3
"""Verify the generated Native Messaging host manifest (HOTFIX 4, P1).

Replaces the BAT's findstr checks. findstr conflates "string not
found" (exit 1) and "file/path error" (exit 2), and the BAT had no
existence check — so a path/read failure was misreported as a
content error (ATTEMPT-05/06: install actually succeeded, the
manifest content was correct, but verification reported a content
error, and the jumbled log made it look contradictory).

This checker:
- resolves the manifest path to its LONG form (GetLongPathNameW via
  ctypes on Windows, os.path.realpath fallback) and also computes
  the SHORT form (GetShortPathNameW), and verifies the file is
  accessible via BOTH the long and the short path AND the as-given
  path — so a short-path access problem is diagnosed, not guessed
  from fsutil (fsutil only reports the volume's short-name
  generation setting; existing short names may still exist);
- runs findstr (Windows only, best-effort) and records its ORIGINAL
  exit code + stderr for diagnosis (the verdict does NOT depend on
  findstr — it is evidence, not the check);
- parses the JSON and verifies name / path / type /
  allowed_origins;
- prints a structured JSON result AND a human-readable summary, so
  install.py's success result, the actual manifest content, and
  this verification land in the same stage log.

Exit codes: 0 = manifest valid; 1 = content mismatch;
2 = file/parse error (missing, unreadable, invalid JSON).

Usage:
    python verify_manifest.py --manifest <path>
        --host-name com.agentrelay.host.e2e
        --extension-id <id> --exe-path <path to host exe>
"""

import argparse
import json
import os
import subprocess
import sys

try:
    import ctypes
    from ctypes import wintypes
except ImportError:  # pragma: no cover - ctypes is stdlib on CPython
    ctypes = None


def long_path(path):
    """Return the long (non-8.3) form of path.

    On Windows this uses GetLongPathNameW, which is the verified way
    to expand a short name such as HIHOME~1. %~f in a BAT only
    converts to an absolute path — it does NOT guarantee the short
    name is expanded. Falls back to os.path.realpath when the API is
    unavailable (non-Windows, or ctypes missing).
    """
    if ctypes is not None and os.name == "nt":
        try:
            buf = ctypes.create_unicode_buffer(32767)
            n = ctypes.windll.kernel32.GetLongPathNameW(path, buf, 32767)
            if n and n < 32767:
                return buf.value
        except Exception:
            pass
    return os.path.realpath(path)


def short_path(path):
    """Return the 8.3 short form of path (Windows only).

    Used to test whether the short path can access the same file —
    the check must be done by actually trying the path, not by
    reading fsutil (which only reports the volume's short-name
    generation setting; existing short names may still exist).
    On non-Windows, returns the path unchanged.
    """
    if ctypes is not None and os.name == "nt":
        try:
            buf = ctypes.create_unicode_buffer(32767)
            n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 32767)
            if n and n < 32767:
                return buf.value
        except Exception:
            pass
    return path


def run_findstr(manifest_path, needle):
    """Run findstr for needle on the manifest and return its ORIGINAL
    exit code and stderr (diagnostic only — the verdict does not
    depend on findstr). On non-Windows findstr does not exist;
    returns (None, "findstr_not_available").
    """
    try:
        proc = subprocess.run(
            ["findstr", "/C:" + needle, manifest_path],
            capture_output=True, text=True, timeout=30)
        return proc.returncode, proc.stderr
    except FileNotFoundError:
        return None, "findstr_not_available"
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        return None, f"findstr_error:{exc}"


def verify(manifest_path, host_name, extension_id, exe_path):
    """Verify the manifest. Returns (exit_code, result_dict)."""
    result = {
        "manifest_given": manifest_path,
        "manifest_long": long_path(manifest_path),
        "manifest_short": short_path(manifest_path),
        "accessible_given": os.path.isfile(manifest_path),
        "accessible_long": os.path.isfile(long_path(manifest_path)),
        "accessible_short": os.path.isfile(short_path(manifest_path)),
        "findstr_exit": None,
        "findstr_stderr": "",
        "manifest": None,
        "errors": [],
    }
    if not os.path.isfile(manifest_path):
        result["errors"].append(
            f"manifest file not found or not a file: {manifest_path}")
        return 2, result
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as exc:
        result["errors"].append(f"manifest unreadable or invalid JSON: {exc}")
        return 2, result
    result["manifest"] = manifest

    # Diagnostic: findstr's original exit code + stderr, recorded so
    # a future "findstr says missing but the content is right" can be
    # explained from the log instead of guessed.
    exit_code, stderr = run_findstr(manifest_path, host_name)
    result["findstr_exit"] = exit_code
    result["findstr_stderr"] = stderr

    # Content checks. The "path" field is the host EXE path; compare
    # after normalising both sides to long form (the install may
    # have been given a short-form dest dir) and case-insensitively
    # on Windows.
    if manifest.get("name") != host_name:
        result["errors"].append(
            f"name mismatch: manifest has {manifest.get('name')!r}, "
            f"expected {host_name!r}")
    expected_path = long_path(exe_path)
    actual_path = manifest.get("path")
    if not isinstance(actual_path, str) or \
            os.path.normcase(long_path(actual_path)) != \
            os.path.normcase(expected_path):
        result["errors"].append(
            f"path mismatch: manifest has {actual_path!r}, "
            f"expected {exe_path!r} (long form {expected_path!r})")
    if manifest.get("type") != "stdio":
        result["errors"].append(
            f"type mismatch: manifest has {manifest.get('type')!r}, "
            f"expected 'stdio'")
    expected_origins = [f"chrome-extension://{extension_id}/"]
    if manifest.get("allowed_origins") != expected_origins:
        result["errors"].append(
            f"allowed_origins mismatch: manifest has "
            f"{manifest.get('allowed_origins')!r}, "
            f"expected {expected_origins!r}")
    if result["errors"]:
        return 1, result
    return 0, result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify a generated Native Messaging host manifest.")
    parser.add_argument("--manifest", required=True,
                        help="path to the generated host manifest JSON")
    parser.add_argument("--host-name", required=True,
                        help="expected host name, e.g. "
                             "com.agentrelay.host.e2e")
    parser.add_argument("--extension-id", required=True,
                        help="expected extension ID for allowed_origins")
    parser.add_argument("--exe-path", required=True,
                        help="expected path to the host EXE (the "
                             "manifest's 'path' field)")
    args = parser.parse_args(argv)

    exit_code, result = verify(args.manifest, args.host_name,
                               args.extension_id, args.exe_path)
    # The JSON result goes to stdout (machine-readable); the
    # human-readable summary goes to stderr. The BAT redirects both
    # into the same stage log, so the log still carries both.
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if exit_code == 0:
        print("Manifest verification: PASS "
              f"(name={args.host_name}, "
              f"allowed_origins matches extension ID {args.extension_id})",
              file=sys.stderr)
    elif exit_code == 1:
        print("Manifest verification: FAIL (content mismatch): "
              + "; ".join(result["errors"]), file=sys.stderr)
    else:
        print("Manifest verification: FAIL (file/parse error): "
              + "; ".join(result["errors"]), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
