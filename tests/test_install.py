#!/usr/bin/env python3
"""RC3 tests for install.py / uninstall.py (installer safety).

Uses FakeRegistry (dict-backed) so no real registry is touched, and
throwaway copies of the package as the install source:
- happy path: copy, real host manifest (real extension ID + .exe path),
  registry entry, PIN file (hash only), install manifest;
- refuse when the destination already exists;
- refuse when the registry entry points elsewhere (non-interactive,
  and interactive + user says no); proceed + record the prior value
  when the user confirms;
- refuse when agent-relay-host.exe is missing (never fall back to
  .bat / .py);
- rollback on failure (registry set raises -> destination is gone,
  prior registry value restored);
- uninstall removes only manifest-listed paths, deletes the registry
  entry only if it still points at our manifest, restores a prior
  value, refuses without a manifest, refuses a non-skill target,
  backs up state with --keep-state and refuses on backup failure.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

sys.path.insert(0, PKG)
sys.path.insert(0, os.path.join(PKG, "approvals"))
from install import (FakeRegistry, InstallError, Installer,  # noqa: E402
                     REG_KEY)
from uninstall import uninstall  # noqa: E402


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "agent-relay-skill")
        shutil.copytree(PKG, self.source)
        self.dest = os.path.join(self.tmp.name, "installed",
                                 "agent-relay-skill")
        self.registry = FakeRegistry()

    def tearDown(self):
        self.tmp.cleanup()

    def _installer(self, **kw):
        return Installer(self.source, self.dest, self.registry, **kw)

    def test_happy_path(self):
        record, pin = self._installer().install()
        self.assertEqual(len(pin), 6)
        self.assertTrue(pin.isdigit())
        # Destination copied.
        self.assertTrue(os.path.exists(
            os.path.join(self.dest, "SKILL.md")))
        # Host manifest: real extension ID + real .exe path.
        manifest_path = os.path.join(
            self.dest, "transport", "extension",
            "com.agentrelay.host.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["name"], "com.agentrelay.host")
        self.assertEqual(manifest["type"], "stdio")
        self.assertTrue(manifest["path"].endswith("agent-relay-host.exe"),
                        manifest["path"])
        self.assertNotIn(".bat", manifest["path"])
        self.assertNotIn(".py", manifest["path"])
        self.assertEqual(manifest["allowed_origins"],
                         ["chrome-extension://jeelmedmciafjnfdpnjgbgipplcddhka/"])
        # Registry entry points at the generated manifest.
        self.assertEqual(self.registry.get(REG_KEY), manifest_path)
        # PIN file stores only a hash.
        pin_file = os.path.join(self.dest, "orchestrator", "state",
                                "approval_pin.json")
        with open(pin_file, "r", encoding="utf-8") as f:
            self.assertNotIn(pin, f.read())
        # Install manifest lists what was created.
        with open(os.path.join(self.dest, "install-manifest.json"),
                  "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["dest_dir"], self.dest)
        self.assertEqual(saved["registry_key"], REG_KEY)
        self.assertIsNone(saved["registry_prior_value"])
        self.assertIn(self.dest, saved["created_paths"])

    def test_refuses_when_dest_exists(self):
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "SKILL.md"), "w") as f:
            f.write("old install")
        with self.assertRaises(InstallError):
            self._installer().install()
        self.assertEqual(self.registry.get(REG_KEY), None)

    def test_refuses_registry_conflict_non_interactive(self):
        self.registry.set(REG_KEY, "C:\\Other\\host.json")
        with self.assertRaises(InstallError):
            self._installer(non_interactive=True).install()
        self.assertEqual(self.registry.get(REG_KEY), "C:\\Other\\host.json")
        self.assertFalse(os.path.exists(self.dest))

    def test_registry_conflict_user_says_no(self):
        self.registry.set(REG_KEY, "C:\\Other\\host.json")
        inst = self._installer(input_fn=lambda prompt: "n")
        with self.assertRaises(InstallError):
            inst.install()
        self.assertEqual(self.registry.get(REG_KEY), "C:\\Other\\host.json")
        self.assertFalse(os.path.exists(self.dest))

    def test_registry_conflict_user_confirms_records_prior(self):
        self.registry.set(REG_KEY, "C:\\Other\\host.json")
        inst = self._installer(input_fn=lambda prompt: "y")
        record, _ = inst.install()
        self.assertEqual(record["registry_prior_value"],
                         "C:\\Other\\host.json")
        self.assertEqual(self.registry.get(REG_KEY),
                         record["host_manifest"])

    def test_refuses_when_exe_missing(self):
        os.remove(os.path.join(self.source, "transport",
                               "agent-relay-host.exe"))
        with self.assertRaises(InstallError):
            self._installer().install()
        self.assertFalse(os.path.exists(self.dest))

    def test_rollback_on_failure(self):
        class FailingRegistry(FakeRegistry):
            def set(self, key_path, value):
                raise OSError("simulated registry failure")
        registry = FailingRegistry()
        inst = Installer(self.source, self.dest, registry)
        with self.assertRaises(OSError):
            inst.install()
        # Destination must be gone again (rolled back).
        self.assertFalse(os.path.exists(self.dest))

    def test_check_only(self):
        self._installer().check()
        self.assertFalse(os.path.exists(self.dest))


class TestInstallTestHostName(unittest.TestCase):
    """RC4-hotfix FIX 3: install.py takes a --host-name; a test install
    (com.agentrelay.host.e2e) writes ONLY the test registry key, and
    uninstall removes the test key (from the install manifest's
    registry_key) without touching the production key."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "agent-relay-skill")
        shutil.copytree(PKG, self.source)
        self.dest = os.path.join(self.tmp.name, "installed",
                                 "agent-relay-skill")
        self.registry = FakeRegistry()

    def tearDown(self):
        self.tmp.cleanup()

    def _installer(self, **kw):
        return Installer(self.source, self.dest, self.registry, **kw)

    def test_custom_host_name_writes_only_test_key(self):
        record, _pin = self._installer(
            host_name="com.agentrelay.host.e2e").install()
        test_key = ("Software\\Google\\Chrome\\NativeMessagingHosts\\"
                    "com.agentrelay.host.e2e")
        manifest_path = os.path.join(
            self.dest, "transport", "extension",
            "com.agentrelay.host.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["name"], "com.agentrelay.host.e2e")
        self.assertEqual(manifest["allowed_origins"],
                         ["chrome-extension://jeelmedmciafjnfdpnjgbgipplcddhka/"])
        self.assertEqual(self.registry.get(test_key), manifest_path)
        # Production key untouched.
        self.assertIsNone(self.registry.get(REG_KEY))
        self.assertEqual(record["registry_key"], test_key)
        self.assertEqual(record["host_name"], "com.agentrelay.host.e2e")

    def test_uninstall_removes_test_key_not_production(self):
        # A production install exists first; then a test install.
        prod_dest = os.path.join(self.tmp.name, "prod",
                                 "agent-relay-skill")
        Installer(self.source, prod_dest, self.registry).install()
        prod_manifest = os.path.join(
            prod_dest, "transport", "extension",
            "com.agentrelay.host.json")
        self.assertEqual(self.registry.get(REG_KEY), prod_manifest)
        record, _pin = self._installer(
            host_name="com.agentrelay.host.e2e").install()
        test_key = record["registry_key"]
        self.assertIsNotNone(self.registry.get(test_key))
        result = uninstall(self.dest, self.registry,
                           non_interactive=True)
        self.assertEqual(result["registry"], "deleted")
        self.assertEqual(result["registry_key"], test_key)
        self.assertIsNone(self.registry.get(test_key))
        # Production key still there, still pointing at prod install.
        self.assertEqual(self.registry.get(REG_KEY), prod_manifest)
        self.assertFalse(os.path.exists(self.dest))

    def test_bad_host_name_refused(self):
        for bad in ("com.example.host", "evil", "",
                    "com.agentrelay.hostx", "com.agentrelay.host "):
            with self.assertRaises(InstallError, msg=bad):
                self._installer(host_name=bad).install()
        self.assertIsNone(self.registry.get(REG_KEY))


class TestUninstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.tmp.name, "agent-relay-skill")
        shutil.copytree(PKG, self.source)
        self.dest = os.path.join(self.tmp.name, "installed",
                                 "agent-relay-skill")
        self.registry = FakeRegistry()
        self.record, _ = Installer(self.source, self.dest,
                                   self.registry).install()

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path(self):
        result = uninstall(self.dest, self.registry)
        self.assertFalse(os.path.exists(self.dest))
        self.assertIsNone(self.registry.get(REG_KEY))
        self.assertEqual(result["registry"], "deleted")
        self.assertIn(self.dest, result["removed"])

    def test_restores_prior_registry_value(self):
        self.registry.set(REG_KEY, "C:\\Other\\host.json")
        inst = Installer(self.source, self.dest, self.registry,
                         input_fn=lambda prompt: "y")
        # Re-install over the confirmed conflict (dest was removed first).
        shutil.rmtree(self.dest)
        record, _ = inst.install()
        self.assertEqual(record["registry_prior_value"],
                         "C:\\Other\\host.json")
        result = uninstall(self.dest, self.registry)
        self.assertEqual(self.registry.get(REG_KEY), "C:\\Other\\host.json")
        self.assertEqual(result["registry"], "restored_prior")

    def test_leaves_registry_alone_if_changed(self):
        self.registry.set(REG_KEY, "C:\\SomeoneElse\\host.json")
        result = uninstall(self.dest, self.registry)
        self.assertEqual(self.registry.get(REG_KEY),
                         "C:\\SomeoneElse\\host.json")
        self.assertEqual(result["registry"], "left_alone_changed")
        self.assertFalse(os.path.exists(self.dest))

    def test_refuses_without_manifest(self):
        os.remove(os.path.join(self.dest, "install-manifest.json"))
        with self.assertRaises(InstallError):
            uninstall(self.dest, self.registry)
        self.assertTrue(os.path.exists(self.dest))

    def test_refuses_non_skill_target(self):
        other = os.path.join(self.tmp.name, "not-a-skill")
        os.makedirs(other)
        with self.assertRaises(InstallError):
            uninstall(other, self.registry)

    def test_keep_state_backs_up(self):
        state = os.path.join(self.dest, "orchestrator", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "discussion.jsonl"), "w") as f:
            f.write('{"kind": "project"}\n')
        backup = os.path.join(self.tmp.name, "backup")
        result = uninstall(self.dest, self.registry, keep_state=True,
                           backup_dir=backup)
        self.assertTrue(os.path.exists(
            os.path.join(backup, "orchestrator-state",
                         "discussion.jsonl")))
        self.assertFalse(os.path.exists(self.dest))
        self.assertEqual(result["backup_dir"], backup)

    def test_keep_state_backup_failure_refuses(self):
        state = os.path.join(self.dest, "orchestrator", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "discussion.jsonl"), "w") as f:
            f.write('{"kind": "project"}\n')
        # backup_dir is an existing FILE, so makedirs fails.
        blocker = os.path.join(self.tmp.name, "blocker")
        with open(blocker, "w") as f:
            f.write("not a dir")
        with self.assertRaises(InstallError):
            uninstall(self.dest, self.registry, keep_state=True,
                      backup_dir=blocker)
        self.assertTrue(os.path.exists(self.dest))


if __name__ == "__main__":
    unittest.main()
