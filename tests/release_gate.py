#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — MANDATORY release gate.

Why this exists: the EXE was stripped in transit TWICE — first with
the RC4 ZIP (ChatGPT received a file with hash 02dcf688... vs Dash's
published 5beff152..., missing transport/agent-relay-host.exe), then
again with the RC4-hotfix ZIP (ChatGPT received 85 entries, no EXE;
Dash's delivered ZIP has 86 entries with the EXE, SHA-256
4129a0e0...). The packaging itself was NOT broken at build time
either time; something in the download / re-upload path strips the
EXE. A plain "check the files" step that a human may skip is not
enough — the release procedure MUST run this gate, and no ZIP is
delivered unless it passes.

RC4-HOTFIX3 (ChatGPT review of the RC4 hotfix2, rounds 10-11,
2026-11-20): the hotfix2 gate had two gaps, both reproduced by
ChatGPT on the real code:
  (a) A failed release could leave a stale old ZIP. The hotfix2
      gate removed only the pre-existing .sha256, never the target
      ZIP, so if the run aborted before building (e.g. the directory
      check failed because the EXE was missing), the ZIP from an
      earlier successful run stayed at the target path and looked
      publishable.
  (b) The automated test suite was not a mandatory gate condition
      — the gate only ran check_package.py, never the tests.
ChatGPT's required approach (rounds 10-11): build in an ISOLATED
TEMP DIRECTORY and publish atomically only after ALL checks pass,
so a failed run can never leave a stale artifact at the target
path, and fold the automated regression tests into the mandatory
release checks.

The gate, in order:
  1. Remove any pre-existing .sha256 AND any pre-existing target
     ZIP, so a failed run can never leave a stale hash or a stale
     ZIP beside a new deliverable.
  2. Run the automated test suite (tests/run_tests.py --batch 1, 2,
     3 in sequence) and abort on any failure. The runner is
     resolved relative to the target --package-dir, NOT relative to
     this script's own directory (resolving to this script's
     directory would recurse infinitely, since the real suite
     contains test_release_gate, whose tests invoke
     release_gate.main()). Tests run BEFORE the manifest is
     generated because run_tests.py rewrites the test-output-*.txt
     files inside the package dir — generating the manifest first
     would leave it stale.
  3. (Re)generate MANIFEST.json in the package directory from its
     current contents (every covered file + its SHA-256; see
     tests/check_package.py for what the manifest covers and what
     it deliberately excludes).
  4. Run tests/check_package.py --dir <package-dir> — required
     files, EXE hash, and manifest-vs-directory must all pass.
  5. Build the ZIP in an ISOLATED TEMP DIRECTORY (not at the
     target path).
  6. Run tests/check_package.py --dir <package-dir> --zip
     <temp-zip> — the ZIP must contain the same files with the same
     hashes and the same MANIFEST.json.
  7. Only then ATOMICALLY publish: move the temp ZIP to the target
     path (os.replace) and write the .sha256 file (sha256 of the
     ZIP, same "<hash>  <basename>" format as before), verified by
     re-reading.

Any step failing ABORTS with a non-zero exit: no .sha256 is
written, no ZIP is published at the target path, and the temp
directory is cleaned up, so there is no publishable artifact from
a failed run. The gate never publishes anything on its own — it
only produces a verified ZIP + .sha256 for a human to upload.

Usage (stdlib only, no dependencies):
    python3 tests/release_gate.py \
        --package-dir agent-relay-skill \
        --zip agent-relay-skill-v1.0.0-rc4-hotfix5.zip \
        --sha256 agent-relay-skill-v1.0.0-rc4-hotfix5.zip.sha256

Exit code: 0 only when every step passes.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
CHECK_PACKAGE = os.path.join(HERE, "check_package.py")
TEST_TIMEOUT_S = 300


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_zip(pkg_dir, zip_path):
    """Build the ZIP from a package directory. Sorted entries,
    ZIP_DEFLATED, no __pycache__ dirs, no .pyc files. Every other
    file in the directory is included (including MANIFEST.json and
    the test-output run artifacts)."""
    entries = []
    for dirpath, dirs, names in os.walk(pkg_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, pkg_dir).replace(os.sep, "/")
            entries.append((full, rel))
    entries.sort(key=lambda item: item[1])
    with zipfile.ZipFile(zip_path, "w",
                         compression=zipfile.ZIP_DEFLATED) as zf:
        for full, rel in entries:
            zf.write(full, rel)
    return [rel for _full, rel in entries]


