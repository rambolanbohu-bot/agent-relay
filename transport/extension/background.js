/**
 * Agent Relay Browser Adapter — background service worker (v1.0.0-rc4-hotfix4).
 *
 * Routes messages between the content scripts (chatgpt.com / muse.ai tabs)
 * and the native host (transport/native_host.py) over Chrome Native
 * Messaging. It holds no credentials, reads no files, runs no system
 * commands, and cannot release an approval. It only forwards envelopes.
 *
 * HOTFIX 4 (P2-C + GATE-SEAMLESS-CONTINUITY): the tab a command is
 * routed to is BOUND to the discussion session. The old code took
 * tabs[0] from every query — if several tabs of the same site are
 * open, the next round could go to the WRONG session, and seamless
 * continuity fails even without new windows. Now each site (or an
 * explicit session_id when the coordinator sends one) keeps a fixed
 * tab binding; a command reuses the bound tab, verifies it still
 * exists, and only re-binds (to the first tab of a fresh query) when
 * the bound tab is gone. Content-script messages also bind their
 * sender tab, so the tab that actually talks becomes the bound tab.
 * Re-binding is logged and reported (the result carries the tab id
 * and whether it was a fresh bind), so a round that moved sessions
 * is visible in the records, never silent.
 *
 * LEAST PRIVILEGE (condition 1):
 * - Only permissions: nativeMessaging + tabs (tabs is needed for
 *   chrome.tabs.query() below; see manifest.json). RC3 added tabs.
 * - Site scope: chatgpt.com and muse.ai only — never <all_urls>.
 * - Content arriving from browser pages is untrusted data: forwarded as-is,
 *   never executed.
 *
 * CONNECTION / RECOVERY:
 * - Connects to the native host on startup. If the host disconnects, it
 *   retries with backoff (1s, 2s, 4s, 8s, 16s) up to 5 attempts, then
 *   reports disconnected and stops. No infinite restart loop.
 * - If the native host is not installed, every command returns a clear
 *   "native_host_not_connected" error so the coordinator can fall back to
 *   the browser-task mode (see transport/adapter.py) instead of hanging.
 */

"use strict";

var HOST_NAME = "com.agentrelay.host";
var MAX_RECONNECTS = 5;
var RECONNECT_BACKOFF_MS = [1000, 2000, 4000, 8000, 16000];

var port = null;
var reconnects = 0;
var reconnectTimer = null;

function log(msg) {
  // Service-worker console only; nothing sensitive is logged (no tokens,
  // no message content beyond length).
  console.log("[agent-relay-adapter] " + msg);
}

function connectHost() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (e) {
    port = null;
    scheduleReconnect("connect threw: " + e.message);
    return;
  }
  port.onMessage.addListener(onHostMessage);
  port.onDisconnect.addListener(function () {
    var err = chrome.runtime.lastError
      ? chrome.runtime.lastError.message
      : "unknown";
    log("native host disconnected: " + err);
    port = null;
    scheduleReconnect("host disconnected");
  });
  log("native host connected");
  reconnects = 0;
}

function scheduleReconnect(reason) {
  if (reconnectTimer) return;
  if (reconnects >= MAX_RECONNECTS) {
    log("giving up reconnecting after " + MAX_RECONNECTS +
        " attempts (" + reason + "); coordinator must fall back");
    return;
  }
  var delay = RECONNECT_BACKOFF_MS[Math.min(reconnects,
                                            RECONNECT_BACKOFF_MS.length - 1)];
  reconnects += 1;
  log("reconnect attempt " + reconnects + " in " + delay + "ms (" + reason + ")");
  reconnectTimer = setTimeout(function () {
    reconnectTimer = null;
    connectHost();
  }, delay);
}

function hostConnected() {
  return !!port;
}

