#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4-hotfix — Windows E2E test tests.

RC4-hotfix FIX 3: the E2E test must load a TEST extension build
(HOST_NAME = com.agentrelay.host.e2e) and verify install/uninstall
by invoking the real install.py / uninstall.py — never by copying
files and writing the registry directly.

These tests run on Linux (no Windows, no Chrome here). They verify
the parts that CAN be verified without Windows:
  - make_test_extension.py: the replacement, the verifications, and
    the failure modes (including cleanup on failure);
  - windows_e2e_test/e2e_runner.py: it invokes install.py /
    uninstall.py / make_test_extension.py, loads the TEST extension
    (not the production one), and does NOT copy the package by hand
    or write the host registry entry directly. (Hotfix6: the thin
    run_e2e_test.bat only delegates to the runner; its own safety
    rules live in tests/test_bat_cmd_safety.py and the stage
    machine's invariants in tests/test_e2e_runner.py.)

The real Windows run stays PENDING until it runs on Leo's Windows PC.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, "windows_e2e_test"))

from make_test_extension import (  # noqa: E402
    DEFAULT_TEST_HOST_NAME, TestExtensionError, make_test_extension)

EXTENSION_DIR = os.path.join(PKG, "transport", "extension")
BAT = os.path.join(PKG, "windows_e2e_test", "run_e2e_test.bat")
RUNNER = os.path.join(PKG, "windows_e2e_test", "e2e_runner.py")
EXT_ID = "jeelmedmciafjnfdpnjgbgipplcddhka"


class TestMakeTestExtension(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "extension")
        shutil.copytree(EXTENSION_DIR, self.source)
        self.dest = os.path.join(self.tmp.name, "test-extension")

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path(self):
        report = make_test_extension(self.source, self.dest)
        self.assertEqual(report["host_name"], DEFAULT_TEST_HOST_NAME)
        self.assertEqual(report["extension_id"], EXT_ID)
        self.assertTrue(report["manifest_unchanged"])
        self.assertTrue(report["extension_id_unchanged"])
        self.assertEqual(report["allowed_origin"],
                         f"chrome-extension://{EXT_ID}/")
        with open(os.path.join(self.dest, "background.js"),
                  "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            f'var HOST_NAME = "{DEFAULT_TEST_HOST_NAME}";', content)
        self.assertNotIn('var HOST_NAME = "com.agentrelay.host";',
                         content)
        # manifest.json byte-identical to the source (extension ID
        # unchanged, so allowed_origins still matches).
        with open(os.path.join(self.source, "manifest.json"),
                  "rb") as f:
            src_manifest = f.read()
        with open(os.path.join(self.dest, "manifest.json"),
                  "rb") as f:
            dst_manifest = f.read()
        self.assertEqual(src_manifest, dst_manifest)
        # The rest of the extension is an exact copy.
        for name in ("content.js", "EXTENSION_ID.txt"):
            with open(os.path.join(self.source, name), "rb") as f:
                src = f.read()
            with open(os.path.join(self.dest, name), "rb") as f:
                dst = f.read()
            self.assertEqual(src, dst, name)

    def test_run_bound_beacon_is_only_in_test_copy(self):
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp:
            dest = os.path.join(temp, "test-extension")
            source = os.path.join(PKG, "transport", "extension")
            make_test_extension(source, dest, run_id="test-run")
            before = (Path(source) / "background.js").read_text(encoding="utf-8")
            after = (Path(dest) / "background.js").read_text(encoding="utf-8")
            self.assertNotIn("e2e_browser_ready", before)
            self.assertIn('type:"e2e_browser_ready", run_id:"test-run"', after)
            self.assertIn("extension_id:chrome.runtime.id", after)
            self.assertNotIn("e2e_readonly_stage", before)
            self.assertIn('e2eTrace("background_received", msg)', after)
            self.assertIn('e2eTrace("tab_dispatch", msg)', after)
            self.assertIn('e2eTrace("return_post_accepted", obj)', after)
            self.assertIn("probe_nonce: msg.nonce", after)
            self.assertEqual((Path(source) / "manifest.json").read_bytes(),
                             (Path(dest) / "manifest.json").read_bytes())

    def test_production_host_name_refused(self):
        with self.assertRaises(TestExtensionError):
            make_test_extension(self.source, self.dest,
                                host_name="com.agentrelay.host")
        self.assertFalse(os.path.exists(self.dest))

    def test_unrelated_host_name_refused(self):
        for bad in ("com.example.host", "evil",
                    "com.agentrelay.hostx"):
            with self.assertRaises(TestExtensionError, msg=bad):
                make_test_extension(self.source, self.dest,
                                    host_name=bad)
            self.assertFalse(os.path.exists(self.dest),
                             f"failed build left a dest dir: {bad}")

    def test_missing_host_name_declaration_fails_and_cleans_up(self):
        background = os.path.join(self.source, "background.js")
        with open(background, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(
            'var HOST_NAME = "com.agentrelay.host";',
            'var HOST_NAME = "com.agentrelay.host"; // moved\n'
            'var HOST_NAME = "com.agentrelay.host";')
        with open(background, "w", encoding="utf-8") as f:
            f.write(content)
        with self.assertRaises(TestExtensionError):
            make_test_extension(self.source, self.dest)
        # Nothing half-built is left behind.
        self.assertFalse(os.path.exists(self.dest))

    def test_missing_source_refused(self):
        with self.assertRaises(TestExtensionError):
            make_test_extension(os.path.join(self.tmp.name, "nope"),
                                self.dest)
        self.assertFalse(os.path.exists(self.dest))

    def test_dest_rebuilt_on_repeat(self):
        make_test_extension(self.source, self.dest)
        # Running again over an existing dest rebuilds it cleanly.
        report = make_test_extension(self.source, self.dest)
        self.assertEqual(report["host_name"], DEFAULT_TEST_HOST_NAME)
        with open(os.path.join(self.dest, "background.js"),
                  "r", encoding="utf-8") as f:
            self.assertIn(
                f'var HOST_NAME = "{DEFAULT_TEST_HOST_NAME}";', f.read())


class TestE2ERunnerWiring(unittest.TestCase):
    """Static checks on windows_e2e_test/e2e_runner.py (no Windows
    here): the runner must drive the real install.py / uninstall.py /
    make_test_extension.py, load the TEST extension, and must NOT
    copy the package by hand or write the host registry entry
    directly. The thin BAT only delegates to the runner (see
    tests/test_bat_cmd_safety.py)."""

    def setUp(self):
        with open(RUNNER, "r", encoding="utf-8") as f:
            self.runner = f.read()
        with open(BAT, "r", encoding="utf-8") as f:
            self.bat = f.read()

    def test_runner_runs_real_install(self):
        self.assertIn("install.py", self.runner)
        self.assertIn("com.agentrelay.host.e2e", self.runner)
        self.assertIn("--non-interactive", self.runner)

    def test_runner_runs_real_uninstall(self):
        self.assertIn("uninstall.py", self.runner)

    def test_runner_builds_test_extension(self):
        self.assertIn("make_test_extension.py", self.runner)
        self.assertIn("--dest", self.runner)

    def test_runner_loads_test_extension_not_production(self):
        self.assertIn("--load-extension", self.runner)
        # The Chrome launch must point at the test extension dir,
        # never at the production transport\extension dir.
        for line in self.runner.splitlines():
            if "--load-extension" in line:
                self.assertIn("test_ext_dir", line)
                self.assertNotIn("transport", line)

    def test_runner_does_not_copy_package_or_write_registry_directly(self):
        # FIX 3: no hand-rolled copy of the package (install.py does
        # the copy) and no direct registry write for the host.
        self.assertNotIn("robocopy", self.runner.lower())
        self.assertNotIn("reg add", self.runner.lower())
        # Registry reads (reg query) for verification are fine.
        self.assertIn("reg_query", self.runner)

    def test_runner_verifies_production_key_unchanged(self):
        self.assertIn("prod-reg-before", self.runner)
        self.assertIn("prod-reg-after-install", self.runner)
        self.assertIn("prod-reg-after-uninstall", self.runner)

    def test_thin_bat_delegates_to_the_runner(self):
        self.assertIn("e2e_runner.py", self.bat)


if __name__ == "__main__":
    unittest.main()
