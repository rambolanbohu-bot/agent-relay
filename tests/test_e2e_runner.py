#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4-hotfix6 - e2e_runner stage-machine tests.

HOTFIX 6 P1: the Windows E2E stage logic moved from the monolithic
run_e2e_test.bat into windows_e2e_test/e2e_runner.py (Python), because
the BAT skipped from init straight to cleanup on the real machine
in ATTEMPT-05/08/09 and the BAT's static checks cannot prevent a
control-flow failure. These tests prove the stage machine's
invariants on Linux with a fake ops object (no Windows, no Chrome):

  - every stage runs in order and writes start/end markers;
  - a failed stage aborts the run and no later stage is reached;
  - cleanup ALWAYS runs (try/finally), even when a stage failed;
  - uninstall is called ONLY when install actually completed;
    when install never completed, cleanup only verifies nothing
    was left behind and never calls uninstall.py;
  - a failed INSTALL cannot reach CLEANUP's uninstall call;
  - stage skip is impossible (the marker list is a strict
    prefix of the canonical stage order plus CLEANUP).

The real Windows run is ATTEMPT-10.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, "windows_e2e_test"))

import e2e_runner
from e2e_runner import (  # noqa: E402
    EXIT_B_PENDING, EXIT_CHROME_LAUNCH, EXIT_CHROME_NOT_FOUND, EXIT_CLEANUP_FAILED,
    EXIT_DRIVER_FAILED, EXIT_INSTALL_FAILED, EXIT_MANIFEST_CONTENT,
    EXIT_OK, EXIT_TEST_REG_EXISTS, FakeOps, Runner, STAGES,
    TEST_HOST_NAME, main)

REG_ROOT = (r"HKCU\Software\Google\Chrome\NativeMessagingHosts")
TEST_KEY = "%s\\%s" % (REG_ROOT, TEST_HOST_NAME)
PROD_KEY = "%s\\com.agentrelay.host" % REG_ROOT


def _script_name(cmd):
    """The script a recorded run() cmd list invoked."""
    for part in cmd:
        if part.endswith(".py"):
            return os.path.basename(part)
    return ""


class StatefulFakeOps(FakeOps):
    """FakeOps whose registry state follows install/uninstall,
    like the real machine: the test key appears only after a
    successful install and disappears after uninstall."""

    def __init__(self, results=None):
        super().__init__(results)
        self.installed = False

    def reg_query(self, key):
        if key == TEST_KEY:
            if self.installed:
                return 0, "test host entry present"
            return 1, "ERROR: The system was unable to find the "\
                      "specified registry key or value."
        return 1, "ERROR: The system was unable to find the "\
                  "specified registry key or value."

    def run(self, cmd, log_handle):
        self.run_log.append(list(cmd))
        name = _script_name(cmd)
        if name == "install.py":
            code = self.results.get("run:install.py", 0)
            if code == 0:
                self.installed = True
            elif getattr(self, "install_leaves_key", False):
                # A partial install that failed but left the test
                # registry entry behind.
                self.installed = True
            return code
        if name == "uninstall.py":
            code = self.results.get("run:uninstall.py", 0)
            if code == 0:
                self.installed = False
            return code
        return self.results.get("run:" + name, 0)

    def path_exists(self, path):
        if path.endswith("agent-relay-host.exe"):
            return self.installed
        if path.endswith("test-extension"):
            return True
        return False


class RunnerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ops = StatefulFakeOps()
        self.runner = Runner(PKG, ops=self.ops,
                             temp_root=self.tmp.name,
                             run_id="12345678")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_scripts(self):
        return [_script_name(c) for c in self.ops.run_log
                if c[0] != "launch"]

    def _stages(self):
        return [(m["stage"], m["event"]) for m in self.runner.markers]


