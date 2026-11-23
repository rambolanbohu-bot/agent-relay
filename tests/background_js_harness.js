#!/usr/bin/env node
/**
 * Agent Relay Skill v1.0.0-rc4-hotfix4 — Node harness for
 * transport/extension/background.js (HOTFIX 4 P2-C +
 * GATE-SEAMLESS-CONTINUITY).
 *
 * Loads the REAL background.js with stubbed chrome globals and checks
 * the session-binding contract:
 *  - the first host command for a site binds the first tab of the
 *    query, and the result carries tab_id + tab_rebound:true;
 *  - a later host command for the same site reuses the BOUND tab
 *    even when a fresh query would return a different tab first
 *    (tab_rebound:false) — taking tabs[0] from every query would
 *    send the next round to the WRONG session when several tabs of
 *    the same site are open;
 *  - when the bound tab is gone, the next command re-binds to a
 *    live tab (tab_rebound:true);
 *  - a content-script message binds its sender tab for the site;
 *  - an explicit tab_id in a host command wins over the stored
 *    binding (verified to exist first) and becomes the new binding;
 *  - an explicit session_id binds independently per session;
 *  - the muse site binds independently from the chatgpt site;
 *  - no tab for the site returns no_tab_for_site.
 *
 * This is a simulation of the extension host, not real Chrome. It
 * proves the background script's own routing logic — not a real
 * browser. Real-Chrome end-to-end testing is still PENDING (see
 * docs/KNOWN-LIMITATIONS.md).
 *
 * Usage: node tests/background_js_harness.js
 * Prints one JSON object to stdout and exits 0 only if every check
 * passes. Run via tests/test_background_js.py.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

// --- stub chrome ------------------------------------------------------------
const logs = [];
let tabs = []; // {id, url} — the tabs a query returns, in order
const sentToTabs = []; // {tabId, msg} — chrome.tabs.sendMessage records
const hostMessages = []; // port.postMessage records (results to host)

let readinessFailures = 0;
let readyDocumentState = "complete";
let lastError = null; // chrome.runtime.lastError (set during a callback)
let portOnMessage = null; // the host -> background listener
let onMessageListener = null; // the content-script -> background listener

const portStub = {
  onMessage: { addListener(fn) { portOnMessage = fn; } },
  onDisconnect: { addListener() {} },
  postMessage(obj) { hostMessages.push(obj); },
};

const chromeStub = {
  runtime: {
    connectNative() { return portStub; },
    onMessage: { addListener(fn) { onMessageListener = fn; } },
    onStartup: { addListener() {} },
    onInstalled: { addListener() {} },
    get lastError() { return lastError; },
  },
  tabs: {
    query(queryInfo, cb) {
      const site = queryInfo.url.replace("https://", "").replace("/*", "");
      const found = tabs.filter((t) => {
        try { return new URL(t.url).hostname === site; } catch (e) { return false; }
      });
      lastError = null;
      cb(found);
    },
    get(tabId, cb) {
      const tab = tabs.find((t) => t.id === tabId);
      if (!tab) {
        lastError = { message: "No tab with id: " + tabId };
        cb(undefined);
        lastError = null;
        return;
      }
      lastError = null;
      cb(Object.assign({status: "complete"}, tab));
    },
    sendMessage(tabId, msg, cb) {
      sentToTabs.push({ tabId, msg });
      lastError = null;
      // The content script's reply: a minimal result so the
      // background forwards it to the host.
      if (msg.type === "ping") {
        if (readinessFailures > 0) {
          readinessFailures--;
          lastError = {message: "Receiving end does not exist"};
          cb();
          lastError = null;
          return;
        }
        cb({type: "pong", nonce: msg.nonce, origin: "https://chatgpt.com", document_ready_state: readyDocumentState});
        return;
      }
      if (cb) cb({ type: msg.type + "_result", nonce: msg.nonce || null, ok: true });
    },
  },
};

// --- load the real background script ---------------------------------------
const sandbox = {
  chrome: chromeStub,
  console: { log(...args) { logs.push(args.join(" ")); } },
  setTimeout, clearTimeout,
  URL,
};
vm.createContext(sandbox);
const bgPath = path.join(__dirname, "..", "transport", "extension",
                         "background.js");
const src = fs.readFileSync(bgPath, "utf-8");
vm.runInContext(src, sandbox, { filename: "background.js" });

if (typeof portOnMessage !== "function") {
  console.log(JSON.stringify({ all_pass: false, checks: [{
    name: "background_loads_and_connects", pass: false,
    detail: "port onMessage listener was never registered",
  }] }));
  process.exit(1);
}

// --- checks -----------------------------------------------------------------
const checks = [];
function check(name, cond, detail) {
  checks.push({ name, pass: !!cond, detail: detail || "" });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Simulate a host command arriving over Native Messaging. Returns the
// tabs it was sent to and the results posted back to the host.
async function hostCommand(msg, waitMs = 50) {
  hostMessages.length = 0;
  sentToTabs.length = 0;
  portOnMessage(msg);
  await sleep(waitMs); // let routing settle
  return { sent: sentToTabs.slice(), results: hostMessages.slice() };
}

async function main() {
  // 1. First command binds the first tab of the query.
  tabs = [
    { id: 101, url: "https://chatgpt.com/c/aaa" },
  ];
  let r = await hostCommand({ type: "send", site: "chatgpt",
                              nonce: "n-bg-1", text: "hi" });
  check("bg_first_command_binds_first_tab",
        r.sent.length === 1 && r.sent[0].tabId === 101,
        JSON.stringify(r.sent));
  check("bg_first_command_reports_fresh_bind",
        r.results.length === 1 && r.results[0].tab_id === 101 &&
        r.results[0].tab_rebound === true,
        JSON.stringify(r.results));

  // 2. A later command reuses the BOUND tab even when a fresh query
  // would return a different tab first.
  tabs = [
    { id: 102, url: "https://chatgpt.com/c/bbb" },
    { id: 101, url: "https://chatgpt.com/c/aaa" },
  ];
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-2", text: "hi again" });
  check("bg_second_command_reuses_bound_tab",
        r.sent.length === 1 && r.sent[0].tabId === 101,
        JSON.stringify(r.sent));
  check("bg_second_command_not_rebound",
        r.results.length === 1 && r.results[0].tab_id === 101 &&
        r.results[0].tab_rebound === false,
        JSON.stringify(r.results));

  // 3. The bound tab is gone: the next command re-binds to a live tab.
  tabs = [
    { id: 102, url: "https://chatgpt.com/c/bbb" },
    { id: 103, url: "https://chatgpt.com/c/ccc" },
  ];
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-3", text: "after close" });
  check("bg_gone_tab_requires_explicit_rebind",
        r.sent.length === 0 && r.results[0].error ===
          "bound_tab_missing_explicit_rebind_required",
        JSON.stringify(r));
  r = await hostCommand({ type: "send", site: "chatgpt", tab_id: 102,
                          nonce: "n-bg-3-explicit", text: "approved target" });
  check("bg_explicit_rebind_reported",
        r.sent.length === 1 && r.results[0].tab_rebound === true,
        JSON.stringify(r));

  // 4. A content-script message binds its sender tab for the site.
  hostMessages.length = 0;
  onMessageListener(
    { type: "health_result", nonce: "n-bg-4", ok: true },
    { origin: "https://chatgpt.com",
      tab: { id: 201, url: "https://chatgpt.com/c/ddd" } });
  await sleep(50);
  tabs = [
    { id: 102, url: "https://chatgpt.com/c/bbb" },
    { id: 201, url: "https://chatgpt.com/c/ddd" },
  ];
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-4b", text: "to bound tab" });
  check("bg_unsolicited_message_cannot_replace_binding",
        r.sent.length === 1 && r.sent[0].tabId === 102,
        JSON.stringify(r.sent));

  // 5. An explicit tab_id wins over the stored binding and becomes
  // the new binding.
  tabs = [
    { id: 201, url: "https://chatgpt.com/c/ddd" },
    { id: 202, url: "https://chatgpt.com/c/eee" },
  ];
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-5", text: "explicit",
                          tab_id: 202 });
  check("bg_explicit_tab_id_wins",
        r.sent.length === 1 && r.sent[0].tabId === 202,
        JSON.stringify(r.sent));
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-5b", text: "after explicit" });
  check("bg_explicit_tab_id_becomes_binding",
        r.sent.length === 1 && r.sent[0].tabId === 202,
        JSON.stringify(r.sent));

  // 6. An explicit session_id binds independently per session.
  tabs = [
    { id: 301, url: "https://chatgpt.com/c/fff" },
    { id: 302, url: "https://chatgpt.com/c/ggg" },
  ];
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-6a", text: "s1",
                          session_id: "proj-1", tab_id: 301 });
  check("bg_session_id_first_binds",
        r.sent.length === 1 && r.sent[0].tabId === 301,
        JSON.stringify(r.sent));
  tabs = [
    { id: 302, url: "https://chatgpt.com/c/ggg" },
    { id: 301, url: "https://chatgpt.com/c/fff" },
  ];
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-6b", text: "s1 again",
                          session_id: "proj-1" });
  check("bg_session_id_reuses_bound_tab",
        r.sent.length === 1 && r.sent[0].tabId === 301,
        JSON.stringify(r.sent));
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-6c", text: "s2",
                          session_id: "proj-2", tab_id: 302 });
  check("bg_other_session_binds_independently",
        r.sent.length === 1 && r.sent[0].tabId === 302,
        JSON.stringify(r.sent));

  // 7. The muse site binds independently from the chatgpt site.
  tabs = [
    { id: 401, url: "https://muse.ai/chat" },
    { id: 202, url: "https://chatgpt.com/c/eee" },
    { id: 101, url: "https://chatgpt.com/c/aaa" },
  ];
  r = await hostCommand({ type: "send", site: "muse",
                          nonce: "n-bg-7", text: "muse hi" });
  check("bg_muse_binds_independently",
        r.sent.length === 1 && r.sent[0].tabId === 401,
        JSON.stringify(r.sent));
  r = await hostCommand({ type: "send", site: "chatgpt",
                          nonce: "n-bg-7b", text: "chatgpt again" });
  check("bg_chatgpt_binding_unaffected_by_muse",
        r.sent.length === 1 && r.sent[0].tabId === 202,
        JSON.stringify(r.sent));

  r = await hostCommand({ type: "collect_dom", site: "chatgpt",
                          session_id: "ambiguous", nonce: "ambiguous" });
  check("bg_ambiguous_tab_set_blocks_dispatch",
        r.sent.length === 0 && r.results[0].error ===
          "ambiguous_site_tabs_explicit_binding_required", JSON.stringify(r));
  readinessFailures = 1;
  r = await hostCommand({ type: "collect_dom", site: "chatgpt",
                          nonce: "ready-test" }, 400);
  check("bg_readiness_wait_does_not_retry_collector",
        r.sent.map((entry) => entry.msg.type).join(",") === "ping,ping,collect_dom" &&
        r.results.length === 1, JSON.stringify(r));

  tabs.push({id: 901, url: "about:blank", pendingUrl: "https://chatgpt.com/",
    status: "complete"});
  r = await hostCommand({type: "ping", site: "chatgpt", tab_id: 901,
    session_id: "opaque", nonce: "opaque"});
  check("bg_pending_url_cannot_authorize_opaque_document",
    r.sent.length === 0 && r.results[0].readiness.committed_origin === "opaque" &&
    r.results[0].readiness.pending_navigation === true, JSON.stringify(r));

  readyDocumentState = "interactive";
  const completing = hostCommand({type: "collect_dom", site: "chatgpt",
    tab_id: 202, nonce: "actual-document"}, 420);
  setTimeout(() => { readyDocumentState = "complete"; }, 110);
  r = await completing;
  check("bg_waits_for_complete_content_document",
    r.sent.map((entry) => entry.msg.type).join(",") === "ping,ping,collect_dom" &&
    r.results[0].document_readiness_verified === true, JSON.stringify(r));

  const navigationTab = {id: 902, url: "https://chatgpt.com/c/fixture",
    pendingUrl: "https://chatgpt.com/c/fixture", status: "loading"};
  tabs.push(navigationTab);
  const waitsForNavigation = hostCommand({type: "collect_dom", site: "chatgpt",
    tab_id: 902, session_id: "same-document", nonce: "navigation"}, 420);
  const sentWhileNavigationPending = sentToTabs.length;
  setTimeout(() => {
    delete navigationTab.pendingUrl;
    navigationTab.status = "complete";
  }, 110);
  r = await waitsForNavigation;
  check("bg_pending_reload_waits_before_even_readiness_ping",
    sentWhileNavigationPending === 0 &&
    r.sent.map((entry) => entry.msg.type).join(",") === "ping,collect_dom" &&
    r.results[0].document_readiness_verified === true, JSON.stringify(r));

  navigationTab.status = "loading";
  navigationTab.pendingUrl = "https://chatgpt.com/c/different";
  const changesDocument = hostCommand({type: "collect_dom", site: "chatgpt",
    tab_id: 902, session_id: "same-document", nonce: "changed-document"}, 420);
  setTimeout(() => {
    navigationTab.url = navigationTab.pendingUrl;
    delete navigationTab.pendingUrl;
    navigationTab.status = "complete";
  }, 110);
  r = await changesDocument;
  check("bg_different_committed_document_aborts_without_collector",
    r.sent.length === 0 && r.results.length === 1 &&
    r.results[0].error === "bound_tab_changed", JSON.stringify(r));

  // 8. No tab for the site returns no_tab_for_site.
  tabs = [];
  r = await hostCommand({ type: "send", site: "muse", session_id: "empty",
                          nonce: "n-bg-8", text: "nobody" });
  check("bg_no_tab_returns_error",
        r.sent.length === 0 && r.results.length === 1 &&
        r.results[0].ok === false &&
        r.results[0].error === "no_tab_for_site:muse.ai",
        JSON.stringify(r.results));

  const allPass = checks.every((c) => c.pass);
  console.log(JSON.stringify({ all_pass: allPass, checks }, null, 2));
  process.exit(allPass ? 0 : 1);
}

main().catch((e) => {
  console.log(JSON.stringify({
    all_pass: false,
    checks: checks.concat([{ name: "harness_error", pass: false,
                             detail: String(e && e.stack || e) }]),
  }, null, 2));
  process.exit(1);
});
