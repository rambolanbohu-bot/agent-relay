#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4-hotfix6 - Windows E2E test runner (P1).

HOTFIX 6 replaces the monolithic `run_e2e_test.bat` stage logic with
this Python runner. The BAT is now a THIN ENTRY only: it finds Python,
locates the package directory, and calls this file. All stage logic
lives here, in Python, because CMD's parser proved unreliable on the
real machine (ATTEMPT-05/08/09): a BAT that looks correct can skip
from init straight to cleanup, run uninstall.py on a directory that
was never installed, and leave no Segment A record - and the BAT's
own static checks (test_bat_cmd_safety.py) cannot prevent a
control-flow failure of that kind. Python's control flow is explicit:
a stage that fails raises, the runner aborts, and the later stages
never run.

Stage state machine (in order; each stage writes a before/after
marker with an exit code to the log and to stage-markers.json):

    INIT       resolve %TEMP% to its long form, create the isolated
               dir %TEMP%\\agent-relay-e2e-<RUNID> and record\\,
               open the log. (Exit 11 if the isolated dir cannot
               be created.)
    PREFLIGHT  Chrome found (exit 12 if not); the test registry
               entry com.agentrelay.host.e2e must NOT exist yet
               (exit 13 if it does); the package EXE must exist
               (exit 11 if not).
    INSTALL    run the real install.py with the test host name;
               then verify the test registry entry exists
               (exit 15 if not). Sets install_completed = True
               only when this whole stage passes.
    MANIFEST   verify_manifest.py on the generated host manifest:
               exit 16 = content mismatch, exit 17 = file/parse
               error, exit 18 = unknown verifier exit code. Then
               record the production registry key after install and
               compare it with the before snapshot (exit 19 if it
               changed), and check the host EXE exists in the temp
               install (exit 20 if not).
    MKEXT      make_test_extension.py builds the test extension
               (exit 21 on failure).
    DRIVER     native_host_driver.py drives the real EXE through
               the protocol (Segment A; exit 22 on failure).
    B          launch the isolated Chrome for Testing, validate a
               run-bound Native Host startup receipt from the test
               extension, and record B1 through B5-B separately.
               Missing evidence prevents Segment B from passing.
    CLEANUP    always runs (try/finally), even when an earlier
               stage failed. If install_completed is True, run the
               real uninstall.py and verify the test key is gone
               and the production key is unchanged after uninstall.
               If install_completed is False, NEVER call
               uninstall.py (there is nothing installed to
               uninstall) - only verify nothing was left behind
               (test key absent, install dir absent) and report.
               The test extension dir is removed; the record dir
               and the isolated Chrome profile are kept.

Exit codes (distinct per failure point, so a log line pins the
stage that failed):
    0  success
    10 Python not found (reported by the thin BAT, not this file)
    11 package dir / EXE / isolated dir problem
    12 Chrome not found
    13 test registry entry already exists before install
    14 install.py failed
    15 test registry entry missing after install
    16 manifest content mismatch
    17 manifest file/parse error
    18 manifest verifier unknown exit code
    19 production registry key changed after install
    20 host EXE missing in the temp install
    21 make_test_extension.py failed
    22 Segment A driver failed
    23 Chrome launch failed
    24 cleanup failed (uninstall or post-cleanup verification)
    25 Segment B has no verified evidence
    26 unexpected stage exception
    27 extension identity check failed
    28 extension startup receipt timeout

The runner is testable on Linux: all Windows interaction (registry,
Chrome, subprocess, file removal) goes through an `ops` object.
Tests inject a fake ops and assert the stage machine's invariants:
a failed stage aborts, a later stage is never reached, cleanup
always runs, and uninstall is never called when install never
completed. The real Windows run is ATTEMPT-10.

Isolation (same rules as before, unchanged):
- Chrome uses an isolated --user-data-dir; the everyday profile,
  extensions and MCP config are untouched.
- The registry only ever gets the test host name
  com.agentrelay.host.e2e; the production key com.agentrelay.host
  is only ever READ (before / after install / after uninstall)
  and must be identical each time.
