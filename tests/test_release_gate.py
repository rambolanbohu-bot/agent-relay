#!/usr/bin/env python3
"""Tests for the mandatory release gate (tests/release_gate.py).

Covers: a good package passes the gate end to end (test suite,
manifest generated, directory check, ZIP built in an isolated temp
dir, ZIP check, atomic publish, .sha256 written with the right
hash, MANIFEST.json inside the ZIP matching the directory); a
package missing the EXE is refused with a non-zero exit and
produces NO .sha256 and NO publishable ZIP; a package whose EXE
does not match its checksum is refused the same way; a failed run
removes a stale pre-existing .sha256 AND a stale pre-existing
target ZIP (HOTFIX 3); a failing test suite refuses the release
with no ZIP/.sha256 (HOTFIX 3 — the suite is a mandatory gate
condition); the gate's ZIP is verified complete (required files +
manifest) by check_package.py. The gate is exercised both as an
imported main() and via the CLI.
"""

import hashlib
import os
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
import release_gate
import test_check_package


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TestReleaseGate(unittest.TestCase):
    def _plant_stub_runner(self, tree, exit_code=0):
        """Plant a stub tests/run_tests.py in the fake tree. The
        gate resolves the runner relative to the target package
        dir, and _fake_tree() does not create it (it is not a
        required file). A stub is a legitimate test double for the
        gate's control flow — it only answers "did the suite
        pass?"; the real runner's correctness is covered by the
        actual full-suite run during verification."""
        runner = os.path.join(tree, "tests", "run_tests.py")
        os.makedirs(os.path.dirname(runner), exist_ok=True)
        with open(runner, "w", encoding="utf-8") as f:
            f.write("import sys\n")
            f.write(f"sys.exit({exit_code})\n")

    def _gate(self, tree, tmp, runner_exit=0):
        self._plant_stub_runner(tree, runner_exit)
        zip_path = os.path.join(tmp, "release.zip")
        sha_path = zip_path + ".sha256"
        code = release_gate.main([
            "--package-dir", tree,
            "--zip", zip_path,
            "--sha256", sha_path,
        ])
        return code, zip_path, sha_path

    def test_gate_passes_and_writes_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(tree)
            code, zip_path, sha_path = self._gate(tree, tmp)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(zip_path))
            self.assertTrue(os.path.isfile(sha_path))
            with open(sha_path, "r", encoding="utf-8") as f:
                recorded = f.read().strip().split()
            self.assertEqual(recorded[0], _sha256_file(zip_path))
            self.assertEqual(recorded[1], "release.zip")
            with open(os.path.join(tree, check_package.MANIFEST_REL),
                      "rb") as f:
                dir_manifest = f.read()
            # The ZIP is verified complete by check_package itself.
            self.assertEqual(
                check_package.check_zip(
                    zip_path, expected_manifest=dir_manifest),
                [])
            # MANIFEST.json is inside the ZIP and matches the dir.
            with zipfile.ZipFile(zip_path, "r") as zf:
                self.assertIn(check_package.MANIFEST_REL, zf.namelist())
                self.assertIn(check_package.EXE_REL, zf.namelist())
                self.assertEqual(
                    zf.read(check_package.MANIFEST_REL), dir_manifest)

    def test_gate_writes_manifest_into_package_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(tree)
            os.remove(os.path.join(tree, check_package.MANIFEST_REL))
            code, _zip, _sha = self._gate(tree, tmp)
            self.assertEqual(code, 0)
            self.assertEqual(check_package.check_dir(tree), [])

    def test_gate_refuses_missing_exe(self):
        """The transit-strip case: the EXE is gone. The gate must
        refuse with a non-zero exit and produce NO .sha256 and NO
        publishable ZIP."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(
                tree, missing=check_package.EXE_REL)
            code, zip_path, sha_path = self._gate(tree, tmp)
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(sha_path))
            self.assertFalse(os.path.exists(zip_path))

    def test_gate_refuses_exe_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(
                tree, exe_bytes=b"tampered-exe-bytes")
            code, zip_path, sha_path = self._gate(tree, tmp)
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(sha_path))
            self.assertFalse(os.path.exists(zip_path))

    def test_gate_removes_stale_sha256_on_failure(self):
        """A pre-existing .sha256 must not survive a failed run —
        otherwise a stale hash could be published beside a new ZIP."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(
                tree, missing=check_package.EXE_REL)
            zip_path = os.path.join(tmp, "release.zip")
            sha_path = zip_path + ".sha256"
            with open(sha_path, "w") as f:
                f.write("0" * 64 + "  release.zip\n")
            self._plant_stub_runner(tree)
            code = release_gate.main([
                "--package-dir", tree,
                "--zip", zip_path,
                "--sha256", sha_path,
            ])
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(sha_path))

    def test_gate_removes_preexisting_zip_on_failure(self):
        """HOTFIX 3 (ChatGPT's reproduction): a failed release must
        leave NO stale ZIP at the target path. The hotfix2 gate
        removed only the stale .sha256; when the run aborted before
        building, the ZIP from an earlier successful run stayed and
        looked publishable. Plant an old ZIP + old .sha256, fail
        the package (EXE removed), and assert both are gone."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(
                tree, missing=check_package.EXE_REL)
            zip_path = os.path.join(tmp, "release.zip")
            sha_path = zip_path + ".sha256"
            with open(zip_path, "wb") as f:
                f.write(b"old-zip-from-an-earlier-successful-run")
            with open(sha_path, "w") as f:
                f.write("0" * 64 + "  release.zip\n")
            code, _, _ = self._gate(tree, tmp)
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(zip_path))
            self.assertFalse(os.path.exists(sha_path))

    def test_gate_refuses_failing_test_suite(self):
        """HOTFIX 3: the automated test suite is a mandatory gate
        condition. A package that is otherwise complete must still
        be refused — with no ZIP and no .sha256 published — when
        the suite fails."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(tree)
            code, zip_path, sha_path = self._gate(
                tree, tmp, runner_exit=1)
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(zip_path))
            self.assertFalse(os.path.exists(sha_path))

    def test_gate_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "pkg")
            os.makedirs(tree)
            test_check_package._fake_tree(tree)
            self._plant_stub_runner(tree)
            zip_path = os.path.join(tmp, "release.zip")
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(HERE, "release_gate.py"),
                 "--package-dir", tree, "--zip", zip_path],
                capture_output=True, encoding="utf-8", timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("RELEASE GATE PASSED", proc.stdout)
            self.assertTrue(os.path.isfile(zip_path + ".sha256"))


if __name__ == "__main__":
    unittest.main()
