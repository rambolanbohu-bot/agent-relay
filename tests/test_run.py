#!/usr/bin/env python3
"""RC3 smoke tests for orchestrator/run.py (RC2 smoke + RC3 two-mode split).

Runs the real run.py CLI against a throwaway copy of the package
(browser_task mode, so no extension / native host is needed) and checks:
create -> advance (handoff) -> record-send -> status (with the honesty
block) -> pause -> complete. Also checks the state log stays valid
(verify passes, no duplicate message_ids).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)


class TestRunPy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill_root = os.path.join(self.tmp.name, "agent-relay-skill")
        shutil.copytree(PKG, self.skill_root)
        self.run = os.path.join(self.skill_root, "orchestrator", "run.py")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args, expect=0):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", self.run, "--skill-root", self.skill_root,
             "--mode", "browser_task", *args],
            capture_output=True, encoding="utf-8", timeout=60)
        if expect is not None:
            self.assertEqual(proc.returncode, expect,
                             f"{args}: stdout={proc.stdout} "
                             f"stderr={proc.stderr}")
        try:
            return json.loads(proc.stdout)
        except ValueError:
            return {"_raw": proc.stdout, "_stderr": proc.stderr}

    def test_create_advance_record_status(self):
        out = self._run("create", "--topic", "test topic",
                        "--project-id", "P-TEST")
        self.assertEqual(out["status"], "created")
        self.assertEqual(out["project_id"], "P-TEST")
        # Honesty block is present even at creation.
        self.assertIn("NOT YET IMPLEMENTED", out["honesty"])
        # Advance with no reply file: browser_task mode has no live
        # extension, so it returns a handoff instead of hanging.
        out = self._run("advance", "--project-id", "P-TEST", expect=1)
        self.assertEqual(out["status"], "handoff_needed")
        # Advance with a reply file: send also hands off in this mode.
        reply = os.path.join(self.tmp.name, "reply.txt")
        with open(reply, "w", encoding="utf-8") as f:
            f.write("Round 1: proposal — use the browser adapter.")
        out = self._run("advance", "--project-id", "P-TEST",
                        "--reply-file", reply, expect=1)
        self.assertEqual(out["status"], "handoff_needed")
        message_id = out["handoff"]["message_id"]
        # Complete the transaction the way the Muse session would after
        # performing the browser task.
        out = self._run("record-send", "--project-id", "P-TEST",
                        "--message-id", message_id, "--outcome", "sent",
                        "--content-file", reply)
        self.assertEqual(out["status"], "recorded")
        self.assertEqual(out["outcome"], "sent")
        # Status shows the turn and the honesty block.
        out = self._run("status", "--project-id", "P-TEST")
        self.assertEqual(out["project_id"], "P-TEST")
        self.assertEqual(out["turn_number"], 1)
        self.assertIn("NOT YET IMPLEMENTED",
                      out["honesty"]["muse_handoff_auto_wake"])
        self.assertIn("python_coordinator_can_do_automatically",
                      out["honesty"])
        # Pause and complete.
        out = self._run("pause", "--project-id", "P-TEST",
                        "--reason", "test pause")
        self.assertEqual(out["status"], "paused")
        out = self._run("complete", "--project-id", "P-TEST",
                        "--reason", "test done")
        self.assertEqual(out["status"], "completed")
        # The state log is still valid (no dupes, hashes ok).
        sys.path.insert(0, os.path.join(self.skill_root, "orchestrator"))
        import file_log
        log = os.path.join(self.skill_root, "orchestrator", "state",
                           "discussion.jsonl")
        result = file_log.verify_log(log)
        self.assertTrue(result["ok"], result["problems"])

    def test_unknown_project(self):
        out = self._run("status", "--project-id", "P-NOPE", expect=1)
        self.assertEqual(out["error"], "project_not_found")

    def test_reconcile_with_uncertain_pauses(self):
        self._run("create", "--topic", "t", "--project-id", "P-U")
        reply = os.path.join(self.tmp.name, "reply.txt")
        with open(reply, "w", encoding="utf-8") as f:
            f.write("Round 1 text.")
        out = self._run("advance", "--project-id", "P-U",
                        "--reply-file", reply, expect=1)
        message_id = out["handoff"]["message_id"]
        # Browser result "unknown" -> UNCERTAIN; resume must refuse.
        out = self._run("record-send", "--project-id", "P-U",
                        "--message-id", message_id, "--outcome", "unknown",
                        expect=1)
        self.assertEqual(out["outcome"], "uncertain")
        out = self._run("resume", "--project-id", "P-U", expect=1)
        self.assertEqual(out["status"], "paused_uncertain")


class TestTwoModes(unittest.TestCase):
    """RC4: Discussion (default, no externally-effective ops) vs
    Execution (needs execution mode + a local-approval-page approval;
    the Muse approval card channel is disabled in RC4)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill_root = os.path.join(self.tmp.name, "agent-relay-skill")
        shutil.copytree(PKG, self.skill_root)
        self.run = os.path.join(self.skill_root, "orchestrator", "run.py")
        sys.path.insert(0, os.path.join(self.skill_root, "approvals"))
        sys.path.insert(0, os.path.join(self.skill_root, "orchestrator"))
        from approvals import ApprovalStore, local_page_credential
        self.ApprovalStore = ApprovalStore
        self.local_page_credential = local_page_credential

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args, expect=0):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", self.run, "--skill-root", self.skill_root,
             "--mode", "browser_task", *args],
            capture_output=True, encoding="utf-8", timeout=60)
        if expect is not None:
            self.assertEqual(proc.returncode, expect,
                             f"{args}: stdout={proc.stdout} "
                             f"stderr={proc.stderr}")
        try:
            return json.loads(proc.stdout)
        except ValueError:
            return {"_raw": proc.stdout, "_stderr": proc.stderr}

    def _params(self, **over):
        params = {"action": "write_file", "path": "summary.md",
                  "content": "Agreed: use the browser adapter."}
        params.update(over)
        p = os.path.join(self.tmp.name, "params.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(params, f)
        return p, params

    def _approved_decision(self, params):
        # Approve the way the local approval page does: register a
        # session (after PIN) and use the decision-bound nonce.
        store = self.ApprovalStore(os.path.join(
            self.skill_root, "orchestrator", "state", "approvals.json"))
        created = store.create_decision(
            project_id="P-EXE", operation_id="OP-write-summary",
            operation_params=params, options=["write", "skip"],
            recommended_option="write", evidence=["round 3 consensus"],
            cost="AUD 0", risk="low", recommendation="write",
            approver="leo", ttl_seconds=3600)
        session = store.register_page_session("leo")
        data = store._load()
        nonce = data["decisions"][created["decision_id"]]["page_nonce"]
        cred = self.local_page_credential(session["session_token"],
                                          nonce, "leo")
        ok, reason = store.approve(created["decision_id"],
                                   created["token"], "write", cred)
        self.assertTrue(ok, reason)
        return created

    def test_execute_refused_in_discussion_mode(self):
        self._run("create", "--topic", "t", "--project-id", "P-EXE")
        params_file, _ = self._params()
        out = self._run("execute", "--project-id", "P-EXE",
                        "--decision-id", "DEC-whatever",
                        "--operation-id", "OP-write-summary",
                        "--params-file", params_file, expect=1)
        self.assertEqual(out["status"], "refused")
        self.assertEqual(out["reason"], "mode_is_discussion")

    def test_execute_refused_without_approval(self):
        self._run("create", "--topic", "t", "--project-id", "P-EXE")
        self._run("set-mode", "--project-id", "P-EXE",
                  "--mode", "execution")
        params_file, _ = self._params()
        out = self._run("execute", "--project-id", "P-EXE",
                        "--decision-id", "DEC-nope",
                        "--operation-id", "OP-write-summary",
                        "--params-file", params_file, expect=1)
        self.assertEqual(out["status"], "refused")
        self.assertEqual(out["reason"], "decision_not_found")

    def test_execute_allowed_with_approval_writes_file(self):
        self._run("create", "--topic", "t", "--project-id", "P-EXE")
        self._run("set-mode", "--project-id", "P-EXE",
                  "--mode", "execution")
        params_file, params = self._params()
        created = self._approved_decision(params)
        out = self._run("execute", "--project-id", "P-EXE",
                        "--decision-id", created["decision_id"],
                        "--operation-id", "OP-write-summary",
                        "--params-file", params_file)
        self.assertEqual(out["status"], "executed")
        target = os.path.join(self.skill_root, "orchestrator", "state",
                              "projects", "P-EXE", "summary.md")
        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), params["content"])
        # Second execute with the same approval is refused (one-shot).
        out = self._run("execute", "--project-id", "P-EXE",
                        "--decision-id", created["decision_id"],
                        "--operation-id", "OP-write-summary",
                        "--params-file", params_file, expect=1)
        self.assertEqual(out["status"], "refused")
        self.assertEqual(out["reason"], "approval_already_executed")

    def test_execute_path_escape_refused(self):
        self._run("create", "--topic", "t", "--project-id", "P-EXE")
        self._run("set-mode", "--project-id", "P-EXE",
                  "--mode", "execution")
        params_file, params = self._params(path="../escape.md")
        created = self._approved_decision(params)
        out = self._run("execute", "--project-id", "P-EXE",
                        "--decision-id", created["decision_id"],
                        "--operation-id", "OP-write-summary",
                        "--params-file", params_file, expect=1)
        self.assertEqual(out["status"], "refused")
        self.assertEqual(out["reason"], "path_escapes_project_dir")

    def test_execute_non_whitelisted_action_refused(self):
        self._run("create", "--topic", "t", "--project-id", "P-EXE")
        self._run("set-mode", "--project-id", "P-EXE",
                  "--mode", "execution")
        params_file, params = self._params(action="delete_everything")
        created = self._approved_decision(params)
        out = self._run("execute", "--project-id", "P-EXE",
                        "--decision-id", created["decision_id"],
                        "--operation-id", "OP-write-summary",
                        "--params-file", params_file, expect=1)
        self.assertEqual(out["status"], "refused")
        self.assertEqual(out["reason"], "operation_not_whitelisted")

    def test_status_reports_mode_and_exe(self):
        self._run("create", "--topic", "t", "--project-id", "P-EXE")
        out = self._run("status", "--project-id", "P-EXE")
        self.assertEqual(out["mode"], "discussion")
        self.assertTrue(out["windows_host_exe"]["present"])
        self.assertIn("NOT been run on a real Windows machine",
                      out["windows_host_exe"]["note"])
        self.assertIn("two_modes", out["honesty"])
        self._run("set-mode", "--project-id", "P-EXE",
                  "--mode", "execution")
        out = self._run("status", "--project-id", "P-EXE")
        self.assertEqual(out["mode"], "execution")


