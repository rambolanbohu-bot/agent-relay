#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4-hotfix — make_test_extension.py.

RC4-hotfix FIX 3 (P1): builds the TEST extension for the Windows E2E
test. The E2E test must never touch the production Native Messaging
host (com.agentrelay.host) or the production registry entry. This
script copies the real extension dir and replaces HOST_NAME in
background.js with the test host name (default
"com.agentrelay.host.e2e"), then verifies:

  - the replacement happened (exactly one occurrence of the new
    HOST_NAME value, and the production value no longer appears as
    the HOST_NAME value);
  - manifest.json is byte-identical to the source (so the extension
    ID stays jeelmedmciafjnfdpnjgbgipplcddhka — it is derived from
    the "key" field, which is NOT changed — and the .e2e host
    manifest's allowed_origins, which install.py generates from
    EXTENSION_ID.txt, still matches);
  - EXTENSION_ID.txt is unchanged and well-formed (32 chars a-p).

If the extension ID ever changes (new key), the installer
regenerates the host manifest from EXTENSION_ID.txt, so
allowed_origins always matches the ID of the extension being
installed — no hand-editing of the manifest is needed.

Usage:
    python make_test_extension.py --source <extension dir>
                                  --dest <test extension dir>
                                  [--host-name com.agentrelay.host.e2e]

Exit code 0 on success (prints a JSON report); 1 on any failure
(nothing is left half-built: the dest dir is removed on failure).
"""

import argparse
import hashlib
import json
import os
import shutil
import sys

PRODUCTION_HOST_NAME = "com.agentrelay.host"
DEFAULT_TEST_HOST_NAME = "com.agentrelay.host.e2e"


class TestExtensionError(Exception):
    pass


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _instrument_readonly_roundtrip(content):
    """Trace only diagnostic commands; never include message data or tab IDs."""
    hooks = {
        "function sendToTab(tabId, msg, rebound) {":
            '  e2eTrace("tab_dispatch", msg);',
        "chrome.tabs.sendMessage(tabId, msg, function (resp) {":
            '''      e2eTrace(chrome.runtime.lastError ? "tab_callback_error" :
        resp && resp.nonce === msg.nonce && resp.origin === "https://chatgpt.com" &&
        resp.type === (msg.type === "ping" ? "pong" : "collect_dom_result")
        ? "content_receipt" : "tab_callback_unverified", msg);''',
        "    port.postMessage(obj);":
            '''    e2eTrace("return_post_accepted", obj);''',
        '  var site = msg.site === "muse" ? "muse.ai" : "chatgpt.com";':
            None,
    }
    for anchor, statement in hooks.items():
        if content.count(anchor) != 1:
            raise TestExtensionError("Cannot install read-only round-trip tracing")
        if statement is None:
            content = content.replace(anchor, '  e2eTrace("background_received", msg);\n' + anchor)
        else:
            content = content.replace(anchor, anchor + "\n" + statement)
    readiness_hooks = {
        "  var readiness = describe(tab);": """
  var e2eInitial = readiness;
  var e2eStarted = performance.now();
  var e2ePolls = 0;
  var e2ePending = readiness.pending_navigation || readiness.tab_state === "loading";
  function traceReadiness(outcome, dispatchCount) {
    e2eTrace("readiness_terminal", msg, {
      initial_origin: e2eInitial.committed_origin,
      initial_tab_state: e2eInitial.tab_state,
      pending_navigation_seen: e2ePending,
      readiness_polls: Math.min(e2ePolls, 32),
      elapsed_wait_ms: Math.min(60000, Math.max(0, Math.round(performance.now() - e2eStarted))),
      final_dispatch_count: dispatchCount,
      outcome: outcome
    });
  }""",
        '    routingError(msg, "bound_tab_origin_mismatch", readiness);':
            '    traceReadiness("origin_rejected", 0);',
        '    routingError(msg, "content_script_not_ready", readiness);':
            '    traceReadiness("timeout", 0);',
        '    if (error) routingError(msg, error, readiness);':
            '    traceReadiness(error ? "bound_tab_changed" : "dispatch", error ? 0 : 1);',
        '    chrome.tabs.get(tab.id, function (current) {':
            '    e2ePolls++;',
        '      readiness = describe(current);':
            '      e2ePending = e2ePending || readiness.pending_navigation || readiness.tab_state === "loading";',
    }
    for anchor, statement in readiness_hooks.items():
        if content.count(anchor) != 1:
            raise TestExtensionError("Cannot install read-only readiness tracing")
        if anchor.lstrip().startswith(("routingError", "if (error)", "chrome.tabs.get")):
            content = content.replace(anchor, statement + "\n" + anchor)
        else:
            content = content.replace(anchor, anchor + "\n" + statement)
    return "var e2eTraceBudget = 40;\n" + content + r"""