- Install goes to %TEMP%\\agent-relay-e2e-<RUNID>\\agent-relay-skill.
- The host EXE must be present; never fall back to .bat / .py.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from verify_manifest import long_path
except ImportError:  # pragma: no cover - verify_manifest is in HERE
    def long_path(path):
        return os.path.realpath(path)

TEST_HOST_NAME = "com.agentrelay.host.e2e"
PROD_HOST_NAME = "com.agentrelay.host"
EXTENSION_ID = "jeelmedmciafjnfdpnjgbgipplcddhka"
REG_ROOT = r"HKCU\Software\Google\Chrome\NativeMessagingHosts"

# Exit codes, distinct per failure point (see the module docstring).
EXIT_OK = 0
EXIT_ISOLATED_DIR = 11
EXIT_CHROME_NOT_FOUND = 12
EXIT_TEST_REG_EXISTS = 13
EXIT_INSTALL_FAILED = 14
EXIT_TEST_REG_MISSING = 15
EXIT_MANIFEST_CONTENT = 16
EXIT_MANIFEST_FILE = 17
EXIT_MANIFEST_UNKNOWN = 18
EXIT_PROD_REG_CHANGED = 19
EXIT_EXE_MISSING = 20
EXIT_MKEXT_FAILED = 21
EXIT_DRIVER_FAILED = 22
EXIT_CHROME_LAUNCH = 23
EXIT_CLEANUP_FAILED = 24
EXIT_B_PENDING = 25
EXIT_STAGE_EXCEPTION = 26
EXIT_B1_FAILED = 27
EXIT_B1_TIMEOUT = 28
B_STEPS = ("B1", "B2", "B3", "B4", "B5-A", "B5-B")

STAGES = ("INIT", "PREFLIGHT", "INSTALL", "MANIFEST", "MKEXT",
          "DRIVER", "B", "CLEANUP")


class StageFailed(Exception):
    """A stage failed. Carries the stage name and its exit code."""

    def __init__(self, stage, code, message):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message


