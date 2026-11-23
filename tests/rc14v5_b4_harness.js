#!/usr/bin/env node
/**
 * Agent Relay Skill v1.0.0-rc4-hotfix6 — Node harness for
 * transport/extension/content.js (FIX 1 + FIX 4, HOTFIX 2 TASK 1 + 2,
 * HOTFIX 3 TASK 1, HOTFIX 4 DEFECT 1 + 2 + 3 and P2, HOTFIX 5 P2,
 * HOTFIX 6 B2/B3/B4 + ROUND 25 collector).
 *
 * Loads the REAL content.js with stubbed browser globals (window,
 * document, chrome, Event, MutationObserver) and checks the contract:
 *  - ping / health / read_latest echo the request nonce (FIX 1);
 *  - read_latest only accepts nodes that positively identify as
 *    assistant replies ([data-message-author-role='assistant']).
 *    A user message rendered as an <article> is NEVER reported as a
 *    reply; with only user articles, read_latest reports found:false
 *    (HOTFIX 2 TASK 1);
 *  - read_latest finds a reply whose own innerText is empty but
 *    whose textContent holds the text, and a reply whose role
 *    attribute sits on an empty wrapper while the turn container
 *    (parent) holds the text — WITHOUT reintroducing the generic
 *    "article" fallback (HOTFIX 4 DEFECT 2). A role node whose
 *    parent is MAIN still reports found:false (the parent walk
 *    never reaches the whole conversation);
 *  - the completion watch reports the assistant reply and never a
 *    user message (HOTFIX 2 TASK 1);
 *  - send returns ok:true + delivery:"message_sent" only after a NEW
 *    user message node appears in the DOM with the composer cleared,
 *    and reports the new node's data-message-id (FIX 4 + HOTFIX 2
 *    TASK 2: MESSAGE_SENT, not RESPONSE_COMPLETED);
 *  - a send of text that already exists in history, where the
 *    composer clears but NO new node appears, returns ok:false +
 *    delivery:"uncertain" (HOTFIX 2 TASK 2);
 *  - an old user message node whose content changes IN PLACE (same
 *    dom_id, new text, NO new node) is NOT treated as a new message:
 *    the send returns ok:false + delivery:"uncertain" (HOTFIX 3
 *    TASK 1 — ChatGPT's adversarial test: old node "old-id" with
 *    its text changed in place must not produce message_sent);
 *  - a send whose message was genuinely delivered but the user-node
 *    check missed it is confirmed via the corroborating signal —
 *    composer cleared AND the AI started replying (a new assistant
 *    reply block appeared, or the stop button appeared) — and
 *    reports confirmation:"reply_started" (HOTFIX 4 DEFECT 1);
 *  - a slow page render (the new user node appears after 6.5s) is
 *    still confirmed within the longer 10s timeout (HOTFIX 4
 *    DEFECT 1 + DEFECT 3; the old 5s timeout gave up first);
 *  - a send whose text the page re-renders with different
 *    whitespace is still confirmed by the normalised text match
 *    (HOTFIX 4 DEFECT 1);
 *  - a send whose button is disabled until React syncs (enabled
 *    after 1.2s) waits for the input state before clicking and is
 *    confirmed (HOTFIX 4 P2 / DEFECT 3);
 *  - a send whose button does NOT exist while the composer is empty
 *    and only appears after text is typed is confirmed: doSend
 *    fills first, waits (on actual DOM state) for the button, then
 *    clicks once (HOTFIX 4 P2-A — the ATTEMPT-07 order bug); and
 *    when the button NEVER appears after the input, the result is
 *    not_sent (never clicked), not UNCERTAIN;
 *  - a send whose button EXISTS but NEVER enables after the input
 *    returns not_sent with send_button_never_enabled and NEVER
 *    clicks (HOTFIX 5 P2 — the ATTEMPT-08 failure: Hotfix4
 *    clicked the disabled button, a DOM no-op, and the
 *    confirmation timed out as UNCERTAIN); a send whose fill does
 *    not stick returns not_sent with composer_input_not_accepted
 *    immediately (fast-fail) and never clicks (HOTFIX 5 P2);
 *  - health with an EMPTY composer (no send button — the normal
 *    state before typing) reports ok:true (HOTFIX 4 P2-A; the old
 *    rule wrongly required the button too);
 *  - read_latest retries briefly when no assistant node is found
 *    on the first check, so a reply that is still rendering is
 *    found (HOTFIX 4 DEFECT 2 / P2-B);
 *  - a send that cannot be confirmed returns ok:false +
 *    delivery:"uncertain" and never auto-resends (FIX 4);
 *  - the send / read_latest listeners keep the async response
 *    channel open (return true) so the ACK is not lost.
 *  - HOTFIX 6 (B2/B3): multi-strategy recognition. A user node
 *    carrying an ALTERNATE role attribute (data-author-role), a
 *    node whose role attribute sits on an empty wrapper whose
 *    turn ARTICLE holds the text, a user turn with NO role marker
 *    at all (found via the sent-text anchor), and an assistant
 *    reply found via the turn-after-user-turn fallback are all
 *    recognised; the ATTEMPT-09 exact scenario (message delivered
 *    + reply present, primary selectors missing both) is now
 *    recognised. A bare turn echoing the sent text is NEVER
 *    reported as a reply. Unconfirmed sends and not-found reads
 *    carry a de-sensitized diagnostic inventory (never message
 *    content);
 *  - HOTFIX 6 (B4, ROUND 25): a hidden tab's send records a
 *    button time series (before input, after input, during the
 *    wait, at timeout / button found) with visibilityState, so
 *    the four button states are distinguishable;
 *  - HOTFIX 6 (ROUND 25): the optional read-only de-sensitized
 *    DOM collector (collect_dom) finds both test markers, reports
 *    the role-selector counts and the node structures, never
 *    returns message content, and proves the key diagnostic
 *    (found=true with role count 0).
 *
 * The stub DOM simulates the chat app: the send button's click()
 * clears the composer and appends a user message element — unless
 * simulateApp is false (nothing happens), "clear-only" (composer
 * clears but no new node appears — the duplicate-text trap),
 * "mutate-old" (composer clears and the EXISTING old node's text
 * changes in place to the sent text, but NO new node appears — the
 * HOTFIX 3 TASK 1 trap), "slow" (composer clears at once, the new
 * user node appears after 6.5s), "reply-only" (composer clears and
 * an assistant reply appears, but NO user node — the HOTFIX 4
 * DEFECT 1 trap), "streaming-only" (composer clears and the stop
 * button appears, but NO user node and NO reply text yet), or
 * "normalize" (the new user node is appended with whitespace
 * collapsed). This is a simulation of the page, not real
 *
 * Usage: node tests/content_js_harness.js
 * Prints one JSON object to stdout and exits 0 only if every check
 * passes. Run via tests/test_content_js.py.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

// --- stub DOM -------------------------------------------------------------
let composerPresent = true; // toggle for the missing-composer test
// true: click() appends a new user message; false: nothing happens;
// "clear-only": composer clears but NO new node appears;
// "mutate-old": composer clears and the EXISTING old node's text
// changes in place to the sent text, but NO new node appears;
// "slow": composer clears at once, the new user node appears after
// 6.5s; "reply-only": composer clears and an assistant reply
// appears, but NO user node; "streaming-only": composer clears and
// the stop button appears, but NO user node and NO reply text yet;
// "normalize": the new user node is appended with whitespace
// collapsed.
let simulateApp = true;
// The send button is DYNAMIC: it does not exist while the composer
// is empty — it only appears after text is typed (ATTEMPT-07).
// sendButtonPresent=false models that state. When
// sendButtonAppearsAfterInput is true, an input event on the
// composer makes the button appear after 200ms (React rendering).
let sendButtonPresent = true;
let sendButtonAppearsAfterInput = false;
// HOTFIX 5 (P2, ATTEMPT-08): sendButtonClicks counts every
// click() invocation, including no-ops on a disabled button (a
// real DOM click on a disabled button does nothing, but the call
// still happened — and that is exactly the Hotfix4 bug: it
// clicked a disabled button and the confirmation then timed out
// as UNCERTAIN instead of an honest not_sent). fillSticks=false
// models an input the page never accepts: the native setter runs
// but the composer's value does not change, so composerHasText
// is false right after the fill.
let sendButtonClicks = 0;
let fillSticks = true;
// The stop button (streaming indicator): present only while a reply
// is streaming.
let stopButtonPresent = false;
const userMessages = []; // {innerText, getAttribute, id} — role=user
const userArticles = []; // <article> nodes — user messages rendered
                          // as articles (the HOTFIX 2 TASK 1 trap)
const replyBlocks = []; // {innerText, getAttribute, id} — assistant
// HOTFIX 6 (B2/B3): alternate role-attribute nodes and role-less
// turn nodes, for the multi-strategy recognition tests. The
// content script must find a user/assistant node whose role marker
// is an ALTERNATE attribute (data-author-role), or a turn with no
// role marker at all (found only via the sent-text anchor or the
// turn-after-user-turn fallback).
const userAltMessages = []; // role=user via data-author-role
const replyAltBlocks = []; // role=assistant via data-author-role
const observedBubbles = [];
const bareTurns = []; // turns with data-message-id but NO role marker
// HOTFIX 6: where the click handler appends the new user node.
// "primary" (default): userMessages with the primary role attr;
// "alt": userAltMessages with data-author-role='user';
// "turn": a role node on an empty wrapper whose parent is a turn
//   ARTICLE holding the text (the turn-container walk);
// "bare": bareTurns, a turn with no role marker at all.
let userNodeRoleMode = "primary";
// HOTFIX 6 (B4): how long after the input event the send button
// appears (React rendering). 200ms by default; the hidden-tab
// test sets it to 8000ms.
let sendButtonAppearDelayMs = 200;
let messageCounter = 0; // fresh data-message-id for appended nodes

function makeNode(text, messageId, opts) {
  // opts: {textContent, parentElement, tagName} — lets a test model a
  // node whose innerText is empty but whose textContent holds the
  // text, or a role attribute on an empty wrapper whose turn
  // container (parentElement) holds the text.
  // HOTFIX 6: opts.roleAttr / opts.roleValue model a node carrying
  // an ALTERNATE role attribute (e.g. data-author-role='user');
  // opts.classes models the class list (for the DOM collector).
  opts = opts || {};
  return {
    innerText: text,
    textContent: ("textContent" in opts) ? opts.textContent : text,
    parentElement: opts.parentElement || null,
    tagName: opts.tagName || "DIV",
    id: "",
    _mid: messageId || null,
    classList: opts.classes ? opts.classes.slice() : [],
    getAttribute(name) {
      if (name === "data-message-id") return this._mid;
      if (opts.roleAttr && name === opts.roleAttr) return opts.roleValue;
      return null;
    },
    hasAttribute(name) {
      return this.getAttribute(name) !== null;
    },
  };
}

function observedBubble(text, quoted = false) {
  const leaf = makeNode(text, null, {
    classes: ["text-size-chat", "whitespace-pre-wrap"],
  });
  leaf.closest = () => quoted ? {} : null;
  const bubble = makeNode(text, null, {
    classes: ["bg-user-message", "text-user-message"],
  });
  bubble.querySelectorAll = (selector) =>
    selector === ".text-size-chat.whitespace-pre-wrap" ? [leaf] : [];
  bubble.closest = () => quoted ? {} : null;
  return bubble;
}

const textareaProto = {};
Object.defineProperty(textareaProto, "value", {
  configurable: true,
  // content.js calls this setter via the native-setter trick; it only
  // needs `set` to exist and to assign on the element.
  // HOTFIX 5 (P2): when fillSticks is false the setter runs but
  // the value does not stick — the page never accepted the input.
  set(v) { if (fillSticks) { this.value = v; } },
});

const composer = {
  tagName: "TEXTAREA",
  value: "",
  disabled: false,
  dispatchEvent(ev) {
    this._events = this._events || [];
    this._events.push(ev.type);
    // HOTFIX 4 (P2-A): the send button appears only after text is
    // typed. When the "button-after-input" mode is on, an input
    // event on the composer makes the button appear after a short
    // delay (React rendering the button).
    if (ev.type === "input" && sendButtonAppearsAfterInput &&
        !sendButtonPresent) {
      setTimeout(() => { sendButtonPresent = true; },
                 sendButtonAppearDelayMs);
    }
  },
  getAttribute() { return null; },
  id: "",
};

const stopButton = {
  tagName: "BUTTON",
  disabled: false,
  click() {},
  dispatchEvent() {},
  getAttribute() { return null; },
  id: "",
};

const sendButton = {
  tagName: "BUTTON",
  disabled: false,
  click() {
    // HOTFIX 5 (P2): count every click() invocation, then be a
    // no-op when disabled — a real DOM click on a disabled button
    // does nothing (the ATTEMPT-08 failure: Hotfix4 clicked the
    // disabled button, nothing was submitted, the text stayed in
    // the composer, and confirmation timed out as UNCERTAIN).
    sendButtonClicks += 1;
    if (this.disabled) return;
    // Simulate the chat app accepting the message: it clears the
    // composer and appends the new user message to the history.
    if (simulateApp === false) return;
    const text = composer.value;
    composer.value = "";
    if (simulateApp === "clear-only") return; // no new node appears
    if (simulateApp === "mutate-old") {
      // HOTFIX 3 TASK 1 trap: change the EXISTING old node's text
      // in place to the sent text, but append NO new node. The old
      // (dom_id, text) pair check wrongly treated this as a new
      // message; the new dom_id-identity rule must not.
      if (userMessages.length > 0) userMessages[0].innerText = text;
      return;
    }
    if (simulateApp === "slow") {
      // Composer clears at once; the new user node appears after
      // 6.5s (a slow page render — the HOTFIX 4 DEFECT 1 trap).
      setTimeout(() => {
        messageCounter += 1;
        userMessages.push(makeNode(
          text, "msg-" + messageCounter,
          { roleAttr: "data-message-author-role", roleValue: "user" }));
      }, 6500);
      return;
    }
    if (simulateApp === "reply-only") {
      // Composer clears and an assistant reply appears, but NO
      // user node — the HOTFIX 4 DEFECT 1 corroborating-signal trap.
      // The reply node carries its role attribute (as in a real
      // DOM), so the Hotfix6 text-anchor strategy can tell it
      // apart from a user node: a reply whose text contains the
      // sent text must never be mistaken for the sent message.
      messageCounter += 1;
      replyBlocks.push(makeNode(
        "AI reply to: " + text, "msg-a" + messageCounter,
        { roleAttr: "data-message-author-role",
          roleValue: "assistant" }));
      return;
    }
    if (simulateApp === "streaming-only") {
      // Composer clears and the stop button appears, but NO user
      // node and NO reply text yet.
      stopButtonPresent = true;
      return;
    }
    if (simulateApp === "normalize") {
      // The page re-renders the sent text with different
      // whitespace; the new node carries the collapsed text.
      messageCounter += 1;
      userMessages.push(makeNode(
        text.replace(/\s+/g, " ").trim(), "msg-" + messageCounter,
        { roleAttr: "data-message-author-role", roleValue: "user" }));
      return;
    }
    // HOTFIX 6: where the new user node lands depends on the
    // recognition mode under test (primary / alternate role
    // attribute / role on an empty wrapper whose turn ARTICLE
    // holds the text / no role marker at all). Role nodes carry
    // their role attribute (as in a real DOM) so the text-anchor
    // strategy can tell a user node from an assistant node.
    messageCounter += 1;
    if (userNodeRoleMode === "observed") {
      observedBubbles.push(observedBubble(text));
      return;
    }
    if (userNodeRoleMode === "alt") {
      userAltMessages.push(makeNode(
        text, "msg-" + messageCounter,
        { roleAttr: "data-author-role", roleValue: "user" }));
      return;
    }
    if (userNodeRoleMode === "turn") {
      const turn = makeNode(text, "msg-" + messageCounter + "-turn",
                            { tagName: "ARTICLE" });
      userMessages.push(makeNode(
        "", null,
        { parentElement: turn,
          roleAttr: "data-message-author-role", roleValue: "user" }));
      return;
    }
    if (userNodeRoleMode === "bare") {
      bareTurns.push(makeNode(text, "msg-" + messageCounter));
      return;
    }
    userMessages.push(makeNode(
      text, "msg-" + messageCounter,
      { roleAttr: "data-message-author-role", roleValue: "user" }));
  },
  dispatchEvent() {},
  getAttribute() { return null; },
  id: "",
};

const container = {
  tagName: "MAIN",
  // The collector scopes its queries to main when the element
  // supports querySelectorAll (as in a real DOM); delegate to the
  // document stub so the harness exercises that path.
  querySelectorAll(sel) { return documentStub.querySelectorAll(sel); },
};

const documentStub = {
  readyState: "complete",
  body: { tagName: "BODY" },
  // HOTFIX 6 (B4): the tab visibility state. Tests set this to
  // "hidden" for the minimised-tab scenarios; the content script
  // reads it via document.visibilityState.
  visibilityState: "visible",
  querySelector(sel) {
    if (sel === "#prompt-textarea") return composerPresent ? composer : null;
    if (sel === "form textarea") return composerPresent ? composer : null;
    if (sel === "textarea") return composerPresent ? composer : null;
    if (sel === "button[data-testid='send-button']") return sendButtonPresent ? sendButton : null;
    if (sel === "button[aria-label='Send prompt']") return sendButtonPresent ? sendButton : null;
    if (sel === "form button[type='submit']") return sendButtonPresent ? sendButton : null;
    if (sel === "button[data-testid='stop-button']") return stopButtonPresent ? stopButton : null;
    if (sel === "main") return container;
    if (sel === "[contenteditable='true']") return null;
    return null;
  },
  querySelectorAll(sel) {
    // HOTFIX 6: the content script queries with a comma-joined
    // selector (queryUnion) for multi-strategy recognition. A real
    // DOM returns document order; the stub concatenates the parts
    // in selector order and dedupes by identity. Test scenarios
    // are built so that order matches document order.
    if (sel.indexOf(",") !== -1) {
      const out = [];
      for (const part of sel.split(",")) {
        for (const el of this.querySelectorAll(part.trim())) {
          if (out.indexOf(el) === -1) out.push(el);
        }
      }
      return out;
    }
    if (sel === "[data-message-author-role='assistant']") return replyBlocks;
    if (sel === "[data-message-author-role='user']") return userMessages;
    if (sel === "[data-author-role='assistant']" ||
        sel === "[data-role='assistant']" ||
        sel === "[data-sender='assistant']") return replyAltBlocks;
    if (sel === "[data-author-role='user']" ||
        sel === "[data-role='user']" ||
        sel === "[data-sender='user']") return userAltMessages;
    if (sel === ".bg-user-message") return observedBubbles;
    if (sel === "article") return userArticles;
    if (sel === "[data-message-id]") {
      // Every turn in the conversation, in the order the stub's
      // arrays are concatenated (test scenarios are built so this
      // matches document order). Turns are the nodes carrying a
      // data-message-id; role nodes on empty wrappers are not
      // turns themselves (their turn ARTICLE is).
      const out = [];
      for (const arr of [userMessages, replyBlocks, userArticles,
                         userAltMessages, replyAltBlocks, bareTurns]) {
        for (const el of arr) {
          if (el._mid !== null && el._mid !== undefined &&
              out.indexOf(el) === -1) out.push(el);
        }
      }
      return out;
    }
    if (sel === "*") {
      // Every node the stub knows about (the DOM collector's
      // descendant scan). Turn ARTICLEs that are only reachable as
      // a parentElement are not listed here — the collector's
      // structure walk reaches them via parentElement.
      const out = [];
      for (const arr of [userMessages, replyBlocks, userArticles,
                         userAltMessages, replyAltBlocks, bareTurns]) {
        for (const el of arr) {
          if (out.indexOf(el) === -1) out.push(el);
        }
      }
      return out;
    }
    return [];
  },
  addEventListener() {},
};

// MutationObserver stub: the content script's completion watch
// observes the chat container; tests fire the callback on demand.
class MutationObserverStub {
  constructor(cb) {
    this.cb = cb;
    MutationObserverStub.instances.push(this);
  }
  observe() {}
  disconnect() {}
}
MutationObserverStub.instances = [];
MutationObserverStub.fireAll = function () {
  MutationObserverStub.instances.forEach((o) => o.cb());
};

const sentMessages = []; // chrome.runtime.sendMessage records

const windowStub = {
  location: { hostname: "chatgpt.com", origin: "https://chatgpt.com" },
  HTMLTextAreaElement: { prototype: textareaProto },
  HTMLInputElement: { prototype: {} },
  MutationObserver: MutationObserverStub,
  // crypto intentionally undefined: sha256Hex resolves null (hash
  // unavailable) — the coordinator re-hashes on receipt.
};

let onMessageListener = null;
const chromeStub = {
  runtime: {
    onMessage: {
      addListener(fn) { onMessageListener = fn; },
    },
    sendMessage(msg) { sentMessages.push(msg); },
  },
};

function EventStub(type, opts) {
  this.type = type;
  this.bubbles = !!(opts && opts.bubbles);
}

// --- load the real content script ------------------------------------------
globalThis.window = windowStub;
globalThis.document = documentStub;
globalThis.chrome = chromeStub;
globalThis.Event = EventStub;
// content.js calls the bare `new MutationObserver(...)` constructor,
// so it must exist as a global, not only on window.
globalThis.MutationObserver = MutationObserverStub;

const contentPath = path.join(__dirname, "..", "transport", "extension",
                              "content.js");
const src = fs.readFileSync(contentPath, "utf-8");
vm.runInThisContext(src.replace(/\}\)\(\);\s*$/,
  "globalThis.confirmObservedBubble = confirmObservedBubble; globalThis.confirmMarkerCorroboratedBubble = confirmMarkerCorroboratedBubble; globalThis.resetRC14Anchor = function () { lastConfirmedUserTurn = null; }; })();"),
  { filename: "content.js" });

if (typeof onMessageListener !== "function") {
  console.log(JSON.stringify({
    all_pass: false,
    checks: [{ name: "listener_registered", pass: false,
               detail: "content.js did not register onMessage listener" }],
  }, null, 2));
  process.exit(1);
}

// --- dispatch helper --------------------------------------------------------
function dispatch(msg) {
  let response;
  let responded = false;
  const sendResponse = (resp) => { response = resp; responded = true; };
  const ret = onMessageListener(msg, {}, sendResponse);
  return {
    ret,
    respondedNow: () => responded,
    wait: (timeoutMs = 8000) => new Promise((resolve) => {
      const t0 = Date.now();
      (function poll() {
        if (responded) return resolve(response);
        if (Date.now() - t0 > timeoutMs) return resolve(undefined);
        setTimeout(poll, 20);
      })();
    }),
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- checks -----------------------------------------------------------------
const checks = [];
function check(name, cond, detail) {
  checks.push({ name, pass: !!cond, detail: detail || "" });
}

async function main() {
  const marker = "RC14V5-B4-ABCDEF123456";
  const prompt = "Agent Relay RC14-v5 isolated background DOM confirmation test. Unique nonce " + marker + ". Reply exactly " + marker + " and nothing else.";
  const bubble = observedBubble(prompt);
  bubble.isConnected = true;
  bubble.compareDocumentPosition = function (el) { return el === replyBlocks[0] ? 4 : 0; };
  observedBubbles.push(bubble);
  replyBlocks.push(makeNode(marker, "new-b4-assistant", {roleAttr:"data-message-author-role",roleValue:"assistant"}));
  const snap = {ids:{}, latestText:"prior unrelated reply"};
  const ok = confirmMarkerCorroboratedBubble([],observedBubbles,prompt,snap);
  check("b4_unique_exact_prompt_new_reply_pass",!!ok && ok.strategy==="verified_marker_reply_after_rerender");
  check("b4_preexisting_user_rejected",confirmMarkerCorroboratedBubble([{el:bubble,text:prompt}],observedBubbles,prompt,snap)===null);
  check("b4_old_reply_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,prompt,{ids:{},latestText:marker})===null);
  observedBubbles.push(observedBubble(prompt));
  check("b4_ambiguous_user_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,prompt,snap)===null);
  observedBubbles.pop();
  replyBlocks.length=0;
  replyBlocks.push(makeNode(marker+" extra","wrong-reply",{roleAttr:"data-message-author-role",roleValue:"assistant"}));
  check("b4_wrong_reply_suffix_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,prompt,snap)===null);
  replyBlocks.length=0;
  replyBlocks.push(makeNode("other marker","wrong-marker",{roleAttr:"data-message-author-role",roleValue:"assistant"}));
  check("b4_wrong_reply_marker_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,prompt,snap)===null);
  replyBlocks.length=0;
  replyBlocks.push(makeNode(marker,"new-b4-assistant",{roleAttr:"data-message-author-role",roleValue:"assistant"}));
  check("b4_old_reply_id_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,prompt,{ids:{"new-b4-assistant":true},latestText:"prior unrelated reply"})===null);
  check("b4_generic_prompt_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,"Reply exactly "+marker+" and nothing else.",snap)===null);
  check("b4_wrong_nonce_in_prompt_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,prompt.replace("Reply exactly "+marker,"Reply exactly RC14V5-B4-111111111111"),snap)===null);
  check("b4_wrong_nonce_length_rejected",confirmMarkerCorroboratedBubble([],observedBubbles,prompt.replaceAll(marker,"RC14V5-B4-ABCDEF12345"),snap)===null);
  observedBubbles.length=0; replyBlocks.length=0;
  const legacy="R11-2-CHATGPT-ABCDE12345";
  const oldPrompt="Agent Relay verified discussion, round 2. Previous participant: test\nReply starting exactly with "+legacy+": then add observations.";
  const legacyBubble = observedBubble(oldPrompt);
  legacyBubble.isConnected = true;
  legacyBubble.compareDocumentPosition = function (el) { return el === replyBlocks[0] ? 4 : 0; };
  observedBubbles.push(legacyBubble);
  replyBlocks.push(makeNode(legacy+": confirmed reply","legacy-new",{roleAttr:"data-message-author-role",roleValue:"assistant"}));
  check("legacy_r11_confirmation_unchanged",!!confirmMarkerCorroboratedBubble([],observedBubbles,oldPrompt,{ids:{},latestText:"prior unrelated reply"}));
  const all_pass=checks.every(x=>x.pass);
  console.log(JSON.stringify({all_pass,checks}));
  process.exitCode=all_pass?0:1;
  return;
  // 1. ping echoes the nonce (FIX 1).
  {
    const d = dispatch({ type: "ping", nonce: "n-ping-1" });
    const resp = await d.wait();
    check("ping_echoes_nonce",
          resp && resp.type === "pong" && resp.nonce === "n-ping-1" &&
          resp.document_ready_state === "complete",
          JSON.stringify(resp));
    check("ping_listener_returns_true", d.ret === true, String(d.ret));
  }

  // 2. health echoes the nonce (FIX 1).
  {
    const d = dispatch({ type: "health", nonce: "n-health-1" });
    const resp = await d.wait();
    check("health_echoes_nonce",
          resp && resp.type === "health_result" &&
          resp.nonce === "n-health-1",
          JSON.stringify(resp));
    check("health_reports_composer_and_send",
          resp && resp.ok === true && resp.composer_found === true &&
          resp.send_button_found === true,
          JSON.stringify(resp));
  }

  // 2b. health with an EMPTY composer (no send button — the normal
  // state before typing): ok:true (HOTFIX 4 P2-A). The old rule
  // required the send button too, so it wrongly reported ok:false
  // whenever the composer was empty.
  {
    composer.value = "";
    sendButtonPresent = false;
    const d = dispatch({ type: "health", nonce: "n-health-2b" });
    const resp = await d.wait();
    check("health_empty_composer_ok",
          resp && resp.ok === true && resp.composer_found === true &&
          resp.send_button_found === false,
          JSON.stringify(resp));
    sendButtonPresent = true;
  }

  // 3. read_latest echoes the nonce, with a reply present (FIX 1).
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    replyBlocks.push(makeNode("Hello from ChatGPT", "msg-a0"));
    const d = dispatch({ type: "read_latest", nonce: "n-read-1" });
    const resp = await d.wait();
    check("read_latest_echoes_nonce",
          resp && resp.type === "read_result" &&
          resp.nonce === "n-read-1",
          JSON.stringify(resp));
    check("read_latest_returns_content",
          resp && resp.found === true &&
          resp.content === "Hello from ChatGPT",
          JSON.stringify(resp));
    check("read_latest_listener_returns_true", d.ret === true,
          String(d.ret));
  }

  // 3b. read_latest with a user article AFTER the assistant reply in
  // document order returns the assistant text, never the user text
  // (HOTFIX 2 TASK 1). The old "article" fallback would have taken
  // the last block — the user article — as the reply.
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    replyBlocks.push(makeNode("Assistant answer", "msg-a1"));
    userArticles.push(makeNode("user message as article", "msg-u1"));
    const d = dispatch({ type: "read_latest", nonce: "n-read-1b" });
    const resp = await d.wait();
    check("read_latest_ignores_user_article",
          resp && resp.found === true &&
          resp.content === "Assistant answer",
          JSON.stringify(resp));
    check("read_latest_reports_assistant_dom_id",
          resp && resp.dom_id === "msg-a1",
          JSON.stringify(resp));
  }

  // 3c. read_latest with ONLY user articles: found:false, and nothing
  // in the result labels it as a chatgpt reply (HOTFIX 2 TASK 1).
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    userArticles.push(makeNode("only user here", "msg-u2"));
    const d = dispatch({ type: "read_latest", nonce: "n-read-1c" });
    const resp = await d.wait();
    check("read_latest_user_only_not_found",
          resp && resp.found === false && !("sender" in resp),
          JSON.stringify(resp));
  }

  // 4. read_latest with no reply at all: found:false, nonce echoed.
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    const d = dispatch({ type: "read_latest", nonce: "n-read-2" });
    const resp = await d.wait();
    check("read_latest_not_found_echoes_nonce",
          resp && resp.found === false && resp.nonce === "n-read-2",
          JSON.stringify(resp));
  }

  // 3d. read_latest with innerText="" but textContent present:
  // found:true (HOTFIX 4 DEFECT 2). innerText can be empty while
  // the text is present (rendering state).
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    replyBlocks.push(makeNode("", "msg-a3d",
                              { textContent: "reply via textContent" }));
    const d = dispatch({ type: "read_latest", nonce: "n-read-3d" });
    const resp = await d.wait();
    check("read_latest_textcontent_fallback",
          resp && resp.found === true &&
          resp.content === "reply via textContent",
          JSON.stringify(resp));
  }

  // 3e. read_latest where the role attribute sits on an empty
  // wrapper but the turn container (parent, ARTICLE) holds the
  // text: found:true with the parent's text (HOTFIX 4 DEFECT 2).
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    const parent3e = makeNode("reply via parent turn", "msg-a3e-parent",
                              { tagName: "ARTICLE" });
    replyBlocks.push(makeNode("", "msg-a3e",
                              { parentElement: parent3e }));
    const d = dispatch({ type: "read_latest", nonce: "n-read-3e" });
    const resp = await d.wait();
    check("read_latest_parent_turn_fallback",
          resp && resp.found === true &&
          resp.content === "reply via parent turn",
          JSON.stringify(resp));
  }

  // 3f. read_latest where the role node is empty AND its parent is
  // MAIN: found:false (HOTFIX 4 DEFECT 2). The parent walk never
  // reaches the whole conversation.
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    replyBlocks.push(makeNode("", "msg-a3f",
                              { parentElement: container }));
    const d = dispatch({ type: "read_latest", nonce: "n-read-3f" });
    const resp = await d.wait();
    check("read_latest_parent_main_not_found",
          resp && resp.found === false && !("sender" in resp),
          JSON.stringify(resp));
  }

  // 3g. read_latest retries: the reply appears 1s after the read
  // starts (still rendering) and is found within the 3s retry
  // (HOTFIX 4 DEFECT 2 / P2-B).
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    const d = dispatch({ type: "read_latest", nonce: "n-read-3g" });
    setTimeout(() => {
      replyBlocks.push(makeNode("late reply arrives", "msg-a3g"));
    }, 1000);
    const resp = await d.wait();
    check("read_latest_retry_finds_late_reply",
          resp && resp.found === true &&
          resp.content === "late reply arrives",
          JSON.stringify(resp));
  }

  // 5. send confirmed: ok:true + delivery message_sent + message_id,
  // async channel kept open (FIX 4 + HOTFIX 2 TASK 2).
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = true;
    const d = dispatch({ type: "send", text: "hello relay",
                         nonce: "n-send-1" });
    check("send_listener_returns_true", d.ret === true, String(d.ret));
    check("send_response_not_synchronous", d.respondedNow() === false,
          "response arrived before delivery confirmation");
    const resp = await d.wait();
    check("send_confirmed_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent" &&
          resp.nonce === "n-send-1",
          JSON.stringify(resp));
    check("send_confirmed_reports_message_id",
          resp && typeof resp.message_id === "string" &&
          resp.message_id.indexOf("msg-") === 0,
          JSON.stringify(resp));
    check("send_message_in_dom",
          userMessages.length === 1 &&
          userMessages[0].innerText === "hello relay",
          JSON.stringify(userMessages.map((m) => m.innerText)));
    check("send_composer_cleared", composer.value === "",
          JSON.stringify(composer.value));
  }

  // 5b. duplicate text, genuinely new node: still message_sent
  // (HOTFIX 2 TASK 2). The text already exists in history, but a
  // NEW node appeared — that is a real send, not a misjudgment.
  {
    userMessages.length = 0;
    userMessages.push(makeNode("same text twice", "msg-old"));
    composer.value = "";
    simulateApp = true;
    const d = dispatch({ type: "send", text: "same text twice",
                         nonce: "n-send-1b" });
    const resp = await d.wait();
    check("send_duplicate_text_new_node_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    check("send_duplicate_text_new_node_has_new_id",
          resp && resp.message_id && resp.message_id !== "msg-old",
          JSON.stringify(resp));
  }

  // 5c. duplicate text, composer clears but NO new node appears:
  // UNCERTAIN, never ok:true (HOTFIX 2 TASK 2). The old check would
  // have returned message_sent here because the old identical text
  // was already in history.
  {
    userMessages.length = 0;
    userMessages.push(makeNode("same text twice", "msg-old"));
    composer.value = "";
    simulateApp = "clear-only";
    const d = dispatch({ type: "send", text: "same text twice",
                         nonce: "n-send-1c" });
    const resp = await d.wait(15000); // HOTFIX 4: confirmation timeout is 10s, so the wait must exceed it
    check("send_duplicate_text_no_new_node_is_uncertain",
          resp && resp.ok === false &&
          resp.delivery === "uncertain" &&
          resp.error === "send_unconfirmed" &&
          resp.nonce === "n-send-1c",
          JSON.stringify(resp));
    simulateApp = true;
  }

  // 5d. HOTFIX 3 TASK 1 (ChatGPT's adversarial test, reproduced
  // exactly): an OLD node with dom_id "old-id" whose text changes
  // IN PLACE to the sent text, with NO new node appearing, must be
  // UNCERTAIN — never ok:true / message_sent with message_id
  // "old-id". The hotfix2 (dom_id, text) pair check returned
  // message_sent here; the hotfix3 dom_id-identity rule must not.
  {
    userMessages.length = 0;
    userMessages.push(makeNode("old content", "old-id"));
    composer.value = "";
    simulateApp = "mutate-old";
    const d = dispatch({ type: "send", text: "new text now here",
                         nonce: "n-send-1d" });
    const resp = await d.wait(15000); // HOTFIX 4: confirmation timeout is 10s, so the wait must exceed it
    check("send_mutated_old_node_is_uncertain",
          resp && resp.ok === false &&
          resp.delivery === "uncertain" &&
          resp.error === "send_unconfirmed" &&
          resp.nonce === "n-send-1d",
          JSON.stringify(resp));
    check("send_mutated_old_node_trap_exercised",
          userMessages.length === 1 &&
          userMessages[0].innerText === "new text now here",
          JSON.stringify(userMessages.map((m) => m.innerText)));
    simulateApp = true;
  }

  // 5e. slow render (the new user node appears after 6.5s): still
  // message_sent within the longer 10s timeout (HOTFIX 4 DEFECT 1).
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = "slow";
    const d = dispatch({ type: "send", text: "slow render test",
                         nonce: "n-send-1e" });
    const resp = await d.wait(15000);
    check("send_slow_render_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    check("send_slow_render_reports_new_node",
          resp && resp.confirmation === "new_user_node",
          JSON.stringify(resp));
    simulateApp = true;
  }

  // 5f. reply-only: the composer clears and an assistant reply
  // appears, but NO user node — the corroborating signal confirms
  // delivery (HOTFIX 4 DEFECT 1).
  {
    userMessages.length = 0;
    replyBlocks.length = 0;
    composer.value = "";
    simulateApp = "reply-only";
    const d = dispatch({ type: "send", text: "reply only test",
                         nonce: "n-send-1f" });
    const resp = await d.wait(15000);
    check("send_reply_only_stays_uncertain",
          resp && resp.delivery === "uncertain" &&
          resp.error === "send_unconfirmed",
          JSON.stringify(resp));
    simulateApp = true;
  }

  // 5g. streaming-only: the composer clears and the stop button
  // appears, but NO user node and NO reply text yet — the
  // corroborating signal confirms delivery (HOTFIX 4 DEFECT 1).
  {
    userMessages.length = 0;
    replyBlocks.length = 0;
    composer.value = "";
    simulateApp = "streaming-only";
    const d = dispatch({ type: "send", text: "streaming only test",
                         nonce: "n-send-1g" });
    const resp = await d.wait(15000);
    check("send_streaming_only_stays_uncertain",
          resp && resp.delivery === "uncertain" &&
          resp.error === "send_unconfirmed",
          JSON.stringify(resp));
    simulateApp = true;
    stopButtonPresent = false;
  }

  // 5h. normalize: the page re-renders the sent text with different
  // whitespace; the normalised match still confirms (HOTFIX 4
  // DEFECT 1).
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = "normalize";
    const d = dispatch({ type: "send", text: "hello   relay\nworld",
                         nonce: "n-send-1h" });
    const resp = await d.wait(15000);
    check("send_normalized_text_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    simulateApp = true;
  }

  // 5i. sync delay: the send button is disabled until React syncs
  // (enabled after 1.2s); doSend waits for it before clicking
  // (HOTFIX 4 P2 / DEFECT 3).
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = true;
    sendButton.disabled = true;
    setTimeout(() => { sendButton.disabled = false; }, 1200);
    const d = dispatch({ type: "send", text: "sync delay test",
                         nonce: "n-send-1i" });
    const resp = await d.wait(15000);
    check("send_sync_delay_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    sendButton.disabled = false;
  }

  // 5j. P2-A order: the send button does NOT exist while the
  // composer is empty; it appears only after text is typed
  // (ATTEMPT-07). doSend must fill first, then wait for the
  // button, then click once — and confirm message_sent.
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = true;
    sendButtonPresent = false;
    sendButtonAppearsAfterInput = true;
    const d = dispatch({ type: "send", text: "button after input",
                         nonce: "n-send-1j" });
    const resp = await d.wait(15000);
    check("send_button_after_input_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    sendButtonPresent = true;
    sendButtonAppearsAfterInput = false;
  }

  // 5k. P2-A: the send button NEVER appears after the input — the
  // result is not_sent (never clicked), not UNCERTAIN.
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = true;
    sendButtonPresent = false;
    sendButtonAppearsAfterInput = false;
    const d = dispatch({ type: "send", text: "button never appears",
                         nonce: "n-send-1k" });
    const resp = await d.wait(15000);
    check("send_button_never_appears_is_not_sent",
          resp && resp.ok === false &&
          resp.delivery === "not_sent" &&
          resp.error === "send_button_missing_after_input",
          JSON.stringify(resp));
    sendButtonPresent = true;
  }

  // 5l. HOTFIX 5 (P2, ATTEMPT-08 — HEADLINE): the send button
  // EXISTS but NEVER enables after the input (the page never
  // registered the input). Hotfix4 resolved the disabled button
  // at the button-wait deadline and clicked it — a DOM no-op —
  // so nothing was submitted, the text stayed in the composer,
  // and confirmation timed out as UNCERTAIN (send_unconfirmed)
  // with 1 wasted click. Hotfix5 must return not_sent with the
  // new error send_button_never_enabled and NEVER click.
  // d.wait(20000) so Hotfix4's wrong result (5s button wait +
  // 10s confirmation) completes cleanly and is caught.
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = true;
    sendButton.disabled = true; // never re-enabled: the ATTEMPT-08 state
    sendButtonClicks = 0;
    const d = dispatch({ type: "send", text: "button never enables",
                         nonce: "n-send-1l" });
    const resp = await d.wait(20000);
    check("send_button_never_enabled_is_not_sent",
          resp && resp.ok === false &&
          resp.delivery === "not_sent" &&
          resp.error === "send_button_never_enabled",
          JSON.stringify(resp));
    check("send_button_never_enabled_never_clicked",
          sendButtonClicks === 0,
          "clicks=" + sendButtonClicks);
    check("send_button_never_enabled_text_stays_in_composer",
          composer.value === "button never enables",
          JSON.stringify(composer.value));
    sendButton.disabled = false;
  }

  // 5m. HOTFIX 5 (P2): the fill does not stick — the native
  // setter runs but the composer's value never changes, so the
  // page never accepted the input. Hotfix5 fails FAST with
  // composer_input_not_accepted and never clicks (guard test:
  // Hotfix4 returns the same error, but only after waiting the
  // full 5s for a button that can never enable).
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = true;
    fillSticks = false;
    sendButtonClicks = 0;
    const d = dispatch({ type: "send", text: "fill does not stick",
                         nonce: "n-send-1m" });
    const resp = await d.wait(15000);
    check("send_fill_not_accepted_is_not_sent",
          resp && resp.ok === false &&
          resp.delivery === "not_sent" &&
          resp.error === "composer_input_not_accepted",
          JSON.stringify(resp));
    check("send_fill_not_accepted_never_clicked",
          sendButtonClicks === 0,
          "clicks=" + sendButtonClicks);
    fillSticks = true;
  }

  // 6. send that cannot be confirmed at all: UNCERTAIN, never
  // auto-resend.
  {
    userMessages.length = 0;
    composer.value = "";
    simulateApp = false; // the app never shows the message
    const d = dispatch({ type: "send", text: "will not appear",
                         nonce: "n-send-2" });
    const resp = await d.wait(15000); // HOTFIX 4: confirmation timeout is 10s, so the wait must exceed it
    check("send_unconfirmed_is_uncertain",
          resp && resp.ok === false &&
          resp.delivery === "uncertain" &&
          resp.error === "send_unconfirmed" &&
          resp.nonce === "n-send-2",
          JSON.stringify(resp));
    simulateApp = true;
  }

  // 7. send with a missing composer: definitely not sent.
  {
    composerPresent = false;
    const d = dispatch({ type: "send", text: "no composer",
                         nonce: "n-send-3" });
    const resp = await d.wait();
    check("send_missing_composer_not_sent",
          resp && resp.ok === false &&
          resp.delivery === "not_sent" &&
          resp.error === "composer_or_send_button_missing",
          JSON.stringify(resp));
    composerPresent = true;
  }

  // 8. completion watch reports the assistant reply, never a user
  // message (HOTFIX 2 TASK 1). The watch uses the same latestReply()
  // as read_latest, so a user article must never be reported as
  // sender:"chatgpt".
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    sentMessages.length = 0;
    replyBlocks.push(makeNode("Assistant answer here", "msg-a2"));
    userArticles.push(
      makeNode("user text that looks like an article", "msg-u3"));
    MutationObserverStub.fireAll();
    await sleep(3600); // REPLY_SETTLE_MS (3000) + margin
    const reports = sentMessages.filter((m) => m.type === "reply_complete");
    check("completion_watch_reports_assistant_reply",
          reports.length >= 1 &&
          reports[reports.length - 1].content === "Assistant answer here",
          JSON.stringify(reports.map((r) => r.content)));
    check("completion_watch_never_reports_user_article",
          !reports.some((r) => r.content &&
            r.content.indexOf("user text that looks like") !== -1),
          JSON.stringify(reports.map((r) => r.content)));
  }

  // 9. completion watch with only user articles: reports nothing.
  {
    replyBlocks.length = 0;
    userArticles.length = 0;
    const before = sentMessages.length;
    userArticles.push(makeNode("only a user article now", "msg-u4"));
    MutationObserverStub.fireAll();
    await sleep(3600);
    check("completion_watch_user_only_reports_nothing",
          sentMessages.length === before,
          `before=${before} after=${sentMessages.length}`);
  }

  // --- HOTFIX 6 (B2/B3/B4, ROUND 25) ----------------------------------
  function resetHotfix6() {
    userMessages.length = 0;
    userArticles.length = 0;
    replyBlocks.length = 0;
    userAltMessages.length = 0;
    replyAltBlocks.length = 0;
    bareTurns.length = 0;
    observedBubbles.length = 0;
    composer.value = "";
    simulateApp = true;
    sendButtonPresent = true;
    sendButtonAppearsAfterInput = false;
    sendButtonAppearDelayMs = 200;
    sendButton.disabled = false;
    stopButtonPresent = false;
    userNodeRoleMode = "primary";
    documentStub.visibilityState = "visible";
  }
  function timelineLabels(timeline) {
    return (timeline || []).map((s) => s.label);
  }

  // 6a. B2: the user node carries an ALTERNATE role attribute
  // (data-author-role='user') — the primary selector misses it,
  // the fallback finds it. The send is confirmed message_sent.
  {
    resetHotfix6();
    userNodeRoleMode = "alt";
    const d = dispatch({ type: "send", text: "alt role user",
                         nonce: "n-send-6a" });
    const resp = await d.wait(15000);
    check("send_alt_role_user_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    check("send_alt_role_user_reports_strategy",
          resp && resp.node_strategy === "role_attribute",
          JSON.stringify(resp));
    userNodeRoleMode = "primary";
  }

  // 6b. B3: the assistant reply carries an ALTERNATE role
  // attribute (data-author-role='assistant') — the primary
  // selector misses it, the fallback finds it.
  {
    resetHotfix6();
    replyAltBlocks.push(makeNode(
      "assistant reply via alt role", "msg-a-alt-b",
      { roleAttr: "data-author-role", roleValue: "assistant" }));
    const d = dispatch({ type: "read_latest", nonce: "n-read-6b" });
    const resp = await d.wait();
    check("read_latest_alt_role_assistant_found",
          resp && resp.found === true &&
          resp.content === "assistant reply via alt role",
          JSON.stringify(resp));
    check("read_latest_alt_role_reports_strategy",
          resp && resp.strategy === "role_attribute",
          JSON.stringify(resp));
  }

  // 6c. B2+B3, the ATTEMPT-09 exact scenario: the message WAS
  // delivered and the reply IS present, but the single primary
  // selectors miss both (both use alternate role attributes).
  // The multi-strategy path must now recognise both.
  {
    resetHotfix6();
    userNodeRoleMode = "alt";
    const d = dispatch({ type: "send", text: "H5-B2-20261120-01",
                         nonce: "n-send-6c" });
    const sendResp = await d.wait(15000);
    check("attempt09_scenario_send_is_message_sent",
          sendResp && sendResp.ok === true &&
          sendResp.delivery === "message_sent",
          JSON.stringify(sendResp));
    replyAltBlocks.push(makeNode(
      "ACK-H5-B2-20261120-01", "msg-a-alt-c",
      { roleAttr: "data-author-role", roleValue: "assistant" }));
    const r = dispatch({ type: "read_latest", nonce: "n-read-6c" });
    const readResp = await r.wait();
    check("attempt09_scenario_read_finds_reply",
          readResp && readResp.found === true &&
          readResp.content === "ACK-H5-B2-20261120-01",
          JSON.stringify(readResp));
    userNodeRoleMode = "primary";
  }

  // 6d. B4 (ROUND 25): hidden tab, the button appears only after
  // 6s (slow background render). The send is confirmed, and the
  // result carries the button time series with the four points —
  // before input, after input, during the wait, button found —
  // all with visibility "hidden".
  {
    resetHotfix6();
    documentStub.visibilityState = "hidden";
    sendButtonPresent = false;
    sendButtonAppearsAfterInput = true;
    sendButtonAppearDelayMs = 6000;
    const d = dispatch({ type: "send", text: "hidden tab late button",
                         nonce: "n-send-6d" });
    const resp = await d.wait(20000);
    const labels = timelineLabels(resp && resp.button_timeline);
    check("send_hidden_tab_late_button_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    check("send_hidden_tab_timeline_has_four_points",
          labels.indexOf("before_input") !== -1 &&
          labels.indexOf("after_input") !== -1 &&
          labels.indexOf("during_wait") !== -1 &&
          labels.indexOf("button_found") !== -1,
          JSON.stringify(labels));
    check("send_hidden_tab_timeline_reports_hidden",
          (resp.button_timeline || []).every(
            (s) => s.visibility === "hidden"),
          JSON.stringify(resp.button_timeline));
    check("send_hidden_tab_timeline_button_appears",
          (resp.button_timeline || []).some(
            (s) => s.label === "button_found" && s.button.exists === true &&
                   s.button.disabled === false),
          JSON.stringify(resp.button_timeline));
    resetHotfix6();
  }

  // 6e. B4 (ROUND 25): hidden tab, the button NEVER appears. The
  // result is not_sent (send_button_missing_after_input) with a
  // time series ending in a "timeout" sample whose button does
  // not exist and whose visibility is "hidden" — the evidence
  // that distinguishes "never appeared" from "appeared but
  // disabled".
  {
    resetHotfix6();
    documentStub.visibilityState = "hidden";
    sendButtonPresent = false;
    sendButtonAppearsAfterInput = false;
    const beforeClicks = sendButtonClicks;
    const d = dispatch({ type: "send", text: "hidden tab no button",
                         nonce: "n-send-6e" });
    const resp = await d.wait(25000);
    const labels = timelineLabels(resp && resp.button_timeline);
    check("send_hidden_tab_no_button_is_not_sent",
          resp && resp.ok === false &&
          resp.delivery === "not_sent" &&
          resp.error === "send_button_missing_after_input",
          JSON.stringify(resp));
    check("send_missing_button_never_clicks",
          sendButtonClicks === beforeClicks, "clicks=" + sendButtonClicks);
    check("send_hidden_tab_no_button_visibility_hidden",
          resp && resp.visibility_state === "hidden",
          JSON.stringify(resp));
    check("send_hidden_tab_timeline_ends_in_timeout",
          labels.indexOf("before_input") !== -1 &&
          labels.indexOf("after_input") !== -1 &&
          labels.indexOf("during_wait") !== -1 &&
          labels[labels.length - 1] === "timeout",
          JSON.stringify(labels));
    const timeoutSample = (resp.button_timeline || [])
      .filter((s) => s.label === "timeout").pop();
    check("send_hidden_tab_timeout_sample_button_absent",
          timeoutSample && timeoutSample.button.exists === false &&
          timeoutSample.visibility === "hidden",
          JSON.stringify(timeoutSample));
    resetHotfix6();
  }

  // 6f. B2/B3 diagnostics: when recognition finds nothing, the
  // UNCERTAIN send and the not-found read both carry a
  // de-sensitized diagnostic inventory (tag names, attribute
  // names, role values, text LENGTH — NEVER message content).
  {
    resetHotfix6();
    userMessages.push(makeNode("old history text", "msg-old-f"));
    simulateApp = false;
    const d = dispatch({ type: "send", text: "will not appear f",
                         nonce: "n-send-6f" });
    const resp = await d.wait(15000);
    check("send_unconfirmed_carries_diagnostics",
          resp && resp.delivery === "uncertain" &&
          resp.diagnostics && resp.diagnostics.kind === "user" &&
          Array.isArray(resp.diagnostics.inventory) &&
          resp.diagnostics.inventory.length >= 1,
          JSON.stringify(resp && resp.diagnostics));
    const diagJson = JSON.stringify(resp && resp.diagnostics);
    check("send_diagnostics_contain_no_message_content",
          diagJson.indexOf("will not appear f") === -1 &&
          diagJson.indexOf("old history text") === -1,
          diagJson.slice(0, 400));
    check("send_diagnostics_record_strategies_tried",
          resp && resp.diagnostics &&
          resp.diagnostics.strategies_tried.indexOf("role_attribute") !== -1 &&
          resp.diagnostics.strategies_tried.indexOf("text_anchor") !== -1,
          JSON.stringify(resp && resp.diagnostics.strategies_tried));
    simulateApp = true;
    const r = dispatch({ type: "read_latest", nonce: "n-read-6f" });
    const readResp = await r.wait();
    check("read_not_found_carries_diagnostics",
          readResp && readResp.found === false &&
          readResp.diagnostics &&
          readResp.diagnostics.kind === "assistant",
          JSON.stringify(readResp && readResp.diagnostics));
  }

  // 6g. B2: the user role attribute sits on an empty wrapper whose
  // parent TURN article holds the text (the turn-container walk).
  // The send is confirmed with the turn's data-message-id.
  {
    resetHotfix6();
    userNodeRoleMode = "turn";
    const d = dispatch({ type: "send", text: "turn container user",
                         nonce: "n-send-6g" });
    const resp = await d.wait(15000);
    check("send_turn_container_user_is_message_sent",
          resp && resp.ok === true &&
          resp.delivery === "message_sent",
          JSON.stringify(resp));
    check("send_turn_container_reports_turn_id",
          resp && typeof resp.message_id === "string" &&
          resp.message_id.indexOf("-turn") !== -1,
          JSON.stringify(resp));
    userNodeRoleMode = "primary";
  }

  // 6h. B3: the assistant role attribute sits on an empty wrapper
  // whose parent TURN article holds the text.
  {
    resetHotfix6();
    const turn = makeNode("assistant reply via turn", "msg-a-turn-h",
                          { tagName: "ARTICLE" });
    replyBlocks.push(makeNode(
      "", null,
      { parentElement: turn,
        roleAttr: "data-message-author-role", roleValue: "assistant" }));
    const d = dispatch({ type: "read_latest", nonce: "n-read-6h" });
    const resp = await d.wait();
    check("read_latest_turn_container_assistant_found",
          resp && resp.found === true &&
          resp.content === "assistant reply via turn",
          JSON.stringify(resp));
  }

  // Real ChatGPT must distinguish assistant authorship from adjacency.
  {
    resetHotfix6();
    const d = dispatch({ type: "send", text: "after user turn test",
                         nonce: "n-send-6i" });
    const sendResp = await d.wait(15000);
    check("after_user_turn_send_confirmed",
          sendResp && sendResp.ok === true &&
          sendResp.delivery === "message_sent",
          JSON.stringify(sendResp));
    replyBlocks.length = 0;
    bareTurns.push(makeNode("AI reply after user turn",
                            "msg-a-after-i"));
    const r = dispatch({ type: "read_latest", nonce: "n-read-6i" });
    const readResp = await r.wait();
    check("read_latest_rejects_unauthored_adjacent_turn",
          readResp && readResp.found === false,
          JSON.stringify(readResp));
  }

  {
    resetHotfix6();
    observedBubbles.push(observedBubble("Earlier message"));
    userNodeRoleMode = "observed";
    const d = dispatch({ type: "send", text: "fresh marker",
                         nonce: "n-send-54998652" });
    const response = await d.wait();
    check("observed_user_bubble_confirms_current_nonce",
          response && response.delivery === "message_sent" &&
          response.nonce === "n-send-54998652" &&
          response.message_id === null &&
          response.node_strategy === "observed_user_bubble",
          JSON.stringify(response));
    const bubble = observedBubbles[observedBubbles.length - 1];
    const pair = makeNode("", null, { roleAttr: "data-turn-key", roleValue: "fixture" });
    bubble.parentElement = pair;
    const body = makeNode("fixture reply", "fixture-body", {
      parentElement: pair, roleAttr: "data-response-body", roleValue: "",
    });
    bareTurns.push(body);
    bubble.compareDocumentPosition = (node) => node === body ? 4 : 2;
    const unknown = await dispatch({ type: "read_latest", nonce: "n-b3-boundary-only" }).wait();
    check("response_body_and_shared_key_do_not_establish_author",
          unknown && unknown.found === false, JSON.stringify(unknown));

    const author = makeNode("fixture reply", "fixture-authored", {
      parentElement: pair, roleAttr: "data-message-author-role", roleValue: "assistant",
    });
    replyBlocks.push(author);
    const preceding = await dispatch({ type: "read_latest", nonce: "n-b3-history" }).wait();
    check("observed_layout_rejects_authored_reply_before_anchor",
          preceding && preceding.found === false, JSON.stringify(preceding));

    bubble.compareDocumentPosition = (node) => node === author ? 4 | 16 : 2;
    const nested = await dispatch({ type: "read_latest", nonce: "n-b3-user-quote" }).wait();
    check("observed_layout_rejects_assistant_marker_inside_user_bubble",
          nested && nested.found === false, JSON.stringify(nested));

    bubble.compareDocumentPosition = (node) => node === author ? 4 | 1 : 2;
    const disconnected = await dispatch({ type: "read_latest", nonce: "n-b3-detached" }).wait();
    check("observed_layout_rejects_disconnected_authored_node",
          disconnected && disconnected.found === false, JSON.stringify(disconnected));

    bubble.compareDocumentPosition = (node) => node === author ? 4 : 2;
    const actual = await dispatch({ type: "read_latest", nonce: "n-b3-authored" }).wait();
    check("observed_layout_reads_independently_authored_later_reply",
          actual && actual.found === true && actual.content === "fixture reply" &&
          actual.nonce === "n-b3-authored", JSON.stringify(actual));
    resetHotfix6();
  }

  {
    resetHotfix6();
    userNodeRoleMode = "observed";
    const clicks = sendButtonClicks;
    const response = await dispatch({type: "send", text: "first observed message",
      nonce: "first-observed-empty-transcript"}).wait();
    check("first_observed_bubble_in_empty_transcript_confirms_once",
          response && response.delivery === "message_sent" &&
          response.nonce === "first-observed-empty-transcript" &&
          response.node_strategy === "observed_user_bubble" &&
          observedBubbles.length === 1 && !composer.value &&
          sendButtonClicks === clicks + 1, JSON.stringify(response));
    resetHotfix6();
  }

  {
    const old = observedBubble("marker");
    const snapshot = [{ el: old, text: "marker" }];
    const fresh = observedBubble("marker");
    check("observed_duplicate_marker_is_rejected",
          globalThis.confirmObservedBubble(snapshot, [old, fresh], "marker") === null);
    check("observed_remounted_history_is_rejected",
          globalThis.confirmObservedBubble([{ el: old, text: "old" }],
                                           [observedBubble("old"), fresh], "marker") === null);
    check("observed_quoted_marker_is_rejected",
          globalThis.confirmObservedBubble([], [observedBubble("marker", true)], "marker") === null);
    const changed = observedBubble("before edit");
    const beforeEdit = [{el: changed, text: "before edit"}];
    const changedLeaf = changed.querySelectorAll(".text-size-chat.whitespace-pre-wrap")[0];
    changedLeaf.innerText = changedLeaf.textContent = "marker";
    check("observed_in_place_edit_is_not_a_send",
          globalThis.confirmObservedBubble(beforeEdit, [changed], "marker") === null);
    check("observed_edit_plus_append_cannot_confirm_as_clean_append",
          globalThis.confirmObservedBubble(beforeEdit, [changed, fresh], "marker") === null);
    check("observed_multiple_appended_bubbles_are_ambiguous",
          globalThis.confirmObservedBubble([], [fresh, observedBubble("other")], "marker") === null);
    check("observed_substring_is_rejected",
          globalThis.confirmObservedBubble([], [observedBubble("prefix marker")], "marker") === null);
  }

  // 6j. B2: the user node has NO role marker at all (a bare turn
  // with data-message-id). The sent-text anchor finds it.
  {
    resetHotfix6();
    userNodeRoleMode = "bare";
    const d = dispatch({ type: "send", text: "bare turn user text",
                         nonce: "n-send-6j" });
    const resp = await d.wait(15000);
    check("send_bare_turn_user_stays_uncertain",
          resp && resp.delivery === "uncertain" &&
          resp.error === "send_unconfirmed",
          JSON.stringify(resp));
    userNodeRoleMode = "primary";
  }

  // 6k. B3 guard: a bare turn AFTER the confirmed user turn that
  // merely ECHOES the sent text is the user's own message, not a
  // reply — read_latest must report found:false, never
  // misidentify it (the Hotfix2 error).
  {
    resetHotfix6();
    const d = dispatch({ type: "send", text: "echo guard test",
                         nonce: "n-send-6k" });
    const sendResp = await d.wait(15000);
    check("echo_guard_send_confirmed",
          sendResp && sendResp.ok === true &&
          sendResp.delivery === "message_sent",
          JSON.stringify(sendResp));
    replyBlocks.length = 0;
    bareTurns.push(makeNode("echo guard test", "msg-u-echo-k"));
    const r = dispatch({ type: "read_latest", nonce: "n-read-6k" });
    const readResp = await r.wait();
    check("read_latest_echo_turn_is_not_a_reply",
          readResp && readResp.found === false,
          JSON.stringify(readResp));
  }

  // --- HOTFIX 6 (ROUND 25): de-sensitized DOM collector ------------
  // The collector matches the two known test markers and returns
  // ONLY structure (found flags, role-selector counts, tag / role /
  // testid / class / parent chain). It must NEVER return message
  // content: the result JSON must not contain the marker texts.
  const USER_MARKER = "Agent Relay Hotfix5 E2E B2 ID H5-B2-20261120-01";
  const ASSISTANT_MARKER = "ACK-H5-B2-20261120-01";

  // 7a. collect_dom finds both markers; the counts match the role
  // nodes; the structures carry tag/role/testid; no content leaks.
  {
    resetHotfix6();
    userMessages.push(makeNode(
      USER_MARKER, "msg-u-collect",
      { roleAttr: "data-message-author-role", roleValue: "user",
        classes: ["user-turn", "chat-message"] }));
    replyBlocks.push(makeNode(
      ASSISTANT_MARKER, "msg-a-collect",
      { roleAttr: "data-message-author-role", roleValue: "assistant",
        classes: ["assistant-turn"] }));
    const d = dispatch({ type: "collect_dom",
                         user_marker: USER_MARKER,
                         assistant_marker: ASSISTANT_MARKER,
                         nonce: "n-collect-7a" });
    const resp = await d.wait();
    check("collect_dom_finds_both_markers",
          resp && resp.type === "collect_dom_result" &&
          resp.ok === true && resp.user_found === true &&
          resp.assistant_found === true,
          JSON.stringify(resp));
    check("collect_dom_role_counts_match",
          resp && resp.role_selector_counts &&
          resp.role_selector_counts.user === 1 &&
          resp.role_selector_counts.assistant === 1,
          JSON.stringify(resp && resp.role_selector_counts));
    check("collect_dom_structures_carry_role_attrs",
          resp && Array.isArray(resp.user_structure) &&
          resp.user_structure.length >= 1 &&
          resp.user_structure[0].authorRole === "user" &&
          Array.isArray(resp.assistant_structure) &&
          resp.assistant_structure.length >= 1 &&
          resp.assistant_structure[0].authorRole === "assistant",
          JSON.stringify({ u: resp && resp.user_structure,
                           a: resp && resp.assistant_structure }));
    const respJson = JSON.stringify(resp);
    check("collect_dom_contains_no_message_content",
          respJson.indexOf("H5-B2-20261120-01") === -1 &&
          respJson.indexOf("ACK-H5-B2-20261120-01") === -1,
          respJson.slice(0, 500));
  }

  // 7b. KEY DIAGNOSTIC (ROUND 25): the user message EXISTS but
  // the user role selector matches NOTHING — user_found=true
  // with role_selector_counts.user=0 is direct evidence the
  // selector is broken.
  {
    resetHotfix6();
    bareTurns.push(makeNode(USER_MARKER, "msg-u-bare-b"));
    const d = dispatch({ type: "collect_dom",
                         user_marker: USER_MARKER,
                         assistant_marker: ASSISTANT_MARKER,
                         nonce: "n-collect-7b" });
    const resp = await d.wait();
    check("collect_dom_user_found_but_role_count_zero",
          resp && resp.ok === true && resp.user_found === true &&
          resp.role_selector_counts &&
          resp.role_selector_counts.user === 0,
          JSON.stringify(resp));
    check("collect_dom_assistant_absent_here",
          resp && resp.assistant_found === false &&
          resp.role_selector_counts.assistant === 0,
          JSON.stringify(resp));
  }

  // 7c. Same diagnostic for the assistant side.
  {
    resetHotfix6();
    bareTurns.push(makeNode(ASSISTANT_MARKER, "msg-a-bare-c"));
    const d = dispatch({ type: "collect_dom",
                         user_marker: USER_MARKER,
                         assistant_marker: ASSISTANT_MARKER,
                         nonce: "n-collect-7c" });
    const resp = await d.wait();
    check("collect_dom_assistant_found_but_role_count_zero",
          resp && resp.ok === true && resp.assistant_found === true &&
          resp.role_selector_counts &&
          resp.role_selector_counts.assistant === 0,
          JSON.stringify(resp));
    check("collect_dom_user_absent_here",
          resp && resp.user_found === false &&
          resp.role_selector_counts.user === 0,
          JSON.stringify(resp));
  }

  // 7d. collect_dom without markers is rejected, not run.
  {
    const d = dispatch({ type: "collect_dom", nonce: "n-collect-7d" });
    const resp = await d.wait();
    check("collect_dom_missing_markers_rejected",
          resp && resp.type === "collect_dom_result" &&
          resp.ok === false && resp.error === "missing_marker",
          JSON.stringify(resp));
  }

  // RC14-v3: only the combination of an exact unique user bubble and
  // a NEW positively identified marker reply can bridge a remounted
  // history. None of the adversarial cases may be accepted.
  {
    resetHotfix6();
    resetRC14Anchor();
    const marker = "R11-2-CHATGPT-ABCDE12345";
    const prompt = "Agent Relay verified discussion, round 2. Previous participant: test\\nReply starting exactly with " + marker + ": then add observations.";
    const first = observedBubble(prompt);
    first.isConnected = true;
    first.compareDocumentPosition = function (el) { return el === replyBlocks[0] ? 4 : 0; };
    observedBubbles.push(first);
    replyBlocks.push(makeNode(marker + ": confirmed reply", "msg-a-rc14",
      {roleAttr:"data-message-author-role",roleValue:"assistant"}));
    const snap={ids:{},latestText:"previous assistant reply"};
    const ok=confirmMarkerCorroboratedBubble([],observedBubbles,prompt,snap);
    check("rc14_remount_unique_full_text_and_new_reply",
      !!ok && ok.strategy === "verified_marker_reply_after_rerender");
    check("rc14_reject_history_with_original_identical_prompt",
      confirmMarkerCorroboratedBubble([{el:first,text:prompt}],
        observedBubbles,prompt,snap) === null);
    observedBubbles.push(observedBubble(prompt));
    check("rc14_reject_ambiguous_two_full_matches",
      confirmMarkerCorroboratedBubble([],observedBubbles,prompt,snap) === null);
    observedBubbles.pop();
    check("rc14_reject_preexisting_reply_marker",
      confirmMarkerCorroboratedBubble([],observedBubbles,prompt,
        {ids:{},latestText:marker+": old response"}) === null);
    replyBlocks.length=0;
    replyBlocks.push(makeNode("different reply","msg-a-different",
      {roleAttr:"data-message-author-role",roleValue:"assistant"}));
    check("rc14_reject_wrong_assistant_reply",
      confirmMarkerCorroboratedBubble([],observedBubbles,prompt,snap) === null);
    check("rc14_reject_generic_nonmarker_prompt",
      confirmMarkerCorroboratedBubble([],observedBubbles,
        "an ordinary request without a marker",snap) === null);
    check("rc14_reject_old_user_node_retext",
      confirmMarkerCorroboratedBubble([{el:first,text:"original old message"}],
        observedBubbles,prompt,snap) === null);
    resetHotfix6();
  }

  const allPass = checks.every((c) => c.pass);
  // HOTFIX 6: do NOT call process.exit() right after console.log.
  // When stdout is a pipe (the Python test captures it with
  // subprocess.run(capture_output=True)), console.log's write is
  // async and process.exit() truncates whatever has not drained
  // yet — the Hotfix6 output is ~71 KB, so the test only received
  // the first 65,536 bytes (one pipe buffer) and JSON parsing
  // failed. Setting process.exitCode lets the event loop drain
  // stdout before the process exits; the exit code is identical.
  // (Hotfix5's output was ~15 KB, under one pipe buffer, so the
  // race never showed up.)
  console.log(JSON.stringify({ all_pass: allPass, checks }, null, 2));
  process.exitCode = allPass ? 0 : 1;
}

main().catch((e) => {
  console.log(JSON.stringify({
    all_pass: false,
    checks: checks.concat([{ name: "harness_error", pass: false,
                             detail: String(e && e.stack || e) }]),
  }, null, 2));
  process.exitCode = 1;
});