function e2eTrace(stage, msg, readiness) {
  if (!msg || typeof msg.nonce !== "string" || !/^[a-f0-9]{16}$/.test(msg.nonce)) return;
  var kind = msg.type === "ping" || msg.type === "pong" || msg.type === "ping_result"
    ? "ping" : msg.type === "collect_dom" || msg.type === "collect_dom_result"
      ? "collect_dom" : null;
  if (!kind || !(e2eTraceBudget > 0)) return;
  e2eTraceBudget--;
  var ack = {type:"e2e_readonly_stage", stage:stage, operation:kind, time_ms:Date.now()};
  if (readiness) ack.readiness = readiness;
  console.info("[agent-relay-e2e]", ack);
  // probe_nonce is local transport correlation, deliberately separate from
  // nonce so the adapter cannot accept an intermediate ack as its result.
  if (port) {
    try { port.postMessage(Object.assign({probe_nonce: msg.nonce}, ack)); } catch (_) {}
  }
}
"""


def make_test_extension(source_dir, dest_dir,
                        host_name=DEFAULT_TEST_HOST_NAME, run_id=None):
    source_dir = os.path.abspath(source_dir)
    dest_dir = os.path.abspath(dest_dir)
    if not host_name.startswith("com.agentrelay.host."):
        raise TestExtensionError(
            f"测试 host 名必须是 com.agentrelay.host.*，不是 {host_name!r} "
            "（不能是正式的 com.agentrelay.host，也不能是别的域名）")
    if not os.path.isdir(source_dir):
        raise TestExtensionError(f"扩展源目录不存在：{source_dir}")
    background_src = os.path.join(source_dir, "background.js")
    manifest_src = os.path.join(source_dir, "manifest.json")
    ext_id_src = os.path.join(source_dir, "EXTENSION_ID.txt")
    for path in (background_src, manifest_src, ext_id_src):
        if not os.path.isfile(path):
            raise TestExtensionError(f"扩展源目录缺少文件：{path}")
    if os.path.abspath(source_dir) == os.path.abspath(dest_dir):
        raise TestExtensionError("源目录和目标目录不能是同一个")

    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    try:
        shutil.copytree(source_dir, dest_dir)
        # 1. Replace HOST_NAME in the copy only.
        background_dst = os.path.join(dest_dir, "background.js")
        with open(background_dst, "r", encoding="utf-8") as f:
            content = f.read()
        old_decl = f'var HOST_NAME = "{PRODUCTION_HOST_NAME}";'
        new_decl = f'var HOST_NAME = "{host_name}";'
        count = content.count(old_decl)
        if count != 1:
            raise TestExtensionError(
                f"background.js 里 HOST_NAME 声明出现 {count} 次，"
                f"期望正好 1 次（{old_decl!r}）")
        content = content.replace(old_decl, new_decl)
        if run_id is not None:
            anchor = '  log("native host connected");'
            if content.count(anchor) != 1:
                raise TestExtensionError("Cannot instrument the test host connection")
            beacon = (
                '  sendToHost({type:"e2e_browser_ready", run_id:' +
                json.dumps(run_id) + ', extension_id:chrome.runtime.id});'
            )
            content = content.replace(anchor, anchor + "\n" + beacon)
            content = _instrument_readonly_roundtrip(content)
        with open(background_dst, "w", encoding="utf-8") as f:
            f.write(content)
        # 2. Verify: the new value is there exactly once, the
        #    production value is gone as the HOST_NAME value, and
        #    manifest.json / EXTENSION_ID.txt are byte-identical.
        with open(background_dst, "r", encoding="utf-8") as f:
            after = f.read()
        if after.count(new_decl) != 1:
            raise TestExtensionError("替换后 HOST_NAME 声明不是正好 1 次")
        if old_decl in after:
            raise TestExtensionError("替换后仍残留正式 HOST_NAME 声明")
        manifest_unchanged = (
            _sha256_file(manifest_src)
            == _sha256_file(os.path.join(dest_dir, "manifest.json")))
        if not manifest_unchanged:
            raise TestExtensionError("manifest.json 被改动了（必须原样）")
        with open(ext_id_src, "r", encoding="ascii") as f:
            ext_id = f.read().strip()
        with open(os.path.join(dest_dir, "EXTENSION_ID.txt"),
                  "r", encoding="ascii") as f:
            ext_id_copy = f.read().strip()
        if ext_id != ext_id_copy:
            raise TestExtensionError("EXTENSION_ID.txt 被改动了（必须原样）")
        if len(ext_id) != 32 or not all("a" <= c <= "p" for c in ext_id):
            raise TestExtensionError(f"扩展 ID 格式不对：{ext_id!r}")
        with open(manifest_src, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if "key" not in manifest:
            raise TestExtensionError("manifest.json 缺少 key 字段")
    except TestExtensionError:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    except OSError as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise TestExtensionError(str(e))
    return {
        "source": source_dir,
        "dest": dest_dir,
        "host_name": host_name,
        "extension_id": ext_id,
        "manifest_unchanged": True,
        "extension_id_unchanged": True,
        "allowed_origin": f"chrome-extension://{ext_id}/",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the TEST extension (HOST_NAME = "
                    "com.agentrelay.host.e2e) for the Windows E2E test.")
    parser.add_argument("--source", required=True,
                        help="real extension dir "
                             "(transport/extension)")
    parser.add_argument("--dest", required=True,
                        help="test extension dir to create")
    parser.add_argument("--host-name", default=DEFAULT_TEST_HOST_NAME,
                        help="test host name "
                             "(default: com.agentrelay.host.e2e)")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    try:
        report = make_test_extension(args.source, args.dest,
                                     args.host_name, args.run_id)
    except TestExtensionError as e:
        print(f"make_test_extension: 失败：{e}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
