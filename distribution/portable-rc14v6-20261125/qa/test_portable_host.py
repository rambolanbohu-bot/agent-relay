#!/usr/bin/env python3
"""Portable registration unit tests; isolated fake HKCU, no real Windows change."""
import importlib.util, json, os, pathlib, shutil, tempfile, unittest, sys
SCRIPT=pathlib.Path(__file__).resolve().parent / "portable_host.py"
spec=importlib.util.spec_from_file_location("portable_host", SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
UP=pathlib.Path(__file__).resolve().parent/"upstream"

class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)/"Agent Relay Portable Folder"
        for rel in ["SKILL.md","approvals/approvals.py","approvals/local_approval_page.py",
                    "orchestrator/run.py","orchestrator/locking.py","transport/agent-relay-host.exe",
                    "transport/agent-relay-host.exe.sha256","transport/native_host.py",
                    "transport/extension/EXTENSION_ID.txt"]:
            dst=self.root/rel; dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(UP/rel,dst)
        self.reg=m.FakeRegistry()
        self.host=m.PortableManager(self.root,self.reg)

    def test_fresh_register_writes_in_place_host_and_pin(self):
        r=self.host.register()
        self.assertEqual(r["action"],"registered")
        self.assertEqual(self.reg.get(m.KEY),str(self.host.manifest))
        manifest=json.loads(self.host.manifest.read_text())
        self.assertEqual(manifest["path"],str(self.host.exe))
        self.assertEqual(manifest["allowed_origins"],["chrome-extension://jeelmedmciafjnfdpnjgbgipplcddhka/"])
        self.assertTrue(self.host.pin.exists())
        self.assertNotIn(r["pin_once"],self.host.pin.read_text())
        self.assertFalse((self.root/"install-manifest.json").exists())

    def test_invalid_id_refused_without_writes(self):
        with self.assertRaises(m.PortableError):
            self.host.register("http://bad")
        self.assertIsNone(self.reg.get(m.KEY))
        self.assertFalse(self.host.pin.exists())

    def test_existing_registry_not_replaced_silently(self):
        self.reg.set(m.KEY,"C:\\old\\host.json")
        with self.assertRaises(m.PortableError):
            self.host.register()
        self.assertEqual(self.reg.get(m.KEY),"C:\\old\\host.json")

    def test_explicit_replace_then_restore_prior(self):
        self.reg.set(m.KEY,"C:\\old\\host.json")
        self.host.register(replace_existing=True)
        res=self.host.unregister()
        self.assertEqual(self.reg.get(m.KEY),"C:\\old\\host.json")
        self.assertTrue(res["previous_host_restored"])
        self.assertTrue(self.host.exe.exists())
        self.assertTrue(self.host.pin.exists())

    def test_unregister_no_data_or_core_deleted(self):
        self.host.register()
        custom=self.root/"orchestrator"/"state"/"discussion.log"
        custom.write_text("keep this")
        res=self.host.unregister()
        self.assertEqual(res["action"],"unregistered")
        self.assertIsNone(self.reg.get(m.KEY))
        self.assertFalse(self.host.manifest.exists())
        self.assertFalse(self.host.record.exists())
        self.assertEqual(custom.read_text(),"keep this")
        self.assertTrue(self.host.pin.exists())
        self.assertTrue(self.host.exe.exists())

    def test_re_register_preserves_pin_and_prior(self):
        self.host.register()
        before=self.host.pin.read_bytes()
        new_id="abcdefghijklmnopabcdefghijklmnop"
        self.host.register(new_id)
        self.assertEqual(self.host.pin.read_bytes(),before)
        self.assertEqual(json.loads(self.host.manifest.read_text())["allowed_origins"],
                         [f"chrome-extension://{new_id}/"])
        self.host.unregister()
        self.assertIsNone(self.reg.get(m.KEY))

    def test_external_registry_change_refuses_unregister(self):
        self.host.register()
        self.reg.set(m.KEY,"C:\\other\\changed.json")
        with self.assertRaises(m.PortableError):
            self.host.unregister()
        self.assertEqual(self.reg.get(m.KEY),"C:\\other\\changed.json")
        self.assertTrue(self.host.record.exists())

    def test_dry_run_has_no_mutations(self):
        r=self.host.register(dry_run=True)
        self.assertEqual(r["action"],"dry-run")
        self.assertIsNone(self.reg.get(m.KEY))
        self.assertFalse(self.host.pin.exists())

    def test_missing_exe_refuses_registration(self):
        self.host.exe.unlink()
        with self.assertRaises(m.PortableError):
            self.host.register()
        self.assertFalse(self.host.record.exists())

    def test_tampered_exe_refuses_registration(self):
        with self.host.exe.open("ab") as f:f.write(b"tamper")
        with self.assertRaises(m.PortableError):
            self.host.register()
        self.assertFalse(self.host.record.exists())

    def test_corrupt_record_refuses_unregistration(self):
        self.host.register()
        self.host.record.write_text('{"root":"C:\\\\unrelated"}')
        with self.assertRaises(m.PortableError):
            self.host.unregister()
        self.assertEqual(self.reg.get(m.KEY),str(self.host.manifest))

    def test_failed_registry_set_rolls_back(self):
        class FaultReg(m.FakeRegistry):
            def __init__(self): super().__init__();self.fail=True
            def set(self,key,val):
                if self.fail:self.fail=False;raise RuntimeError("simulated winreg failure")
                super().set(key,val)
        reg=FaultReg()
        host=m.PortableManager(self.root,reg)
        with self.assertRaises(RuntimeError):
            host.register()
        self.assertIsNone(reg.get(m.KEY))
        self.assertFalse(host.manifest.exists())
        self.assertFalse(host.record.exists())
        self.assertFalse(host.pin.exists())

    def test_other_record_root_refused(self):
        self.host.register()
        state=json.loads(self.host.record.read_text())
        state["root"]="C:\\other"
        self.host.record.write_text(json.dumps(state))
        with self.assertRaises(m.PortableError):
            self.host.register()
        self.assertEqual(self.reg.get(m.KEY),str(self.host.manifest))

if __name__=="__main__":
    unittest.main(verbosity=2)