// --- routing: native host -> content script ---------------------------------
// HOTFIX 4 (P2-C + GATE-SEAMLESS-CONTINUITY): the tab is BOUND to the
// discussion session. sessionTabs maps a session key — an explicit
// session_id from the coordinator when one is sent, otherwise the
// site — to a fixed tab id. A command reuses the bound tab (verified
// to still exist) and only re-binds to the first tab of a fresh
// query when the bound tab is gone. Taking tabs[0] from every query
// would send the next round to the WRONG session when several tabs
// of the same site are open. Re-binding is logged, and the result
// carries the tab id and whether it was a fresh bind, so a round
// that moved sessions is visible in the records, never silent.
var sessionTabs = {};

function sessionKey(msg, site) {
  if (msg && typeof msg.session_id === "string" && msg.session_id) {
    return msg.session_id;
  }
  return site;
}

function sendToTab(tabId, msg, rebound) {
  chrome.tabs.sendMessage(tabId, msg, function (resp) {
    if (chrome.runtime.lastError) {
      sendToHost({
        type: msg.type + "_result",
        nonce: msg.nonce || null,
        ok: false,
        error: "content_script_unreachable:" +
          chrome.runtime.lastError.message,
      });
      return;
    }
    if (resp) {
      // Tag the result with the tab it came from, so the coordinator
      // can check the round stayed in the bound session.
      resp.tab_id = tabId;
      resp.tab_rebound = !!rebound;
      if (isReadOnlyCommand(msg.type)) resp.document_readiness_verified = true;
      sendToHost(resp);
    }
  });
}

function isReadOnlyCommand(type) {
  return type === "ping" || type === "collect_dom" ||
    type === "read_latest" || type === "health" || type === "last_sent";
}

function routingError(msg, error, readiness) {
  log("routing: " + error);
  sendToHost({ type: msg.type + "_result", nonce: msg.nonce || null,
    ok: false, error: error, readiness: readiness || null });
}

function dispatchBoundTab(tab, msg, site, rebound) {
  var origin = "https://" + site;
  function originState(value) {
    if (typeof value !== "string" || !value) return "unavailable";
    try {
      var actual = new URL(value).origin;
      return actual === origin ? "match" : actual === "null" ? "opaque" : "mismatch";
    } catch (_) { return "unavailable"; }
  }
  function describe(current) {
    return {
      committed_origin: originState(current.url),
      pending_navigation: Boolean(current.pendingUrl),
      tab_state: current.status === "complete" ? "complete" :
        current.status === "loading" ? "loading" : "unknown"
    };
  }
  var readiness = describe(tab);
  if (readiness.committed_origin !== "match") {
    routingError(msg, "bound_tab_origin_mismatch", readiness);
    return;
  }
  if (!isReadOnlyCommand(msg.type)) {
    sendToTab(tab.id, msg, rebound);
    return;
  }

  var settled = false;
  var deadline = setTimeout(function () {
    if (settled) return;
    settled = true;
    routingError(msg, "content_script_not_ready", readiness);
  }, 6000);
  function finish(error) {
    if (settled) return;
    settled = true;
    clearTimeout(deadline);
    if (error) routingError(msg, error, readiness);
    else sendToTab(tab.id, msg, rebound);
  }
  function checkReady() {
    if (settled) return;
    chrome.tabs.get(tab.id, function (current) {
      if (settled) return;
      if (chrome.runtime.lastError || !current ||
          current.url !== tab.url || originState(current.url) !== "match") {
        finish("bound_tab_changed");
        return;
      }
      readiness = describe(current);
      if (readiness.tab_state !== "complete" || readiness.pending_navigation) {
        setTimeout(checkReady, 250);
        return;
      }
      // Only the readiness ping is polled. The requested command is
      // dispatched once after the bound tab proves it has a receiver.
      chrome.tabs.sendMessage(tab.id, { type: "ping", nonce: msg.nonce },
        function (reply) {
          if (settled) return;
          if (!chrome.runtime.lastError && reply && reply.type === "pong" &&
              reply.nonce === msg.nonce && reply.origin === origin &&
              reply.document_ready_state === "complete") finish();
          else setTimeout(checkReady, 250);
        });
    });
  }
  checkReady();
}

