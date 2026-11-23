#!/usr/bin/env python3
"""RC4-hotfix7 P1 tests: thin BAT entry CMD-parse safety
(tests/test_bat_cmd_safety.py).

ATTEMPT-09 (2026-11-21): the Hotfix5 ASCII BAT STILL failed on the
real machine - it jumped from init straight to cleanup (exit 2),
install never ran, no Segment A driver JSON. The Hotfix5 safety
scan (block-message parens, "%~" in messages, distinct exit codes
10-21) only covers message lines and bracket depth; it cannot
prevent a control-flow failure of that kind. The BAT's own static
checks are structurally unable to prove the BAT runs its stages
in order.

Hotfix6 fixes the class, not just the lines: the BAT is now a THIN
ENTRY only - it finds Python, locates the package directory, and
calls windows_e2e_test/e2e_runner.py. All stage logic lives in
Python, whose control flow is explicit (a failed stage raises and
the run aborts; see tests/test_e2e_runner.py). The thin entry
itself is built so CMD cannot misparse it:

- NO bracket blocks at all: flow control uses GOTO jumps only.
  A GOTO jump cannot be confused with a block end, so the
  ATTEMPT-05/08/09 "skipped from init to cleanup" failure mode
  has no mechanism left in this file.
- NO :log subroutine (no `call :log`, no `:log` label).
- No ASCII parens in any echo / REM message line.
- No "%~" literal in any REM / echo message line (percent
  expansion runs on REM lines too). "%~" appears only in `set`
  commands, where it is a real parameter expansion (%~1, %~dp0).
- Pure ASCII, no BOM, LF line endings (the old UTF-8 no-BOM BAT
  was misparsed by cmd on a non-UTF-8 console in ATTEMPT-01-04).
- Only two failure exits of its own (10 = Python not found,
  11 = package dir / runner / EXE not found); the runner's exit
  code is passed through unchanged with `exit /b !ERRORLEVEL!`.

Hotfix7 (ChatGPT's new-conversation review, 2026-11-21): the
Hotfix6 thin entry carried one more CMD hazard the Hotfix6 scan
did not cover - it stored the launcher WITH its flag in one
variable (`set "PY=py -3"`) and invoked it QUOTED (`"!PY!"`).
CMD treats a quoted "py -3" as a SINGLE executable filename, so
the runner never starts on a machine where the py launcher is
present (the typical Windows Python install; the `python`
fallback has no space and would have worked, but `py` is checked
first). The launcher and its flag now live in separate variables
(PY / PYARGS) and the invocation is unquoted. The new tests catch
the whole hazard class: no quoted variable used as a command may
hold a value with a space in it, and the runner invocation must
parse to `py -3` (py branch) or plain `python` (fallback branch).

These tests scan the thin BAT statically (no Windows here) and
fail if any rule is violated. They run against the source BAT in
the package; the ASCII copy is byte-identical to it (verified
before delivery) because the entry is already pure ASCII.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
BAT = os.path.join(PKG, "windows_e2e_test", "run_e2e_test.bat")
# The ASCII copy lives next to the package dirs, not inside the
# package (it is a separate deliverable, regenerated from the BAT).
ASCII_BAT = os.path.join(
    os.path.dirname(os.path.dirname(PKG)), "e2e-ascii",
    "run_e2e_test_ascii.bat")

# The thin entry's own failure exits: 10 = Python not found,
# 11 = package dir / runner / EXE not found. The runner's exit
# code is passed through (exit /b !ERRORLEVEL!), not re-listed.
EXPECTED_EXIT_CODES = {10, 11}


def _scan_bat(path):
    """Scan the BAT for the thin-entry rules. Returns
    (problems, literal_exit_codes, final_depth)."""
    with open(path, "rb") as f:
        raw = f.read()
    problems = []
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("BAT has a UTF-8 BOM")
    if b"\r" in raw:
        problems.append("BAT has CR line endings")
    non_ascii = [b for b in raw if b >= 128]
    if non_ascii:
        problems.append(
            "BAT is not pure ASCII (%d non-ASCII bytes)"
            % len(non_ascii))
    lines = raw.decode("ascii", errors="replace").splitlines()
    exit_codes = []
    depth = 0
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("REM"):
            if "%~" in ln:
                problems.append(
                    "line %d: REM line contains '%%~': %s"
                    % (i, ln.strip()))
            if re.search(r"[()]", ln):
                problems.append(
                    "line %d: REM line contains an ASCII parenthesis: "
                    "%s" % (i, ln.strip()))
            continue
        if s == "":
            continue
        opens = (s.endswith("(") or s.endswith(") else (")
                 or " do (" in s)
        closes = s == ")" or s.startswith(") else")
        if opens:
            problems.append(
                "line %d: bracket block opened (the thin entry must "
                "use GOTO, not blocks): %s" % (i, ln.strip()))
            depth += 1
        if closes:
            problems.append(
                "line %d: bracket block closed: %s" % (i, ln.strip()))
            depth -= 1
        if depth < 0:
            problems.append("line %d: block depth went negative: %s"
                            % (i, ln.strip()))
            depth = 0
        if s.startswith("echo ") and re.search(r"[()]", ln):
            problems.append(
                "line %d: echo line contains an ASCII parenthesis: "
                "%s" % (i, ln.strip()))
        if s.startswith("echo ") and "%~" in ln:
            problems.append(
                "line %d: echo line contains '%%~': %s"
                % (i, ln.strip()))
        if "call :log" in s or s == ":log":
            problems.append(
                "line %d: the thin entry must not use the :log "
                "subroutine: %s" % (i, ln.strip()))
        m = re.search(r"exit /b (\d+)", s)
        if m:
            exit_codes.append(int(m.group(1)))
    return problems, exit_codes, depth


def _bat_assignments(path):
    """Collect `set "VAR=value"` assignments in file order.
    Returns a list of (line_no, var, value). Values are the literal
    text after `=`; a value may be empty (`set "PYARGS="`)."""
    assignments = []
    with open(path, "r", encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            m = re.match(
                r'\s*set\s+"([A-Za-z_][A-Za-z0-9_]*)=([^"]*)"\s*$',
                ln.rstrip("\n"))
            if m:
                assignments.append((i, m.group(1), m.group(2)))
    return assignments


def _quoted_variable_commands(path):
    """Find lines whose FIRST token is a quoted variable reference
    ("!VAR!" or "%VAR%") used as the command. Returns a list of
    (line_no, var, line). Labels, REM lines, set/if/echo/pause/
    exit/where lines are not invocations and are skipped."""
    found = []
    with open(path, "r", encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            s = ln.strip()
            if not s or s.upper().startswith("REM") or s.startswith(":"):
                continue
            m = re.match(
                r'^"(![A-Za-z_][A-Za-z0-9_]*!|%[A-Za-z_][A-Za-z0-9_]*%)"'
                r'(?:\s|$)', s)
            if m:
                var = m.group(1).strip("!%")
                found.append((i, var, s))
    return found


def _runner_invocation_line(path):
    """The line that actually calls e2e_runner.py (not the `if
    exist` checks, not REM, not the echo error message). There is
    exactly one."""
    hits = []
    with open(path, "r", encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            s = ln.strip()
            if "e2e_runner.py" not in s:
                continue
            if (s.upper().startswith("REM") or s.startswith("if ")
                    or s.startswith("echo ")):
                continue
            hits.append((i, s))
    assert len(hits) == 1, \
        "expected exactly one runner invocation line, found %s" % (hits,)
    return hits[0]


def _split_cmd_tokens(line):
    """Split a CMD line into tokens, keeping quoted strings whole
    (quotes stripped). Unquoted !VAR! / %VAR% stay as tokens."""
    tokens = []
    cur = ""
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch in " \t" and not in_quotes:
            if cur:
                tokens.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        tokens.append(cur)
    return tokens


def _resolve_tokens(tokens, values):
    """Resolve bare !VAR! / %VAR% tokens against an assignment
    dict. Tokens resolving to the empty string are dropped (that is
    how CMD treats an empty variable). Tokens that are not bare
    variables (e.g. "!PKG!\\windows_e2e_test\\e2e_runner.py") are
    left as-is; only the command and flag positions are asserted."""
    out = []
    for tok in tokens:
        m = re.fullmatch(r"!([A-Za-z_][A-Za-z0-9_]*)!", tok)
        if not m:
            m = re.fullmatch(r"%([A-Za-z_][A-Za-z0-9_]*)%", tok)
        if m:
            val = values.get(m.group(1), "")
            if val != "":
                out.append(val)
        else:
            out.append(tok)
    return out


class TestThinBatSafety(unittest.TestCase):
    def setUp(self):
        self.problems, self.exit_codes, self.depth = _scan_bat(BAT)

    def test_no_bracket_blocks(self):
        blocks = [p for p in self.problems if "bracket block" in p]
        self.assertEqual(blocks, [],
                         "bracket blocks in the thin entry "
                         "(ATTEMPT-09 P1): " + "; ".join(blocks))

    def test_no_log_subroutine(self):
        log = [p for p in self.problems if ":log" in p]
        self.assertEqual(log, [],
                         ":log subroutine in the thin entry: "
                         + "; ".join(log))

    def test_no_ascii_parens_in_message_lines(self):
        paren = [p for p in self.problems if "parenthesis" in p]
        self.assertEqual(paren, [],
                         "ASCII parens in message lines: "
                         + "; ".join(paren))

    def test_no_percent_tilde_in_message_lines(self):
        tilde = [p for p in self.problems if "'%~'" in p]
        self.assertEqual(tilde, [],
                         "'%~' in REM/echo lines: " + "; ".join(tilde))

    def test_pure_ascii_no_bom_no_cr(self):
        ascii_problems = [p for p in self.problems
                          if "ASCII" in p or "BOM" in p or "CR " in p]
        self.assertEqual(ascii_problems, [],
                         "; ".join(ascii_problems))

    def test_no_other_scan_problems(self):
        self.assertEqual(self.problems, [],
                         "BAT CMD-parse hazards: " + "; ".join(self.problems))

    def test_only_own_exit_codes_10_and_11(self):
        # The thin entry exits 10 (Python not found) or 11
        # (package/runner/EXE not found) itself; everything else is
        # the runner's exit code passed through. Exit 11 appears
        # twice by design - the runner-missing and EXE-missing
        # checks are the same failure class ("package dir problem").
        self.assertEqual(set(self.exit_codes), EXPECTED_EXIT_CODES,
                         "literal exit codes are %s, expected %s"
                         % (sorted(set(self.exit_codes)),
                            sorted(EXPECTED_EXIT_CODES)))
        self.assertIn(10, self.exit_codes)
        self.assertIn(11, self.exit_codes)

    def test_parameter_expansion_only_in_set_commands(self):
        with open(BAT, "r", encoding="utf-8") as f:
            bat = f.read()
        self.assertIn('set "PKG=%~1"', bat)
        self.assertIn('set "PKG=%~dp0"', bat)
        for line in bat.splitlines():
            if "%~" in line:
                self.assertTrue(line.strip().startswith("set "),
                                "%%~ outside a set command: %r" % line)

    def test_bat_delegates_to_the_python_runner(self):
        with open(BAT, "r", encoding="utf-8") as f:
            bat = f.read()
        self.assertIn("e2e_runner.py", bat)
        self.assertIn("windows_e2e_test\\e2e_runner.py", bat)
        self.assertIn('exit /b !ERRORLEVEL!', bat)
        # The runner gets the package dir as its argument.
        self.assertIn('"!PKG!"', bat)
        # Python is found via the launcher first, then python.exe.
        self.assertIn("where py", bat)
        self.assertIn("where python", bat)

    def test_no_quoted_variable_command_with_spaced_value(self):
        # HOTFIX 7 (ChatGPT's new-conversation review, 2026-11-21):
        # the Hotfix6 entry stored the launcher WITH its flag in
        # one variable (`set "PY=py -3"`) and invoked it QUOTED
        # (`"!PY!"`). CMD treats a quoted "py -3" as a SINGLE
        # executable filename, so the runner never starts. Any
        # quoted variable used as a command must hold a value with
        # no space in it.
        assignments = _bat_assignments(BAT)
        values = {}
        for _ln, var, value in assignments:
            values.setdefault(var, set()).add(value)
        bad = []
        for ln, var, text in _quoted_variable_commands(BAT):
            for value in sorted(values.get(var, set())):
                if " " in value:
                    bad.append(
                        "line %d: quoted command %r resolves to %r "
                        "(contains a space): %s"
                        % (ln, var, value, text))
        self.assertEqual(bad, [],
                         "quoted variable command with a spaced "
                         "value (CMD treats it as one executable "
                         "name): " + "; ".join(bad))

    def test_runner_invocation_py_branch_parses_to_py_minus_3(self):
        # The launcher and its flag live in separate variables.
        # With the FIRST (py) assignment set, the invocation must
        # parse to command `py` + argument `-3`.
        assignments = _bat_assignments(BAT)
        first = {}
        for _ln, var, value in assignments:
            if var not in first:
                first[var] = value
        self.assertEqual(first.get("PY"), "py",
                         "first PY assignment must be the bare "
                         "launcher `py`, got %r" % (first.get("PY"),))
        self.assertEqual(first.get("PYARGS"), "-3",
                         "first PYARGS assignment must be `-3`, got "
                         "%r" % (first.get("PYARGS"),))
        _ln, line = _runner_invocation_line(BAT)
        self.assertFalse(line.startswith('"'),
                         "the runner invocation must NOT quote the "
                         "launcher: %r" % line)
        resolved = _resolve_tokens(_split_cmd_tokens(line), first)
        self.assertGreaterEqual(len(resolved), 3)
        self.assertEqual(resolved[0], "py")
        self.assertEqual(resolved[1], "-3")
        self.assertIn("e2e_runner.py", resolved[2])

    def test_runner_invocation_python_fallback_is_plain_python(self):
        # With the LAST (python) assignment set, the invocation
        # must parse to plain `python` with no `-3` flag.
        assignments = _bat_assignments(BAT)
        last = {}
        for _ln, var, value in assignments:
            last[var] = value
        self.assertEqual(last.get("PY"), "python",
                         "last PY assignment must be `python`, got "
                         "%r" % (last.get("PY"),))
        self.assertEqual(last.get("PYARGS"), "",
                         "last PYARGS assignment must be empty, got "
                         "%r" % (last.get("PYARGS"),))
        _ln, line = _runner_invocation_line(BAT)
        resolved = _resolve_tokens(_split_cmd_tokens(line), last)
        self.assertGreaterEqual(len(resolved), 2)
        self.assertEqual(resolved[0], "python")
        self.assertNotIn("-3", resolved)
        self.assertIn("e2e_runner.py", resolved[1])

    def test_ascii_copy_is_byte_identical_to_the_thin_entry(self):
        with open(BAT, "rb") as f:
            source = f.read()
        source.decode("ascii")
        reference = os.environ.get("AGENT_RELAY_ASCII_REFERENCE", ASCII_BAT)
        if os.path.isfile(reference) or "AGENT_RELAY_ASCII_REFERENCE" in os.environ:
            with open(reference, "rb") as f:
                self.assertEqual(source, f.read(),
                                 "the ASCII copy drifted from the thin entry")


if __name__ == "__main__":
    unittest.main()
