#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — pre-delivery package check.

Why this exists: ChatGPT's independent review of the first RC4 ZIP
(2026-11-19 23:24) was CONDITIONAL REJECT with one P0 — the ZIP it
received was missing transport/agent-relay-host.exe, while install.py
requires that EXE or it refuses to install. The approval fix itself
PASSED. Dash verified the ZIP that was actually delivered DID contain
the EXE (224,515 bytes, SHA-256
0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de,
matching transport/agent-relay-host.exe.sha256), and ChatGPT's
computed ZIP hash (02dcf688...) differs from the published hash
(5beff152...) — so the file it received was NOT the file delivered.
Something stripped the EXE during download/re-upload (antivirus
quarantining .exe files inside ZIPs is a prime suspect) or a
different file was uploaded.

The SAME thing happened again with the RC4 hotfix (2026-11-20
10:13): ChatGPT received 85 entries with NO EXE, while Dash's
delivered ZIP has 86 entries with the EXE present (SHA-256
4129a0e0...). The transit path strips the EXE; the packaging itself
was NOT broken at build time. That is why the check below now also
verifies a contents manifest (MANIFEST.json) inside the package: the
receiver can verify completeness (entry count + per-file SHA-256)
and detect a transit strip immediately, instead of discovering it
from a failed install.

This script is the gate that prevents that class of failure from
reaching a reviewer again: a ZIP must NOT be published unless this
check passes on BOTH the package directory AND the final ZIP file.
The mandatory release procedure is tests/release_gate.py, which
runs this check on the directory, builds the ZIP, runs this check
on the ZIP, and only then writes the .sha256 file.