class TestHappyPath(RunnerTestBase):
    def test_all_stages_run_in_order_and_b_is_pending(self):
        code = self.runner.run()
        self.assertEqual(code, EXIT_B_PENDING)
        self.assertTrue(self.runner.install_completed)
        stages = [m["stage"] for m in self.runner.markers
                  if m["event"] == "start"]
        self.assertEqual(stages, list(STAGES))
        # Only B lacks verification in this simulated run.
        for m in self.runner.markers:
            if m["event"] == "end":
                expected = EXIT_B_PENDING if m["stage"] == "B" else EXIT_OK
                self.assertEqual(m["exit_code"], expected, m)

    def test_happy_path_runs_install_uninstall_and_driver(self):
        self.runner.run()
        scripts = self._run_scripts()
        for name in ("install.py", "verify_manifest.py",
                     "make_test_extension.py",
                     "native_host_driver.py", "uninstall.py"):
            self.assertIn(name, scripts, scripts)
        self.assertTrue(self.ops.waited)
        self.assertIn(self.runner.test_ext_dir, self.ops.removed)

    def test_browser_exit_during_operator_wait_still_cleans_up(self):
        def browser_exits(prompt, process):
            path = os.path.join(self.runner.record_dir, "stage-checkpoint.json")
            with open(path, encoding="utf-8") as record:
                self.assertEqual(json.load(record)["active_stage"], "B")
            return "browser_exited"

        self.ops.wait_operator = browser_exits
        self.assertEqual(self.runner.run(), EXIT_B_PENDING)
        self.assertEqual(self.runner.markers[-1]["stage"], "CLEANUP")
        self.assertEqual(self.runner.markers[-1]["exit_code"], EXIT_OK)

    def test_stage_markers_json_written(self):
        self.runner.run()
        path = os.path.join(self.runner.record_dir,
                            "stage-markers.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["run_id"], "12345678")
        self.assertTrue(data["install_completed"])
        self.assertEqual(data["exit_code"], EXIT_B_PENDING)
        self.assertEqual(
            [m["stage"] for m in data["markers"]
             if m["event"] == "start"], list(STAGES))

    def test_prod_reg_snapshots_identical(self):
        self.runner.run()
        record = self.runner.record_dir
        for name in ("prod-reg-before.txt",
                     "prod-reg-after-install.txt",
                     "prod-reg-after-uninstall.txt"):
            self.assertTrue(os.path.isfile(os.path.join(record, name)),
                            name)
        with open(os.path.join(record, "prod-reg-before.txt"),
                  "r", encoding="utf-8") as f:
            before = f.read()
        with open(os.path.join(record,
                               "prod-reg-after-uninstall.txt"),
                  "r", encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)


class TestFailFast(RunnerTestBase):
    def test_install_failure_aborts_and_never_calls_uninstall(self):
        self.ops.results["run:install.py"] = 1
        code = self.runner.run()
        self.assertEqual(code, EXIT_INSTALL_FAILED)
        self.assertFalse(self.runner.install_completed)
        scripts = self._run_scripts()
        self.assertIn("install.py", scripts)
        self.assertNotIn("verify_manifest.py", scripts)
        self.assertNotIn("native_host_driver.py", scripts)
        self.assertNotIn("uninstall.py", scripts,
                         "a failed INSTALL must never reach "
                         "CLEANUP's uninstall call")
        # Cleanup still ran and verified nothing was left.
        self.assertEqual(
            [m["stage"] for m in self.runner.markers
             if m["event"] == "start"],
            ["INIT", "PREFLIGHT", "INSTALL", "CLEANUP"])
        self.assertFalse(self.ops.waited)

    def test_preflight_test_key_exists_aborts_before_install(self):
        self.ops.installed = True  # test key already present
        code = self.runner.run()
        self.assertEqual(code, EXIT_TEST_REG_EXISTS)
        self.assertFalse(self.runner.install_completed)
        self.assertNotIn("install.py", self._run_scripts())
        self.assertNotIn("uninstall.py", self._run_scripts())

    def test_chrome_not_found_aborts_before_install(self):
        self.ops.results["chrome"] = None
        code = self.runner.run()
        self.assertEqual(code, EXIT_CHROME_NOT_FOUND)
        self.assertNotIn("install.py", self._run_scripts())

    def test_manifest_content_failure_aborts_before_driver(self):
        self.ops.results["run:verify_manifest.py"] = 1
        code = self.runner.run()
        self.assertEqual(code, EXIT_MANIFEST_CONTENT)
        scripts = self._run_scripts()
        self.assertIn("install.py", scripts)
        self.assertIn("verify_manifest.py", scripts)
        self.assertNotIn("native_host_driver.py", scripts)
        # Install DID complete, so cleanup must uninstall.
        self.assertIn("uninstall.py", scripts)
        self.assertTrue(self.runner.install_completed)

    def test_driver_failure_aborts_before_b(self):
        self.ops.results["run:native_host_driver.py"] = 2
        code = self.runner.run()
        self.assertEqual(code, EXIT_DRIVER_FAILED)
        self.assertNotIn("launch", [c[0] for c in self.ops.run_log])
        self.assertIn("uninstall.py", self._run_scripts())
        self.assertFalse(self.ops.waited)

    def test_failed_stage_has_one_terminal_marker(self):
        failures = {
            "INIT": ("long_path", None),
            "PREFLIGHT": ("chrome", None),
            "INSTALL": ("run:install.py", 1),
            "MANIFEST": ("run:verify_manifest.py", 1),
            "MKEXT": ("run:make_test_extension.py", 1),
            "DRIVER": ("run:native_host_driver.py", 1),
            "B": ("launch_chrome", None),
            "CLEANUP": ("run:uninstall.py", 1),
        }
        for index, (stage, (key, value)) in enumerate(failures.items()):
            with self.subTest(stage=stage):
                self.ops = StatefulFakeOps({key: value})
                if key in ("launch_chrome", "long_path"):
                    def fail(*args):
                        raise OSError("injected")
                    setattr(self.ops, key, fail)
                self.runner = Runner(PKG, ops=self.ops, temp_root=self.tmp.name,
                                     run_id=str(10000000 + index))
                code = self.runner.run()
                self.assertNotEqual(code, EXIT_OK)
                starts = [m["stage"] for m in self.runner.markers
                          if m["event"] == "start"]
                expected = list(STAGES[:STAGES.index(stage)]) + [stage]
                if stage != "CLEANUP":
                    expected.append("CLEANUP")
                self.assertEqual(starts, expected)
                ends = [m for m in self.runner.markers if m["event"] == "end"]
                self.assertEqual([m["stage"] for m in ends], starts)
                stage_exit = next(m["exit_code"] for m in ends
                                  if m["stage"] == stage)
                self.assertEqual(stage_exit, EXIT_CLEANUP_FAILED
                                 if stage == "CLEANUP" else code)
                if stage == "CLEANUP":
                    self.assertEqual(code, EXIT_CLEANUP_FAILED)

    def test_operator_acknowledgment_without_b_evidence_cannot_pass(self):
        self.assertNotEqual(self.runner.run(), EXIT_OK)
        self.assertTrue(self.ops.waited)
        self.assertIn("uninstall.py", self._run_scripts())
        self.assertTrue(any(m["stage"] == "DRIVER" and m["exit_code"] == 0
                            for m in self.runner.markers))

    def test_b1_requires_matching_live_test_extension(self):
        for evidence, expected in (
            (None, "TIMEOUT"),
            ({"extension_id": "wrong"}, "FAIL"),
            ({"extension_id": e2e_runner.EXTENSION_ID}, "PASS"),
        ):
            with self.subTest(expected=expected):
                self.ops = StatefulFakeOps()
                self.ops.probe_b1 = lambda *args: evidence
                self.runner = Runner(PKG, ops=self.ops, temp_root=self.tmp.name)
                self.assertNotEqual(self.runner.run(), EXIT_OK)
                path = os.path.join(self.runner.record_dir, "segment-b.json")
                with open(path, encoding="utf-8") as file:
                    record = json.load(file)
                self.assertEqual(record["steps"]["B1"]["status"], expected)
                self.assertEqual(record["steps"]["B2"]["status"], "PENDING")
                self.assertEqual(self.ops.waited, expected == "PASS")

    def test_b1_ignores_stale_run_and_coordinator_records(self):
        root = os.path.join(self.tmp.name, "orchestrator", "state", "native_host")
        os.makedirs(root)
        outbox = os.path.join(root, "outbox.jsonl")
        def receipt(direction, run_id):
            return {"direction": direction,
                    "envelope": {"type": "e2e_browser_ready", "run_id": run_id,
                                 "extension_id": e2e_runner.EXTENSION_ID}}
        process = type("StoppedProcess", (), {"poll": lambda self: 0})()
        ops = e2e_runner.RealOps()
        with open(outbox, "w", encoding="utf-8") as file:
            for row in (receipt("extension_to_coordinator", "old"),
                        receipt("coordinator_to_extension", "new")):
                file.write(json.dumps(row) + "\n")
            file.write(json.dumps(receipt("extension_to_coordinator", "new")))
        self.assertIsNone(ops.probe_b1(self.tmp.name, "new", process))
        with open(outbox, "a", encoding="utf-8") as file:
            file.write("\n")
        self.assertEqual(ops.probe_b1(self.tmp.name, "new", process),
                         {"extension_id": e2e_runner.EXTENSION_ID})

    def test_real_ops_captures_non_ascii_stage_output(self):
        with tempfile.TemporaryFile(mode="w+b") as log:
            with patch.dict(os.environ, {"PYTHONIOENCODING": "cp1252"}):
                code = e2e_runner.RealOps().run(
                    [sys.executable, "-c", "print(chr(0x4E2D))"], log)
            self.assertEqual(code, EXIT_OK)
            log.seek(0)
            self.assertEqual(log.read().decode("utf-8").strip(), chr(0x4E2D))

    def test_existing_run_directory_cannot_supply_b1_evidence(self):
        base = os.path.join(self.tmp.name, "agent-relay-e2e-12345678")
        os.makedirs(base)
        self.assertEqual(self.runner.run(), e2e_runner.EXIT_ISOLATED_DIR)
        self.assertEqual(self.ops.run_log, [])
        self.assertEqual(os.listdir(base), [])

    def test_stage_skip_is_impossible(self):
        # Whichever stage fails, the marker list is a strict prefix
        # of the canonical order plus CLEANUP - a later stage can
        # never appear after a failed one.
        self.ops.results["run:make_test_extension.py"] = 1
        code = self.runner.run()
        self.assertEqual(code, 21)
        starts = [m["stage"] for m in self.runner.markers
                  if m["event"] == "start"]
        self.assertEqual(
            starts,
            ["INIT", "PREFLIGHT", "INSTALL", "MANIFEST", "MKEXT",
             "CLEANUP"])
        self.assertNotIn("DRIVER", starts)
        self.assertNotIn("B", starts)


class TestCleanupRules(RunnerTestBase):
    def test_cleanup_always_runs_after_failure(self):
        self.ops.results["run:install.py"] = 1
        self.runner.run()
        starts = [m["stage"] for m in self.runner.markers
                  if m["event"] == "start"]
        self.assertIn("CLEANUP", starts)
        ends = [m for m in self.runner.markers
                if m["stage"] == "CLEANUP" and m["event"] == "end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["exit_code"], 0)

    def test_cleanup_uninstall_failure_reports_exit_24(self):
        self.ops.results["run:uninstall.py"] = 2
        code = self.runner.run()
        self.assertEqual(code, EXIT_CLEANUP_FAILED)
        self.assertEqual(self.runner.markers[-1]["stage"], "CLEANUP")
        self.assertEqual(self.runner.markers[-1]["exit_code"], EXIT_CLEANUP_FAILED)
        self.assertTrue(self.runner.install_completed)

    def test_cleanup_never_calls_uninstall_when_install_never_ran(self):
        # Even when the test key somehow exists after a failed
        # install, cleanup reports it but must not uninstall.
        self.ops.results["run:install.py"] = 1
        self.ops.install_leaves_key = True
        code = self.runner.run()
        self.assertEqual(code, EXIT_INSTALL_FAILED)
        self.assertNotIn("uninstall.py", self._run_scripts())


class TestMain(unittest.TestCase):
    def test_main_requires_exactly_one_argument(self):
        self.assertEqual(main([]), 11)
        self.assertEqual(main(["a", "b"]), 11)

    def test_main_rejects_missing_package_dir(self):
        self.assertEqual(main(["/definitely/not/here-xyz"]), 11)

    def test_runner_rejects_missing_package_dir(self):
        runner = Runner("/definitely/not/here-xyz",
                        ops=FakeOps(), temp_root=tempfile.gettempdir(),
                        run_id="87654321")
        try:
            self.assertEqual(runner.run(), 11)
        finally:
            shutil.rmtree(os.path.join(tempfile.gettempdir(),
                                       "agent-relay-e2e-87654321"),
                          ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
