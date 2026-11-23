#!/usr/bin/env python3
"""Tests for the pre-delivery package check (tests/check_package.py).

Covers: a complete package passes (both the real package directory
and a fake tree), a missing file fails, a missing EXE fails, an EXE
whose hash does not match the checksum file fails, and the same four
cases inside a ZIP. The manifest (MANIFEST.json) is covered too: a
missing manifest fails, a stale manifest fails, an unlisted file
fails, a manifest that does not match the ZIP contents fails — and
volatile test-output files are deliberately excluded from the
manifest, so re-running the suite never invalidates it. The CLI is
also exercised end to end (exit 0 on a good package, non-zero with
a clear FAIL banner on a bad one).
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import check_package

FAKE_EXE = b"fake-exe-bytes-for-testing"
FAKE_EXE_HASH = hashlib.sha256(FAKE_EXE).hexdigest()


def _fake_tree(root, missing=None, exe_bytes=FAKE_EXE,
               hash_bytes=FAKE_EXE):
    """Build a minimal fake package tree containing every required
    file. `missing` removes one file; `exe_bytes` is what the EXE
    file actually contains; `hash_bytes` is what the checksum file
    was computed from — make them differ to simulate a corrupt or
    stripped EXE. A correct MANIFEST.json is generated last, so the
    fake tree passes the manifest check too (unless a test then
    tampers with it)."""
    for rel in check_package.REQUIRED_FILES:
        if rel == missing:
            continue
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if rel == check_package.EXE_REL:
            data = exe_bytes
        elif rel == check_package.HASH_REL:
            data = (hashlib.sha256(hash_bytes).hexdigest()
                    + "  agent-relay-host.exe\n").encode("utf-8")
        elif rel == check_package.MANIFEST_REL:
            data = b"placeholder\n"  # replaced by write_manifest below
        else:
            data = b"placeholder\n"
        with open(path, "wb") as f:
            f.write(data)
    if missing != check_package.MANIFEST_REL:
        check_package.write_manifest(root)


def _zip_tree(root, zip_path):
    """Zip a fake tree with the same relative names as the package.
    The ZIP file itself is never included (these tests create it
    inside the tree directory, and a ZIP must not contain itself —
    that would also trip the manifest's 'not listed' check)."""
    with zipfile.ZipFile(zip_path, "w",
                         compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                full = os.path.join(dirpath, name)
                if os.path.abspath(full) == os.path.abspath(zip_path):
                    continue
                zf.write(full, os.path.relpath(full, root))


class TestCheckPackage(unittest.TestCase):
    def test_real_package_dir_passes(self):
        """The actual RC4 package directory must pass the check —
        this is the gate the corrected delivery is built on."""
        errors = check_package.check_dir(PKG)
        self.assertEqual(errors, [])

    def test_complete_fake_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            self.assertEqual(check_package.check_dir(tmp), [])

    def test_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp, missing="install.py")
            errors = check_package.check_dir(tmp)
            self.assertEqual(len(errors), 1)
            self.assertIn("install.py", errors[0])

    def test_missing_exe_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp, missing=check_package.EXE_REL)
            errors = check_package.check_dir(tmp)
            self.assertTrue(any(check_package.EXE_REL in e
                                for e in errors))

    def test_exe_hash_mismatch_fails(self):
        """EXE content differs from what the checksum file says —
        the corrupt / stripped / replaced EXE case."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp, exe_bytes=b"tampered-exe-bytes")
            errors = check_package.check_dir(tmp)
            self.assertTrue(any("hash mismatch" in e for e in errors))

    def test_zip_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            zip_path = os.path.join(tmp, "pkg.zip")
            _zip_tree(tmp, zip_path)
            self.assertEqual(check_package.check_zip(zip_path), [])

    def test_zip_missing_exe_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp, missing=check_package.EXE_REL)
            zip_path = os.path.join(tmp, "pkg.zip")
            _zip_tree(tmp, zip_path)
            errors = check_package.check_zip(zip_path)
            self.assertTrue(any(check_package.EXE_REL in e
                                for e in errors))

    def test_zip_exe_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp, exe_bytes=b"tampered-exe-bytes")
            zip_path = os.path.join(tmp, "pkg.zip")
            _zip_tree(tmp, zip_path)
            errors = check_package.check_zip(zip_path)
            self.assertTrue(any("hash mismatch" in e for e in errors))

    def test_manifest_missing_fails(self):
        """No MANIFEST.json at all: the receiver cannot verify
        completeness, so the check must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            os.remove(os.path.join(tmp, check_package.MANIFEST_REL))
            errors = check_package.check_dir(tmp)
            self.assertTrue(any(check_package.MANIFEST_REL in e
                                for e in errors))

    def test_manifest_stale_fails(self):
        """A file changed after the manifest was generated: the
        manifest hash no longer matches the file."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            with open(os.path.join(tmp, "install.py"), "wb") as f:
                f.write(b"tampered\n")
            errors = check_package.check_dir(tmp)
            self.assertTrue(any("install.py" in e and
                                "mismatch" in e for e in errors))

    def test_manifest_unlisted_file_fails(self):
        """A file present in the package but not listed in the
        manifest: either the manifest is stale or something was
        added — both must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            with open(os.path.join(tmp, "notes.txt"), "w") as f:
                f.write("not in the manifest\n")
            errors = check_package.check_dir(tmp)
            self.assertTrue(any("notes.txt" in e and
                                "not listed" in e for e in errors))

    def test_manifest_excludes_test_outputs(self):
        """Volatile test-run outputs (tests/test-output-*.txt) are
        deliberately NOT covered by the manifest: unittest prints
        elapsed seconds, so their bytes change on every run, and
        hashing them would make the manifest go stale the moment
        the suite is re-run (including by an independent reviewer).
        Adding one must NOT fail the check."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            path = os.path.join(tmp, "tests", "test-output-rc4.txt")
            with open(path, "w") as f:
                f.write("Ran 139 tests in 32.308s\n")
            self.assertEqual(check_package.check_dir(tmp), [])
            with open(path, "w") as f:
                f.write("Ran 139 tests in 41.777s\n")
            self.assertEqual(check_package.check_dir(tmp), [])

    def test_zip_manifest_mismatch_fails(self):
        """The manifest inside the ZIP does not match the ZIP's
        contents (a file was tampered with after the manifest was
        generated, then zipped)."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            with open(os.path.join(tmp, "install.py"), "wb") as f:
                f.write(b"tampered\n")
            zip_path = os.path.join(tmp, "pkg.zip")
            _zip_tree(tmp, zip_path)
            errors = check_package.check_zip(zip_path)
            self.assertTrue(any("install.py" in e and
                                "mismatch" in e for e in errors))

    def test_zip_manifest_missing_fails(self):
        """ZIP without MANIFEST.json: the receiver cannot verify
        completeness."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp, missing=check_package.MANIFEST_REL)
            zip_path = os.path.join(tmp, "pkg.zip")
            _zip_tree(tmp, zip_path)
            errors = check_package.check_zip(zip_path)
            self.assertTrue(any(check_package.MANIFEST_REL in e
                                for e in errors))

    def test_cli_passes_on_real_package(self):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(HERE, "check_package.py"), "--dir", PKG],
            capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PACKAGE CHECK PASSED", proc.stdout)

    def test_cli_fails_loudly_on_incomplete_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp, missing="install.py")
            proc = subprocess.run(
                [sys.executable,
                 os.path.join(HERE, "check_package.py"),
                 "--dir", tmp],
                env=dict(os.environ, PYTHONIOENCODING="cp1252"),
                capture_output=True, encoding="utf-8", timeout=30)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("PACKAGE CHECK FAILED", proc.stdout)
            self.assertIn("install.py", proc.stdout)

    def test_cli_zip_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp)
            zip_path = os.path.join(tmp, "pkg.zip")
            _zip_tree(tmp, zip_path)
            proc = subprocess.run(
                [sys.executable,
                 os.path.join(HERE, "check_package.py"), zip_path],
                capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("PACKAGE CHECK PASSED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
