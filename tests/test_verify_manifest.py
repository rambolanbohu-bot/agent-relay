#!/usr/bin/env python3
"""RC4-hotfix4 tests for windows_e2e_test/verify_manifest.py,
windows_e2e_test/resolve_long_path.py, and the P1 BAT changes
(HOTFIX 4, P1; ChatGPT ROUND 22 corrections).

verify_manifest.py replaces the BAT's findstr checks. findstr
conflates "string not found" (exit 1) and "file/path error"
(exit 2), and the BAT had no existence check — so a path/read
failure was misreported as a content error (ATTEMPT-05/06).
The checker parses the JSON, verifies name / path / type /
allowed_origins, verifies the file is accessible via BOTH the
long and the short path AND the as-given path, and records
findstr's original exit code + stderr for diagnosis (the verdict
does not depend on findstr).

resolve_long_path.py resolves a path to its long form via
GetLongPathNameW (Windows) so the BAT never works through a
short-form path such as HIHOME~1. %~f only converts to an
absolute path — it does NOT guarantee the short name is
expanded.

Exit codes: 0 = manifest valid; 1 = content mismatch;
2 = file/parse error. These tests run on Linux (no Windows
here): findstr is recorded as unavailable, and the long/short
path checks fall back to realpath. The Windows-specific path
expansion (GetLongPathNameW) is verified by code inspection
and by the ATTEMPT-08 real-machine run, not here.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
VERIFY = os.path.join(PKG, "windows_e2e_test", "verify_manifest.py")
RESOLVE = os.path.join(PKG, "windows_e2e_test", "resolve_long_path.py")
BAT = os.path.join(PKG, "windows_e2e_test", "run_e2e_test.bat")
RUNNER = os.path.join(PKG, "windows_e2e_test", "e2e_runner.py")
EXT_ID = "jeelmedmciafjnfdpnjgbgipplcddhka"
HOST_NAME = "com.agentrelay.host.e2e"


def write_manifest(directory, **overrides):
    manifest = {
        "name": HOST_NAME,
        "description": "Agent Relay native messaging host (test)",
        "path": os.path.join(directory, "agent-relay-host.exe"),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXT_ID}/"],
    }
    manifest.update(overrides)
    path = os.path.join(directory, "com.agentrelay.host.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    return path, manifest


def run_verify(manifest_path, exe_path):
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", VERIFY,
         "--manifest", manifest_path,
         "--host-name", HOST_NAME,
         "--extension-id", EXT_ID,
         "--exe-path", exe_path],
        capture_output=True, encoding="utf-8", timeout=30)
    return proc


class TestVerifyManifest(unittest.TestCase):
    def test_valid_manifest_passes(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "agent-relay-host.exe")
            open(exe, "w").close()
            manifest_path, _ = write_manifest(d)
            proc = run_verify(manifest_path, exe)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["errors"], [])
            self.assertTrue(result["accessible_given"])
            self.assertTrue(result["accessible_long"])
            self.assertTrue(result["accessible_short"])
            self.assertEqual(result["manifest"]["name"], HOST_NAME)
            # findstr is not available on Linux; it is recorded,
            # not fatal.
            if os.name == "nt":
                self.assertIsInstance(result["findstr_exit"], int)
            else:
                self.assertEqual(result["findstr_stderr"],
                                 "findstr_not_available")
                self.assertIsNone(result["findstr_exit"])

    def test_wrong_name_is_content_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "agent-relay-host.exe")
            open(exe, "w").close()
            manifest_path, _ = write_manifest(d, name="com.other.host")
            proc = run_verify(manifest_path, exe)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            result = json.loads(proc.stdout)
            self.assertTrue(any("name mismatch" in e
                                for e in result["errors"]))

    def test_wrong_allowed_origins_is_content_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "agent-relay-host.exe")
            open(exe, "w").close()
            manifest_path, _ = write_manifest(
                d, allowed_origins=["chrome-extension://wrong/"])
            proc = run_verify(manifest_path, exe)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            result = json.loads(proc.stdout)
            self.assertTrue(any("allowed_origins mismatch" in e
                                for e in result["errors"]))

    def test_wrong_path_is_content_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "agent-relay-host.exe")
            open(exe, "w").close()
            manifest_path, _ = write_manifest(
                d, path="/somewhere/else/agent-relay-host.exe")
            proc = run_verify(manifest_path, exe)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            result = json.loads(proc.stdout)
            self.assertTrue(any("path mismatch" in e
                                for e in result["errors"]))

    def test_missing_manifest_is_file_error(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "agent-relay-host.exe")
            proc = run_verify(os.path.join(d, "no-such.json"), exe)
            self.assertEqual(proc.returncode, 2, proc.stdout)
            result = json.loads(proc.stdout)
            self.assertTrue(any("not found" in e
                                for e in result["errors"]))

    def test_invalid_json_is_file_error(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "agent-relay-host.exe")
            manifest_path = os.path.join(d, "com.agentrelay.host.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write("{not valid json")
            proc = run_verify(manifest_path, exe)
            self.assertEqual(proc.returncode, 2, proc.stdout)
            result = json.loads(proc.stdout)
            self.assertTrue(any("invalid JSON" in e
                                for e in result["errors"]))

    def test_long_and_short_paths_reported(self):
        # On Linux long == short == given; the point is that the
        # result reports all three accessibility checks.
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "agent-relay-host.exe")
            open(exe, "w").close()
            manifest_path, _ = write_manifest(d)
            proc = run_verify(manifest_path, exe)
            result = json.loads(proc.stdout)
            self.assertEqual(result["manifest_given"], manifest_path)
            self.assertTrue(os.path.samefile(result["manifest_long"],
                                             manifest_path))
            self.assertIn("manifest_short", result)


class TestResolveLongPath(unittest.TestCase):
    def test_existing_dir_resolves_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", RESOLVE, d],
                capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.samefile(proc.stdout.strip(), d))

    def test_missing_path_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", RESOLVE, "/definitely/not/here-xyz"],
            capture_output=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not exist", proc.stderr)


class TestRunnerP1Wiring(unittest.TestCase):
    """Static checks on windows_e2e_test/e2e_runner.py (no Windows
    here): the P1 verification must use Python JSON parsing (not
    findstr), must resolve %TEMP% to its long form before building
    the isolated dir, and must log the manifest stage exit code
    distinctly. (Hotfix6: the thin BAT only delegates to the
    runner; the P1 wiring lives in the runner now.)"""

    def setUp(self):
        with open(RUNNER, "r", encoding="utf-8") as f:
            self.runner = f.read()

    def test_runner_verifies_manifest_with_python_not_findstr(self):
        self.assertIn("verify_manifest.py", self.runner)
        # The old findstr manifest checks must be gone (findstr may
        # still be mentioned in comments explaining why it was
        # replaced, but no findstr command may verify the manifest).
        for line in self.runner.splitlines():
            stripped = line.strip()
            if stripped.startswith("findstr"):
                self.fail("runner still runs findstr to verify the "
                          "manifest: %r" % line)

    def test_runner_resolves_temp_to_long_form_before_base(self):
        # The resolution call must happen before BASE (the isolated
        # dir) is built from %TEMP%.
        self.assertIn("long_path(self.temp_root)", self.runner)
        resolve_pos = self.runner.index("long_path(self.temp_root)")
        base_pos = self.runner.index("base_dir = os.path.join(temp_long,")
        self.assertLess(resolve_pos, base_pos,
                        "TEMP must be resolved to long form before "
                        "BASE is set from it")

    def test_runner_distinguishes_manifest_exit_codes(self):
        # Exit 1 = content mismatch (runner exit 16), exit 2 =
        # file/parse error (runner exit 17): distinct codes, not one
        # generic "manifest wrong".
        self.assertIn("EXIT_MANIFEST_CONTENT", self.runner)
        self.assertIn("EXIT_MANIFEST_FILE", self.runner)
        self.assertIn("EXIT_MANIFEST_UNKNOWN", self.runner)
        self.assertIn("manifest content mismatch", self.runner.lower())
        self.assertIn("manifest file/parse error", self.runner.lower())

    def test_runner_logs_manifest_stage_exit_code(self):
        self.assertIn("Manifest stage exit code", self.runner)


if __name__ == "__main__":
    unittest.main()