function routeToSession(msg, site) {
  var key = sessionKey(msg, site);
  // An explicit tab_id in the command (coordinator-directed) wins
  // over the stored binding; it is still verified to exist first.
  var explicit = msg && typeof msg.tab_id === "number" ? msg.tab_id : null;
  if (explicit !== null) {
    chrome.tabs.get(explicit, function (tab) {
      if (chrome.runtime.lastError || !tab) {
        routingError(msg, "bound_tab_missing_explicit_rebind_required");
        return;
      }
      var changed = sessionTabs[key] !== tab.id;
      sessionTabs[key] = tab.id;
      if (changed) log("explicit tab binding accepted");
      dispatchBoundTab(tab, msg, site, changed);
    });
    return;
  }
  var bound = sessionTabs[key];
  if (bound !== undefined && bound !== null) {
    chrome.tabs.get(bound, function (tab) {
      if (chrome.runtime.lastError || !tab) {
        routingError(msg, "bound_tab_missing_explicit_rebind_required");
        return;
      }
      dispatchBoundTab(tab, msg, site, false);
    });
    return;
  }
  bindFreshTab(msg, site, key);
}

function bindFreshTab(msg, site, key) {
  chrome.tabs.query({ url: "https://" + site + "/*" }, function (tabs) {
    if (!tabs || !tabs.length) {
      sendToHost({
        type: msg.type + "_result",
        nonce: msg.nonce || null,
        ok: false,
        error: "no_tab_for_site:" + site,
      });
      return;
    }
    if (tabs.length !== 1) {
      routingError(msg, "ambiguous_site_tabs_explicit_binding_required");
      return;
    }
    var tab = tabs[0];
    sessionTabs[key] = tab.id;
    log("unique matching tab bound");
    dispatchBoundTab(tab, msg, site, true);
  });
}

function onHostMessage(msg) {
  // msg is an envelope from the coordinator via the native host, e.g.
  // {type:"send", text:"...", nonce:"...", site:"chatgpt"}.
  if (!msg || typeof msg.type !== "string") return;
  var site = msg.site === "muse" ? "muse.ai" : "chatgpt.com";
  routeToSession(msg, site);
}

function sendToHost(obj) {
  if (!hostConnected()) {
    log("cannot forward to host: not connected");
    return;
  }
  try {
    port.postMessage(obj);
  } catch (e) {
    log("postMessage to host failed: " + e.message);
  }
}

// --- routing: content script -> native host ---------------------------------
// reply_complete / health / read / send results from content scripts.
chrome.runtime.onMessage.addListener(function (msg, sender) {
  if (!msg || typeof msg.type !== "string") return;
  // HOTFIX 4 (P2-C): a content script that talks is in the
  // discussion tab — bind it, so later host commands reuse this
  // tab instead of re-querying. The binding key is the sender's
  // site (or the session_id the content script was told, when one
  // was sent with the command it is answering).
  if (sender && sender.tab && typeof sender.tab.id === "number") {
    var site = sender.origin
      ? sender.origin.replace(/^https?:\/\//, "").split("/")[0]
      : null;
    if (site && sessionTabs[site] === undefined) sessionTabs[site] = sender.tab.id;
  }
  // Tag the envelope with the tab's origin so provenance is bound to the
  // page origin, not just a sender field (Security-2b).
  var envelope = Object.assign({}, msg, {
    tab_origin: sender && sender.origin ? sender.origin : null,
    tab_url_host: sender && sender.tab && sender.tab.url
      ? new URL(sender.tab.url).hostname
      : null,
  });
  sendToHost(envelope);
});

// --- lifecycle ----------------------------------------------------------------
chrome.runtime.onStartup.addListener(connectHost);
chrome.runtime.onInstalled.addListener(connectHost);
connectHost();
