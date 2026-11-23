#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — automated test suite runner (run_tests.py).

Runs every test module in this directory (file_log, watchdog, locking,
approvals, relay client vs the local stub, native host round trip,
extension syntax, run.py smoke + two-mode split, local approval page
live server, installer/uninstaller with a fake registry, pre-delivery
package check) plus a py_compile check over all Python files in the
package. Prints the raw results and writes them to
tests/test-output-rc4.txt (full run) or
tests/test-output-rc4-batch-N.txt (one batch). The raw output is also
embedded in tests/TEST-RECORDS-v4.md (the human-readable test record).

RC4: the suite is split into batches (ChatGPT's independent re-run of
the 88-test RC3 suite timed out). Each batch finishes in a short time
and writes its own raw output. The full run still works with no
--batch flag.

Usage:
    python3 tests/run_tests.py [--output tests/test-output-rc4.txt]
    python3 tests/run_tests.py --batch 1   # batch 1 only
    python3 tests/run_tests.py --batch 2   # batch 2 only
    python3 tests/run_tests.py --batch 3   # batch 3 only
    python3 tests/run_tests.py --list-batches

Exit code: 0 only when every test in the selected scope passes.
"""

import argparse
import compileall
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

# Batches are balanced by runtime so each one finishes quickly on its
# own (an independent re-run of the whole suite timed out in RC3).
BATCHES = {
    "1": ["test_file_log", "test_watchdog", "test_locking",
          "test_relay_client"],
    "2": ["test_approvals", "test_local_page", "test_run"],
    "3": ["test_native_host", "test_extension_syntax", "test_install",
          "test_check_package", "test_adapter_nonce", "test_content_js",
          "test_background_js", "test_verify_manifest",
          "test_author_boundary",
          "test_e2e", "test_release_gate",
          # HOTFIX 5 (P1/P2): BAT CMD-parse safety + adapter
          # late-receipt reconciliation.
          "test_bat_cmd_safety", "test_adapter_late_receipt",
          # HOTFIX 6 (P1/B2/B3/B4): the Python E2E stage machine +
          # adapter collect_dom / diagnostics passthrough.
          "test_e2e_runner", "test_adapter_collect_dom"],
}
TEST_MODULES = [name for batch in BATCHES.values() for name in batch]


def compile_check():
    """py_compile every .py file in the package (excluding test outputs)."""
    ok = compileall.compile_dir(PKG, quiet=1, force=True)
    return bool(ok)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Relay RC4 test suite")
    parser.add_argument("--output", default=None,
                        help="raw output file (default: "
                             "test-output-rc4.txt, or "
                             "test-output-rc4-batch-N.txt with --batch)")
    parser.add_argument("--batch", default=None, choices=list(BATCHES),
                        help="run one batch only (1, 2 or 3)")
    parser.add_argument("--list-batches", action="store_true",
                        help="list the batches and exit")
    args = parser.parse_args(argv)

    if args.list_batches:
        for key in sorted(BATCHES):
            print(f"batch {key}: {', '.join(BATCHES[key])}")
        return 0

    if args.batch:
        modules = BATCHES[args.batch]
        scope = f"batch {args.batch} ({', '.join(modules)})"
        default_output = os.path.join(
            HERE, f"test-output-rc4-batch-{args.batch}.txt")
    else:
        modules = TEST_MODULES
        scope = "full suite"
        default_output = os.path.join(HERE, "test-output-rc4.txt")
    output = args.output or default_output

    buf = io.StringIO()
    buf.write("Agent Relay Skill v1.0.0-rc4 — automated test suite\n")
    buf.write("=" * 60 + "\n")
    buf.write(f"Scope: {scope}\n\n")

    buf.write("[1/2] py_compile all Python files in the package\n")
    compiled = compile_check()
    buf.write(f"py_compile: {'PASS' if compiled else 'FAIL'}\n\n")
    if not compiled:
        buf.write("ABORTED: Python files do not compile.\n")
        _finish(buf, output, ok=False)
        return 1

    buf.write("[2/2] unittest suite\n")
    sys.path.insert(0, HERE)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in modules:
        suite.addTests(loader.loadTestsFromName(name))
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)
    buf.write(stream.getvalue())
    buf.write("\n")
    buf.write(f"Tests run: {result.testsRun}, "
              f"failures: {len(result.failures)}, "
              f"errors: {len(result.errors)}, "
              f"skipped: {len(result.skipped)}\n")
    ok = result.wasSuccessful()
    buf.write(f"SUITE: {'PASS' if ok else 'FAIL'}\n")
    _finish(buf, output, ok=ok)
    return 0 if ok else 1


def _finish(buf, output_path, ok):
    text = buf.getvalue()
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(text, end="")
    print(f"\nRaw output written to: {output_path}")


if __name__ == "__main__":
    sys.exit(main())