class TestStateMachine(unittest.TestCase):
    """RC4-hotfix FIX 2: _project() merges the latest project_status
    record (latest-wins by log sequence); advance enforces state
    restrictions (CREATED/DISCUSSING allow, PAUSED refuses with a
    resume instruction, COMPLETED/BLOCKED refuse); resume writes the
    new state into the log; a fresh Runner on the same log still sees
    terminal states (restart recovery)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill_root = os.path.join(self.tmp.name, "agent-relay-skill")
        shutil.copytree(PKG, self.skill_root)
        self.run = os.path.join(self.skill_root, "orchestrator", "run.py")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args, expect=0):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", self.run, "--skill-root", self.skill_root,
             "--mode", "browser_task", *args],
            capture_output=True, encoding="utf-8", timeout=60)
        if expect is not None:
            self.assertEqual(proc.returncode, expect,
                             f"{args}: stdout={proc.stdout} "
                             f"stderr={proc.stderr}")
        try:
            return json.loads(proc.stdout)
        except ValueError:
            return {"_raw": proc.stdout, "_stderr": proc.stderr}

    def _append_status(self, project_id, status, detail=""):
        # Write a project_status record the way the watchdog / an
        # operator would (BLOCKED has no CLI command of its own).
        sys.path.insert(0, os.path.join(self.skill_root, "orchestrator"))
        import file_log
        log = os.path.join(self.skill_root, "orchestrator", "state",
                           "discussion.jsonl")
        file_log.append_record(log, {"kind": "project_status",
                                     "project_id": project_id,
                                     "status": status, "detail": detail})

    def test_pause_shows_paused_and_advance_refuses(self):
        self._run("create", "--topic", "t", "--project-id", "P-SM")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "CREATED")
        self._run("pause", "--project-id", "P-SM", "--reason", "test")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "PAUSED")
        out = self._run("advance", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["error"], "project_paused")
        self.assertIn("resume", out["instruction"].lower())

    def test_resume_after_pause_advance_works(self):
        self._run("create", "--topic", "t", "--project-id", "P-SM")
        self._run("pause", "--project-id", "P-SM", "--reason", "test")
        out = self._run("resume", "--project-id", "P-SM")
        self.assertEqual(out["status"], "resumed")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "DISCUSSING")
        # Advance is allowed again (browser_task mode: it hands off
        # instead of sending, which proves the state gate passed).
        out = self._run("advance", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["status"], "handoff_needed")

    def test_complete_shows_completed_and_advance_refuses(self):
        self._run("create", "--topic", "t", "--project-id", "P-SM")
        self._run("complete", "--project-id", "P-SM", "--reason", "done")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "COMPLETED")
        out = self._run("advance", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["error"], "project_closed")
        self.assertEqual(out["status"], "COMPLETED")
        # Terminal states refuse resume / pause / complete too.
        out = self._run("resume", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["error"], "project_closed")
        out = self._run("pause", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["error"], "project_closed")
        out = self._run("complete", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["error"], "project_closed")

    def test_blocked_refuses_advance(self):
        self._run("create", "--topic", "t", "--project-id", "P-SM")
        self._append_status("P-SM", "BLOCKED",
                            detail="watchdog: stalled")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "BLOCKED")
        out = self._run("advance", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["error"], "project_closed")
        self.assertEqual(out["status"], "BLOCKED")

    def test_latest_status_wins(self):
        # Old events must not overwrite new ones: pause, resume,
        # pause again — the latest record decides.
        self._run("create", "--topic", "t", "--project-id", "P-SM")
        self._run("pause", "--project-id", "P-SM", "--reason", "1")
        self._run("resume", "--project-id", "P-SM")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "DISCUSSING")
        self._run("pause", "--project-id", "P-SM", "--reason", "2")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "PAUSED")
        self._run("complete", "--project-id", "P-SM", "--reason", "done")
        out = self._run("status", "--project-id", "P-SM")
        self.assertEqual(out["status"], "COMPLETED")

    def test_fresh_runner_sees_terminal_state(self):
        # Restart recovery: a new Runner instance on the same log
        # still sees COMPLETED (and advance still refuses).
        self._run("create", "--topic", "t", "--project-id", "P-SM")
        self._run("complete", "--project-id", "P-SM", "--reason", "done")
        sys.path.insert(0, os.path.join(self.skill_root, "orchestrator"))
        sys.path.insert(0, os.path.join(self.skill_root, "transport"))
        sys.path.insert(0, os.path.join(self.skill_root, "approvals"))
        import run as run_mod
        runner = run_mod.Runner(self.skill_root, mode="browser_task")
        project = runner._project("P-SM")
        self.assertEqual(project["status"], "COMPLETED")
        out = self._run("advance", "--project-id", "P-SM", expect=1)
        self.assertEqual(out["error"], "project_closed")


if __name__ == "__main__":
    unittest.main()