class RealOps:
    """Windows interaction for the runner. Used on the real machine.

    Every method is a thin wrapper over a Windows facility so the
    stage machine itself stays testable: tests inject a fake ops
    object with the same methods.
    """

    def find_chrome(self):
        path = os.environ.get("AGENT_RELAY_CFT_EXE")
        if path and os.path.isabs(path) and os.path.isfile(path):
            return os.path.realpath(path)
        return None

    def probe_b1(self, skill_dir, run_id, process, timeout=20):
        outbox = os.path.join(skill_dir, "orchestrator", "state",
                              "native_host", "outbox.jsonl")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with open(outbox, "rb") as file:
                    lines = file.read().split(b"\n")[:-1]
            except FileNotFoundError:
                lines = []
            for line in lines:
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                envelope = record.get("envelope")
                if (isinstance(envelope, dict)
                        and record.get("direction") == "extension_to_coordinator"
                        and envelope.get("type") == "e2e_browser_ready"
                        and envelope.get("run_id") == run_id):
                    return {"extension_id": envelope.get("extension_id")}
            if process.poll() is not None:
                break
            time.sleep(0.2)
        return None

    def close_chrome(self, process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)

    def reg_query(self, key):
        """Run `reg query <key> /ve`; return (returncode, output)."""
        try:
            proc = subprocess.run(
                ["reg", "query", key, "/ve"],
                capture_output=True, text=True, errors="replace",
                timeout=30)
            return proc.returncode, proc.stdout + proc.stderr
        except FileNotFoundError:
            # No `reg` tool (not Windows): the key is not installed.
            return 1, "reg tool not available on this system"
        except subprocess.TimeoutExpired:
            return 1, "reg query timed out"

    def run(self, cmd, log_handle):
        """Run cmd, appending its stdout+stderr to log_handle.

        Returns the exit code. cmd is a list (never a shell string),
        so no CMD parsing is involved at all.
        """
        proc = subprocess.run(cmd, stdout=log_handle,
                              stderr=subprocess.STDOUT,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        return proc.returncode

    def launch_chrome(self, cmd):
        return subprocess.Popen(cmd)

    def wait_operator(self, prompt, process):
        if os.name == "nt" and sys.stdin.isatty():
            import msvcrt

            print(prompt, flush=True)
            while process.poll() is None:
                if msvcrt.kbhit():
                    key = msvcrt.getwch()
                    if key == chr(13):
                        return "operator"
                    if key in (chr(0), chr(224)):
                        msvcrt.getwch()
                time.sleep(0.2)
            return "browser_exited"
        try:
            input(prompt)
        except EOFError:
            return "stdin_eof"
        return "operator"

    def path_exists(self, path):
        return os.path.exists(path)

    def remove_dir(self, path):
        shutil.rmtree(path)

    def long_path(self, path):
        return long_path(path)


class FakeOps:
    """In-memory ops for unit tests. Records every call so a test
    can assert which stages ran and which were skipped.

    `results` maps a call key to the value to return:
      - "chrome": path or None (find_chrome)
      - "reg:<key>": (returncode, output) for reg_query
      - "run:<script name>": exit code for run()
    `run_log` collects the cmd lists passed to run() and
    launch_chrome(); `removed` collects remove_dir() calls;
    `waited` is True once wait_operator() was called.
    """

    def __init__(self, results=None):
        self.results = dict(results or {})
        self.run_log = []
        self.removed = []
        self.waited = False

    def find_chrome(self):
        return self.results.get(
            "chrome", r"C:\Program Files\Google\Chrome\Application"
                     r"\chrome.exe")

    def reg_query(self, key):
        return self.results.get("reg:" + key, (1, "not found"))

    def run(self, cmd, log_handle):
        self.run_log.append(list(cmd))
        script = os.path.basename(cmd[1]) if len(cmd) > 1 else ""
        return self.results.get("run:" + script, 0)

    def launch_chrome(self, cmd):
        self.run_log.append(["launch"] + list(cmd))
        return object()

    def probe_b1(self, skill_dir, run_id, process):
        return {"extension_id": EXTENSION_ID}

    def close_chrome(self, process):
        pass

    def wait_operator(self, prompt, process):
        self.waited = True
        return self.results.get('operator_outcome', 'operator')

    def path_exists(self, path):
        return self.results.get("exists:" + path, False)

    def remove_dir(self, path):
        self.removed.append(path)

    def long_path(self, path):
        return self.results.get("long:" + path, path)


class Runner:
    """The E2E stage machine. See the module docstring for the
    stage list, exit codes and isolation rules."""

    def __init__(self, pkg_dir, ops=None, temp_root=None,
                 run_id=None, now=None):
        self.pkg_dir = os.path.abspath(pkg_dir)
        self.ops = ops or RealOps()
        self.temp_root = temp_root or os.environ.get("TEMP", "")
        self.run_id = run_id or "%08d" % random.randint(
            10000000, 99999999)
        self.now = now or time.time
        self.install_completed = False
        self.exit_code = EXIT_OK
        self.markers = []
        self.active_stage = None
        self.base_dir = None
        self.record_dir = None
        self.skill_dir = None
        self.test_ext_dir = None
        self.chrome_profile = None
        self.log_handle = None
        self.browser_process = None

    # -- logging and markers -------------------------------------

    def _timestamp(self):
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(self.now()))

    def log(self, message):
        line = "[%s] %s" % (self._timestamp(), message)
        print(line, flush=True)
        if self.log_handle is not None:
            self.log_handle.write((line + "\n").encode(
                "utf-8", errors="replace"))
            self.log_handle.flush()

    def _marker(self, stage, event, code=None):
        entry = {"stage": stage, "event": event,
                 "exit_code": code, "time": self._timestamp()}
        self.markers.append(entry)
        if code is None:
            self.log("=== %s %s ===" % (stage, event))
        else:
            self.log("%s %s exit code: %d" % (stage, event, code))

    def _checkpoint(self):
        if self.log_handle is None:
            return
        path = os.path.join(self.record_dir, "stage-checkpoint.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"run_id": self.run_id, "active_stage": self.active_stage,
                       "markers": self.markers}, f, indent=2)
        os.replace(path + ".tmp", path)

    def _stage_start(self, stage):
        self.active_stage = stage
        self._marker(stage, "start")
        self._checkpoint()

    def _stage_end(self, stage, code=EXIT_OK):
        self.active_stage = None
        self._marker(stage, "end", code)
        self._checkpoint()

    def _write_markers(self):
        if self.record_dir is None or not os.path.isdir(self.record_dir):
            return
        path = os.path.join(self.record_dir, "stage-markers.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"run_id": self.run_id,
                       "install_completed": self.install_completed,
                       "exit_code": self.exit_code,
                       "markers": self.markers},
                      f, indent=2, ensure_ascii=False)

    # -- helpers -------------------------------------------------

    def _reg_key(self, host_name):
        return "%s\\%s" % (REG_ROOT, host_name)

    def _reg_snapshot(self, host_name, filename):
        """Query a registry key and write its output to record\\."""
        key = self._reg_key(host_name)
        code, output = self.ops.reg_query(key)
        path = os.path.join(self.record_dir, filename)
        with open(path, "w", encoding="utf-8",
                  errors="replace") as f:
            f.write(output)
        return code, output

    def _reg_snapshot_text(self, filename):
        path = os.path.join(self.record_dir, filename)
        with open(path, "r", encoding="utf-8",
                  errors="replace") as f:
            return f.read()

    def _script(self, name):
        return os.path.join(self.pkg_dir, name)

    # -- stages --------------------------------------------------

    def stage_init(self):
        self._stage_start("INIT")
        temp_long = self.ops.long_path(self.temp_root)
        base_dir = os.path.join(temp_long, "agent-relay-e2e-%s" % self.run_id)
        try:
            os.mkdir(base_dir)
        except OSError as exc:
            raise StageFailed("INIT", EXIT_ISOLATED_DIR,
                              "cannot create a fresh isolated directory") from exc
        self.base_dir = base_dir
        self.record_dir = os.path.join(self.base_dir, "record")
        self.skill_dir = os.path.join(self.base_dir, "agent-relay-skill")
        self.test_ext_dir = os.path.join(self.base_dir, "test-extension")
        self.chrome_profile = os.path.join(self.base_dir, "chrome-profile")
        try:
            os.makedirs(self.record_dir, exist_ok=True)
        except OSError as exc:
            self.exit_code = EXIT_ISOLATED_DIR
            print("[ERROR] cannot create isolated dir %s: %s"
                  % (self.record_dir, exc), flush=True)
            raise StageFailed("INIT", EXIT_ISOLATED_DIR, str(exc))
        log_path = os.path.join(self.record_dir, "e2e-run.log")
        self.log_handle = open(log_path, "ab")
        init_start = self.markers[-1]
        self.log_handle.write(("[%s] === INIT start ===\n" %
                               init_start["time"]).encode("utf-8"))
        self.log("E2E run id: %s" % self.run_id)
        self.log("Package: %s" % self.pkg_dir)
        self.log("Isolated dir: %s" % self.base_dir)
        self._stage_end("INIT")

    def stage_preflight(self):
        self._stage_start("PREFLIGHT")
        chrome = self.ops.find_chrome()
        if not chrome:
            raise StageFailed("PREFLIGHT", EXIT_CHROME_NOT_FOUND,
                              "set AGENT_RELAY_CFT_EXE to the approved Chrome for Testing executable")
        self.chrome = chrome
        self.log("Chrome: %s" % chrome)
        exe = os.path.join(self.pkg_dir, "transport",
                           "agent-relay-host.exe")
        if not os.path.isfile(exe):
            raise StageFailed("PREFLIGHT", EXIT_ISOLATED_DIR,
                              "host EXE missing: %s" % exe)
        self.log("Host EXE present: %s" % exe)
        test_key = self._reg_key(TEST_HOST_NAME)
        code, _ = self.ops.reg_query(test_key)
        if code == 0:
            raise StageFailed("PREFLIGHT", EXIT_TEST_REG_EXISTS,
                              "test registry entry already exists: "
                              "%s" % test_key)
        self.log("Test registry entry absent (clean state): %s"
                 % test_key)
        self._reg_snapshot(PROD_HOST_NAME, "prod-reg-before.txt")
        self.log("Production registry key recorded before install")
        self._stage_end("PREFLIGHT")

    def stage_install(self):
        self._stage_start("INSTALL")
        cmd = [sys.executable, self._script("install.py"),
               "--source", self.pkg_dir,
               "--dest", self.skill_dir,
               "--host-name", TEST_HOST_NAME,
               "--non-interactive"]
        code = self.ops.run(cmd, self.log_handle)
        if code != 0:
            raise StageFailed("INSTALL", EXIT_INSTALL_FAILED,
                              "install.py failed (exit %d)" % code)
        self.log("install.py OK")
        test_key = self._reg_key(TEST_HOST_NAME)
        code, _ = self.ops.reg_query(test_key)
        if code != 0:
            raise StageFailed("INSTALL", EXIT_TEST_REG_MISSING,
                              "test registry entry missing after "
                              "install: %s" % test_key)
        self.log("Test registry entry present.")
        self.install_completed = True
        self._stage_end("INSTALL")

    def stage_manifest(self):
        self._stage_start("MANIFEST")
        manifest = os.path.join(
            self.skill_dir, "transport", "extension",
            "com.agentrelay.host.json")
        exe = os.path.join(self.skill_dir, "transport",
                           "agent-relay-host.exe")
        cmd = [sys.executable,
               self._script(os.path.join("windows_e2e_test",
                                         "verify_manifest.py")),
               "--manifest", manifest,
               "--host-name", TEST_HOST_NAME,
               "--extension-id", EXTENSION_ID,
               "--exe-path", exe]
        code = self.ops.run(cmd, self.log_handle)
        if code == 1:
            raise StageFailed("MANIFEST", EXIT_MANIFEST_CONTENT,
                              "manifest content mismatch")
        if code == 2:
            raise StageFailed("MANIFEST", EXIT_MANIFEST_FILE,
                              "manifest file/parse error")
        if code != 0:
            raise StageFailed("MANIFEST", EXIT_MANIFEST_UNKNOWN,
                              "manifest verifier unknown exit code "
                              "%d" % code)
        self.log("Manifest stage exit code: 0")
        self._reg_snapshot(PROD_HOST_NAME, "prod-reg-after-install.txt")
        before = self._reg_snapshot_text("prod-reg-before.txt")
        after = self._reg_snapshot_text("prod-reg-after-install.txt")
        if before != after:
            raise StageFailed("MANIFEST", EXIT_PROD_REG_CHANGED,
                              "production registry key changed after "
                              "install")
        self.log("Production registry key unchanged after install.")
        if not self.ops.path_exists(exe):
            raise StageFailed("MANIFEST", EXIT_EXE_MISSING,
                              "host EXE missing in temp install: %s"
                              % exe)
        self.log("Host EXE present in temp install.")
        self._stage_end("MANIFEST")

    def stage_mkext(self):
        self._stage_start("MKEXT")
        cmd = [sys.executable,
               self._script(os.path.join("windows_e2e_test",
                                         "make_test_extension.py")),
               "--source", os.path.join(self.pkg_dir, "transport",
                                        "extension"),
               "--dest", self.test_ext_dir, "--run-id", self.run_id]
        code = self.ops.run(cmd, self.log_handle)
        if code != 0:
            raise StageFailed("MKEXT", EXIT_MKEXT_FAILED,
                              "make_test_extension.py failed (exit "
                              "%d)" % code)
        self.log("Test extension built: %s" % self.test_ext_dir)
        self._stage_end("MKEXT")

    def stage_driver(self):
        self._stage_start("DRIVER")
        record = os.path.join(self.record_dir, "e2e-record-driver.json")
        cmd = [sys.executable,
               self._script(os.path.join("windows_e2e_test",
                                         "native_host_driver.py")),
               "--exe", os.path.join(self.skill_dir, "transport",
                                     "agent-relay-host.exe"),
               "--record", record]
        code = self.ops.run(cmd, self.log_handle)
        if code != 0:
            raise StageFailed("DRIVER", EXIT_DRIVER_FAILED,
                              "native_host_driver.py failed (exit "
                              "%d)" % code)
        self.log("Driver exit code: 0 (0 = all protocol steps PASS)")
        self._stage_end("DRIVER")

    def stage_b(self):
        self._stage_start("B")
        steps = {step: {"status": "PENDING", "time": self._timestamp(),
                        "evidence": None} for step in B_STEPS}
        path = os.path.join(self.record_dir, "segment-b.json")
        try:
            cmd = [self.chrome, "--no-first-run", "--no-default-browser-check",
                   "--user-data-dir=%s" % self.chrome_profile,
                   "--load-extension=%s" % self.test_ext_dir]
            try:
                self.browser_process = self.ops.launch_chrome(cmd)
            except Exception as exc:
                steps["B1"]["status"] = "FAIL"
                raise StageFailed("B", EXIT_CHROME_LAUNCH,
                                  "Chrome for Testing launch failed") from exc
            evidence = self.ops.probe_b1(
                self.skill_dir, self.run_id, self.browser_process)
            if evidence is None:
                steps["B1"]["status"] = "TIMEOUT"
                raise StageFailed("B", EXIT_B1_TIMEOUT,
                                  "no live test extension receipt")
            steps["B1"]["evidence"] = evidence
            if evidence.get("extension_id") != EXTENSION_ID:
                steps["B1"]["status"] = "FAIL"
                raise StageFailed("B", EXIT_B1_FAILED,
                                  "test extension ID mismatch")
            steps["B1"]["status"] = "PASS"
            steps["B1"]["time"] = self._timestamp()
            self.log("B1 PASS: live extension and test Native Host verified")
            self.log("B2 PENDING: operator must sign in to the isolated browser "
                     "and collect real, sanitized DOM evidence before send tests.")
            self.log("Test install: %s" % self.skill_dir)
            outcome = self.ops.wait_operator(
                "Close the isolated browser or press Enter to clean up.",
                self.browser_process)
            self.log("B operator wait ended: %s" % outcome)
            raise StageFailed("B", EXIT_B_PENDING,
                              "B2 through B5 have no verified evidence")
        finally:
            steps["B1"]["time"] = self._timestamp()
            with open(path, "x", encoding="utf-8") as file:
                json.dump({"run_id": self.run_id, "segment_a": "PASS",
                           "steps": steps}, file, indent=2)

    def stage_cleanup(self):
        """Always runs (try/finally). Uninstall only if install
        actually completed; otherwise only verify nothing was left
        behind - never call uninstall.py on a directory that was
        never installed."""
        self._stage_start("CLEANUP")
        failed = False
        if self.browser_process is not None:
            try:
                self.ops.close_chrome(self.browser_process)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.log("[WARNING] isolated browser cleanup: %s" % type(exc).__name__)
                failed = True
        if self.base_dir is None:
            # INIT itself failed before any isolated dir existed:
            # there is nothing installed and nothing to verify.
            self.log("No isolated dir was created; nothing to clean.")
            self._stage_end("CLEANUP")
            return
        if self.install_completed:
            cmd = [sys.executable,
                   os.path.join(self.skill_dir, "uninstall.py"),
                   "--dest", self.skill_dir,
                   "--non-interactive"]
            code = self.ops.run(cmd, self.log_handle)
            if code != 0:
                self.log("[WARNING] uninstall.py failed (exit "
                         "code %d)" % code)
                failed = True
            else:
                self.log("uninstall.py OK")
            test_key = self._reg_key(TEST_HOST_NAME)
            code, _ = self.ops.reg_query(test_key)
            if code == 0:
                self.log("[WARNING] test registry entry still "
                         "present after uninstall: %s" % test_key)
                failed = True
            else:
                self.log("Test registry entry removed.")
            self._reg_snapshot(PROD_HOST_NAME,
                               "prod-reg-after-uninstall.txt")
            before = self._reg_snapshot_text("prod-reg-before.txt")
            after = self._reg_snapshot_text(
                "prod-reg-after-uninstall.txt")
            if before != after:
                self.log("[WARNING] production registry key changed "
                         "after uninstall")
                failed = True
            else:
                self.log("Production registry key unchanged after "
                         "uninstall.")
        else:
            # Install never completed: there is nothing to
            # uninstall. Calling uninstall.py here would be the
            # ATTEMPT-09 failure mode (uninstall on a non-existent
            # dir, exit 2, and a log that looks like cleanup ran).
            self.log("Install never completed; uninstall skipped "
                     "(nothing installed). Verifying nothing was "
                     "left behind:")
            test_key = self._reg_key(TEST_HOST_NAME)
            code, _ = self.ops.reg_query(test_key)
            if code == 0:
                self.log("[WARNING] test registry entry exists "
                         "although install never completed: %s"
                         % test_key)
                failed = True
            else:
                self.log("Test registry entry absent (nothing left).")
            skill = os.path.join(self.base_dir, "agent-relay-skill")
            if self.ops.path_exists(skill):
                self.log("[WARNING] temp install dir exists although "
                         "install never completed: %s" % skill)
                failed = True
            else:
                self.log("Temp install dir absent (nothing left).")
        if self.ops.path_exists(self.test_ext_dir):
            try:
                self.ops.remove_dir(self.test_ext_dir)
                self.log("Test extension dir removed.")
            except Exception as exc:  # noqa: BLE001 - cleanup must not crash
                self.log("[WARNING] could not remove test extension "
                         "dir: %s" % exc)
                failed = True
        self.log("done")
        self._stage_end("CLEANUP", EXIT_CLEANUP_FAILED if failed
                        else EXIT_OK)
        if failed:
            raise StageFailed("CLEANUP", EXIT_CLEANUP_FAILED,
                              "cleanup verification failed")

    # -- top level -----------------------------------------------

    def run(self):
        """Run the stage machine. Returns the exit code."""
        try:
            self.stage_init()
            self.stage_preflight()
            self.stage_install()
            self.stage_manifest()
            self.stage_mkext()
            self.stage_driver()
            self.stage_b()
        except (Exception, KeyboardInterrupt) as exc:
            self.exit_code = self._record_stage_failure(exc, EXIT_STAGE_EXCEPTION)
        finally:
            try:
                self.stage_cleanup()
            except (Exception, KeyboardInterrupt) as exc:
                cleanup_exit = self._record_stage_failure(exc, EXIT_CLEANUP_FAILED)
                if self.exit_code in (EXIT_OK, EXIT_B_PENDING):
                    self.exit_code = cleanup_exit
            finally:
                try:
                    self._write_markers()
                finally:
                    if self.log_handle is not None:
                        self.log_handle.close()
                        self.log_handle = None
        return self.exit_code


    def _record_stage_failure(self, exc, fallback_code):
        if isinstance(exc, StageFailed):
            stage, code, message = exc.stage, exc.code, exc.message
        else:
            stage = self.active_stage
            code = fallback_code
            message = type(exc).__name__
        if self.active_stage is not None:
            self._stage_end(self.active_stage, code)
        self.log("[ERROR] %s failed (exit %d): %s" % (stage, code, message))
        return code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("Usage: e2e_runner.py <package directory>", flush=True)
        return 11
    pkg_dir = argv[0]
    if not os.path.isdir(pkg_dir):
        print("[ERROR] package directory not found: %s" % pkg_dir,
              flush=True)
        return 11
    runner = Runner(pkg_dir)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