What it verifies:
  (a) every required install file exists in the package directory;
  (b) transport/agent-relay-host.exe's SHA-256 matches
      transport/agent-relay-host.exe.sha256;
  (c) MANIFEST.json exists and matches the package: every covered
      file is listed with the right SHA-256, no covered file is
      missing from the manifest, no unlisted file is present, and
      the recorded file_count / total_bytes match;
  (d) when given a ZIP path, the same files are present INSIDE the
      ZIP (via zipfile, the unzip -l equivalent), the EXE inside
      the ZIP has the same hash, and the manifest inside the ZIP
      matches the ZIP contents (and, when a directory is given too,
      is byte-identical to the directory's manifest).

The manifest deliberately does NOT cover: MANIFEST.json itself (it
cannot hash itself), __pycache__ / *.pyc (bytecode caches, never
shipped), and tests/test-output-*.txt (volatile run outputs —
unittest prints elapsed seconds, so their bytes change on every
run, including an independent re-run; hashing them would make the
manifest go stale the moment the suite runs). The exclusion list is
recorded inside MANIFEST.json itself, so the receiver knows exactly
what is not covered.

Usage (stdlib only, no dependencies):
    python3 tests/check_package.py            # check the package dir
    python3 tests/check_package.py <zip>      # check a ZIP file
    python3 tests/check_package.py --dir <dir> --zip <zip>
                                              # check both

Exit code: 0 only when every check passes. Any failure prints a
clear "PACKAGE CHECK FAILED" banner with each problem and exits 1.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

EXE_REL = "transport/agent-relay-host.exe"
HASH_REL = "transport/agent-relay-host.exe.sha256"
MANIFEST_REL = "MANIFEST.json"
MANIFEST_VERSION = "1.0.0-rc6"

# Files the install flow needs. If any of these is missing the
# install is broken (install.py refuses to install without the EXE),
# so a missing file is a hard failure, not a warning.
REQUIRED_FILES = (
    EXE_REL,
    HASH_REL,
    "transport/native_host/agent-relay-host.c",
    "transport/native_host/build_host_exe.bat",
    "SKILL.md",
    "install.py",
    "uninstall.py",
    "install.bat",
    "uninstall.bat",
    "transport/extension/manifest.json",
    "approvals/approvals.py",
    "approvals/local_approval_page.py",
    "orchestrator/run.py",
    "transport/relay_client.py",
    "transport/native_host.py",
    "transport/extension/content.js",
    "transport/extension/background.js",
    "docs/KNOWN-LIMITATIONS.md",
    "docs/INSTALL.md",
    "windows_e2e_test/run_e2e_test.bat",
    "windows_e2e_test/make_test_extension.py",
    # HOTFIX 6 (P1): the E2E stage logic moved from the monolithic
    # BAT into this Python runner; the BAT is now a thin entry.
    "windows_e2e_test/e2e_runner.py",
    # HOTFIX 4 (P1): the BAT now verifies the generated host
    # manifest with Python JSON parsing and resolves %TEMP% to its
    # long form with Python — both helpers are required.
    "windows_e2e_test/verify_manifest.py",
    "windows_e2e_test/resolve_long_path.py",
    "tests/test_content_js.py",
    "tests/test_adapter_nonce.py",
    "tests/test_e2e.py",
    "tests/content_js_harness.js",
    # HOTFIX 4 (P2-C / P1): the background.js session-binding
    # harness + its test, and the verify_manifest tests.
    "tests/test_background_js.py",
    "tests/background_js_harness.js",
    "tests/test_verify_manifest.py",
    # HOTFIX 5 (P1/P2): BAT CMD-parse safety + adapter
    # late-receipt reconciliation.
    "tests/test_bat_cmd_safety.py",
    "tests/test_adapter_late_receipt.py",
    # HOTFIX 6 (P1/B2/B3/B4): the E2E stage machine + adapter
    # collect_dom / diagnostics passthrough.
    "tests/test_e2e_runner.py",
    "tests/test_adapter_collect_dom.py",
    MANIFEST_REL,
    "tests/release_gate.py",
)

# Manifest exclusion list (also recorded inside MANIFEST.json).
MANIFEST_EXCLUDED_NOTE = (
    "MANIFEST.json (the manifest cannot hash itself)",
    "__pycache__/** and *.pyc (bytecode caches, not shipped)",
    "tests/test-output-*.txt (volatile run outputs: unittest prints "
    "elapsed seconds, so their bytes change on every run)",
)


def _manifest_included(rel):
    """True when a package-relative path is covered by MANIFEST.json."""
    if rel == MANIFEST_REL:
        return False
    parts = rel.replace("\\", "/").split("/")
    if "__pycache__" in parts:
        return False
    if rel.endswith(".pyc"):
        return False
    if fnmatch.fnmatch(rel, "tests/test-output-*.txt"):
        return False
    return True


def _collect_manifest_files_dir(pkg_dir):
    """Walk a package directory. Returns (files, total_bytes) where
    files maps covered relative paths to their SHA-256 hex digests."""
    files = {}
    total = 0
    for dirpath, dirs, names in os.walk(pkg_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, pkg_dir).replace(os.sep, "/")
            if not _manifest_included(rel):
                continue
            files[rel] = sha256_file(full)
            total += os.path.getsize(full)
    return files, total


def build_manifest(pkg_dir):
    """Build the manifest dict for a package directory."""
    files, total = _collect_manifest_files_dir(pkg_dir)
    return {
        "package": "agent-relay-skill",
        "version": MANIFEST_VERSION,
        "file_count": len(files),
        "total_bytes": total,
        "excluded": list(MANIFEST_EXCLUDED_NOTE),
        "files": files,
    }


def manifest_bytes(manifest):
    """Canonical serialisation of a manifest dict (sorted keys,
    2-space indent, trailing newline) — the same bytes every time
    for the same content, so dir and ZIP copies compare equal."""
    return (json.dumps(manifest, sort_keys=True, indent=2,
                       ensure_ascii=False) + "\n").encode("utf-8")


def write_manifest(pkg_dir):
    """(Re)generate MANIFEST.json in a package directory from its
    current contents. Returns the manifest dict."""
    manifest = build_manifest(pkg_dir)
    path = os.path.join(pkg_dir, MANIFEST_REL)
    with open(path, "wb") as f:
        f.write(manifest_bytes(manifest))
    return manifest


def _verify_manifest(manifest, actual_files, actual_total, source):
    """Compare a parsed manifest against actual {rel: sha256} +
    total_bytes. Returns a list of error strings."""
    errors = []
    listed = manifest.get("files")
    if not isinstance(listed, dict):
        return [f"{source}: {MANIFEST_REL} has no 'files' mapping"]
    for rel, expected in sorted(listed.items()):
        if rel not in actual_files:
            errors.append(
                f"{source}: {MANIFEST_REL} lists {rel}, "
                "but it is not present")
        elif actual_files[rel] != expected:
            errors.append(
                f"{source}: {MANIFEST_REL} hash mismatch for {rel}: "
                f"actual {actual_files[rel]}, manifest says {expected}")
    for rel in sorted(actual_files):
        if rel not in listed:
            errors.append(
                f"{source}: {rel} is present but not listed in "
                f"{MANIFEST_REL} — regenerate it "
                "(tests/release_gate.py)")
    if manifest.get("file_count") != len(actual_files):
        errors.append(
            f"{source}: {MANIFEST_REL} file_count is "
            f"{manifest.get('file_count')}, actual {len(actual_files)}")
    if manifest.get("total_bytes") != actual_total:
        errors.append(
            f"{source}: {MANIFEST_REL} total_bytes is "
            f"{manifest.get('total_bytes')}, actual {actual_total}")
    return errors


def check_manifest_dir(pkg_dir):
    """Verify MANIFEST.json against a package directory. Returns a
    list of error strings (empty means PASS)."""
    path = os.path.join(pkg_dir, MANIFEST_REL)
    if not os.path.isfile(path):
        return [f"missing {MANIFEST_REL}: run tests/release_gate.py "
                "to generate it"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return [f"cannot parse {MANIFEST_REL}: {exc}"]
    if not isinstance(manifest, dict):
        return [f"{MANIFEST_REL} is not a JSON object"]
    actual_files, actual_total = _collect_manifest_files_dir(pkg_dir)
    return _verify_manifest(manifest, actual_files, actual_total,
                            "directory")


def check_manifest_zip(zf):
    """Verify MANIFEST.json against a ZIP's contents. `zf` is an open
    zipfile.ZipFile. Returns a list of error strings."""
    names = set(zf.namelist())
    if MANIFEST_REL not in names:
        return [f"missing {MANIFEST_REL} in ZIP: the receiver cannot "
                "verify completeness"]
    try:
        manifest = json.loads(zf.read(MANIFEST_REL).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return [f"cannot parse {MANIFEST_REL} in ZIP: {exc}"]
    if not isinstance(manifest, dict):
        return [f"{MANIFEST_REL} in ZIP is not a JSON object"]
    actual_files = {}
    actual_total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = info.filename
        if not _manifest_included(rel):
            continue
        data = zf.read(rel)
        actual_files[rel] = sha256_bytes(data)
        actual_total += len(data)
    return _verify_manifest(manifest, actual_files, actual_total, "ZIP")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_hash_file(text, source):
    """Parse a '<sha256>  <filename>' checksum file. Returns the hash
    string, or raises ValueError with a clear reason."""
    token = text.strip().split()
    if not token:
        raise ValueError(f"{source}: checksum file is empty")
    candidate = token[0].strip().lower()
    if len(candidate) != 64 or any(
            c not in "0123456789abcdef" for c in candidate):
        raise ValueError(
            f"{source}: first token is not a SHA-256 hex digest: "
            f"{candidate!r}")
    return candidate


def check_dir(pkg_dir):
    """Check the package directory. Returns a list of error strings
    (empty means PASS)."""
    errors = []
    for rel in REQUIRED_FILES:
        path = os.path.join(pkg_dir, rel)
        if not os.path.isfile(path):
            errors.append(f"missing required file: {rel}")
    hash_path = os.path.join(pkg_dir, HASH_REL)
    exe_path = os.path.join(pkg_dir, EXE_REL)
    if os.path.isfile(hash_path) and os.path.isfile(exe_path):
        try:
            with open(hash_path, "r", encoding="utf-8") as f:
                expected = parse_hash_file(f.read(), HASH_REL)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            errors.append(f"cannot read expected EXE hash: {exc}")
            return errors
        actual = sha256_file(exe_path)
        if actual != expected:
            errors.append(
                f"EXE hash mismatch in package dir: "
                f"{EXE_REL} is {actual}, "
                f"{HASH_REL} says {expected}")
    errors.extend(check_manifest_dir(pkg_dir))
    return errors


def check_zip(zip_path, expected_manifest=None):
    """Check the ZIP file. `expected_manifest` (bytes, optional) is
    the MANIFEST.json from the package directory — when given, the
    manifest inside the ZIP must be byte-identical to it, so the
    receiver gets exactly the manifest the directory was checked
    against. Returns a list of error strings (empty means PASS)."""
    errors = []
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"cannot open ZIP {zip_path}: {exc}"]
    with zf:
        names = set(zf.namelist())
        for rel in REQUIRED_FILES:
            if rel not in names:
                errors.append(f"missing required file in ZIP: {rel}")
        if HASH_REL in names and EXE_REL in names:
            try:
                expected = parse_hash_file(
                    zf.read(HASH_REL).decode("utf-8"), HASH_REL)
            except (ValueError, UnicodeDecodeError) as exc:
                errors.append(
                    f"cannot read expected EXE hash from ZIP: {exc}")
                return errors
            actual = sha256_bytes(zf.read(EXE_REL))
            if actual != expected:
                errors.append(
                    f"EXE hash mismatch inside ZIP: "
                    f"{EXE_REL} is {actual}, "
                    f"{HASH_REL} says {expected}")
        errors.extend(check_manifest_zip(zf))
        if expected_manifest is not None and MANIFEST_REL in names:
            actual_manifest = zf.read(MANIFEST_REL)
            if actual_manifest != expected_manifest:
                errors.append(
                    f"{MANIFEST_REL} inside ZIP differs from the "
                    "package directory's manifest — the ZIP was not "
                    "built from the checked directory")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay RC4 pre-delivery package check")
    parser.add_argument("--dir", default=None,
                        help="package directory to check "
                             "(default: the package this script "
                             "lives in)")
    parser.add_argument("--zip", default=None,
                        help="ZIP file to check")
    parser.add_argument("zip_path", nargs="?", default=None,
                        help="ZIP file to check (positional)")
    args = parser.parse_args(argv)

    zip_path = args.zip or args.zip_path
    pkg_dir = args.dir or PKG

    targets = []
    if args.dir is not None or zip_path is None:
        targets.append(("directory", pkg_dir))
    if zip_path is not None:
        targets.append(("ZIP", zip_path))

    all_errors = []
    expected_manifest = None
    for kind, target in targets:
        if kind == "directory":
            errors = check_dir(target)
            if not errors:
                # The directory passed: capture its manifest bytes so
                # the ZIP check can require the same manifest inside
                # the ZIP (the ZIP must be built from this directory).
                manifest_path = os.path.join(target, MANIFEST_REL)
                try:
                    with open(manifest_path, "rb") as f:
                        expected_manifest = f.read()
                except OSError:
                    expected_manifest = None
        else:
            errors = check_zip(target,
                               expected_manifest=expected_manifest)
        if errors:
            print(f"CHECK {kind} {target}: FAIL")
            for err in errors:
                print(f"  - {err}")
            all_errors.extend(errors)
        else:
            print(f"CHECK {kind} {target}: PASS")

    if all_errors:
        print()
        print("PACKAGE CHECK FAILED: "
              f"{len(all_errors)} problem(s) — "
              "do NOT publish this package.")
        return 1
    print()
    print("PACKAGE CHECK PASSED: all required files present, "
          "EXE hash matches, MANIFEST.json matches the package.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