def _run_check_package(pkg_dir, zip_path=None):
    """Run tests/check_package.py as a subprocess. Returns
    (returncode, combined output)."""
    cmd = [sys.executable, "-X", "utf8", CHECK_PACKAGE, "--dir", pkg_dir]
    if zip_path is not None:
        cmd += ["--zip", zip_path]
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                          timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def _run_test_suite(pkg_dir):
    """Run the automated test suite (tests/run_tests.py --batch 1,
    2, 3) against the target package directory. The runner is
    resolved relative to the target package dir, NOT relative to
    this script's own directory — otherwise the real suite's
    test_release_gate tests would invoke this gate again on the
    same tree and recurse. Returns (returncode, combined output)
    of the first failing batch, or (0, output) when all pass."""
    runner = os.path.join(pkg_dir, "tests", "run_tests.py")
    if not os.path.isfile(runner):
        return 1, (f"test runner not found: {runner}\n"
                   "The package must contain tests/run_tests.py.")
    combined = ""
    for batch in ("1", "2", "3"):
        try:
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", runner, "--batch", batch],
                capture_output=True, encoding="utf-8",
                timeout=TEST_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return 1, (combined +
                       f"batch {batch}: TIMEOUT after "
                       f"{TEST_TIMEOUT_S}s\n")
        combined += proc.stdout + proc.stderr
        if proc.returncode != 0:
            return proc.returncode, combined
    return 0, combined


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay RC4 mandatory release gate")
    parser.add_argument("--package-dir", default=PKG,
                        help="package directory to release "
                             "(default: the package this script "
                             "lives in)")
    parser.add_argument("--zip", required=True,
                        help="ZIP file to build and verify")
    parser.add_argument("--sha256", default=None,
                        help=".sha256 file to write on success "
                             "(default: <zip>.sha256)")
    args = parser.parse_args(argv)

    pkg_dir = os.path.abspath(args.package_dir)
    zip_path = os.path.abspath(args.zip)
    sha_path = (os.path.abspath(args.sha256)
                if args.sha256 else zip_path + ".sha256")
    # Isolated temp dir for the build, created in the target's
    # parent directory so the final publish (os.replace) stays on
    # the same filesystem and is atomic.
    target_dir = os.path.dirname(zip_path) or os.getcwd()
    tmp_dir = tempfile.mkdtemp(prefix=".release-gate-",
                               dir=target_dir)
    temp_zip = os.path.join(tmp_dir, os.path.basename(zip_path))

    def abort(step, detail):
        print()
        print(f"RELEASE GATE FAILED at step {step}: {detail}")
        print("No .sha256 was written. No ZIP was published.")
        print("Do NOT publish this package.")
        return 1

    try:
        print("RELEASE GATE — Agent Relay Skill v1.0.0-rc4")
        print(f"  package dir: {pkg_dir}")
        print(f"  ZIP:         {zip_path}")
        print(f"  .sha256:     {sha_path}")
        print()

        # Step 1: remove any pre-existing .sha256 AND any
        # pre-existing target ZIP, so a failed run can never leave
        # a stale hash or a stale ZIP looking publishable.
        if os.path.exists(sha_path):
            print("[1/7] Removing pre-existing .sha256 "
                  "(a failed run must leave none behind)...")
            os.remove(sha_path)
        else:
            print("[1/7] No pre-existing .sha256 to remove.")
        if os.path.exists(zip_path):
            print("      Removing pre-existing target ZIP "
                  "(a failed run must leave none behind)...")
            os.remove(zip_path)
        else:
            print("      No pre-existing target ZIP to remove.")

        # Step 2: run the automated test suite BEFORE the manifest
        # is generated (the suite rewrites test-output-*.txt inside
        # the package dir). Any failure aborts the release.
        print("[2/7] Running automated test suite "
              "(run_tests.py --batch 1, 2, 3)...")
        code, out = _run_test_suite(pkg_dir)
        print(out, end="")
        if code != 0:
            return abort(2, "automated test suite failed")

        # Step 3: (re)generate MANIFEST.json from the directory.
        print("[3/7] Generating MANIFEST.json from the package dir...")
        sys.path.insert(0, HERE)
        try:
            import check_package
        except ImportError as exc:
            return abort(3, f"cannot import check_package: {exc}")
        try:
            manifest = check_package.write_manifest(pkg_dir)
        except OSError as exc:
            return abort(3, f"cannot write MANIFEST.json: {exc}")
        print(f"      MANIFEST.json: {manifest['file_count']} files, "
              f"{manifest['total_bytes']} bytes.")

        # Step 4: check_package.py on the directory.
        print("[4/7] Running check_package.py --dir ...")
        code, out = _run_check_package(pkg_dir)
        print(out, end="")
        if code != 0:
            return abort(4, "check_package.py failed on the directory")

        # Step 5: build the ZIP in the ISOLATED TEMP DIRECTORY,
        # never at the target path.
        print("[5/7] Building ZIP in isolated temp dir...")
        try:
            entries = build_zip(pkg_dir, temp_zip)
        except OSError as exc:
            return abort(5, f"cannot build ZIP: {exc}")
        print(f"      ZIP built: {len(entries)} entries.")

        # Step 6: check_package.py on the directory AND the temp ZIP.
        print("[6/7] Running check_package.py --dir --zip ...")
        code, out = _run_check_package(pkg_dir, temp_zip)
        print(out, end="")
        if code != 0:
            return abort(6, "check_package.py failed on the ZIP")

        # Step 7: ATOMICALLY publish — move the temp ZIP to the
        # target path, then write the .sha256 file and verify it by
        # re-reading. Nothing is publishable before this step.
        print("[7/7] Publishing atomically (temp ZIP -> target, "
              "writing .sha256)...")
        try:
            os.replace(temp_zip, zip_path)
        except OSError as exc:
            return abort(7, f"cannot publish ZIP: {exc}")
        digest = sha256_file(zip_path)
        try:
            with open(sha_path, "w", encoding="utf-8") as f:
                f.write(f"{digest}  {os.path.basename(zip_path)}\n")
            with open(sha_path, "r", encoding="utf-8") as f:
                recorded = f.read().strip().split()[0]
        except (OSError, IndexError) as exc:
            # The ZIP is already published; remove it again so a
            # failed run leaves no publishable artifact behind.
            try:
                os.remove(zip_path)
            except OSError:
                pass
            return abort(7, f"cannot write or verify .sha256: {exc}")
        if recorded != digest:
            try:
                os.remove(zip_path)
            except OSError:
                pass
            return abort(7, ".sha256 content does not match the ZIP hash")
        print(f"      SHA-256: {digest}")
        print()
        print("RELEASE GATE PASSED: ZIP + .sha256 are verified and "
              "publishable.")
        return 0
    finally:
        # Always clean up the temp dir: on failure it holds an
        # unpublished ZIP; on success it is empty after the move.
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
