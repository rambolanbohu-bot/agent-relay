/**
 * Agent Relay Browser Adapter — content script (v1.0.0-rc4-hotfix5).
 *
 * Runs inside the user's own chatgpt.com / muse.ai tab. It does exactly
 * three things: read the latest assistant reply, send a message, and detect
 * when a reply has finished streaming. Nothing else.
 *
 * RC4-HOTFIX (ChatGPT review of the corrected RC4, 2026-11-19 23:54):
 * - FIX 1 (P0): every reply echoes the request nonce. ping returns
 *   {type:"pong", origin, nonce}; doHealth() and doReadLatest() include
 *   the nonce in their results. Before this fix only the send path
 *   echoed the nonce, so adapter.py _wait_outbox() (which matches on
 *   nonce) timed out even when the browser had responded.
 * - FIX 4 (P1): send confirmation distinguishes MESSAGE_SENT from
 *   RESPONSE_COMPLETED. doSend() waits until the new user message
 *   actually appears in the chat history (composer cleared AND the
 *   message in the DOM) before returning ok:true. ok:true means
 *   MESSAGE_SENT only — never that the AI reply is done; the
 *   completion watch reports RESPONSE_COMPLETED separately via
 *   reply_complete when the reply finishes streaming. If delivery
 *   cannot be confirmed within the timeout, the result is UNCERTAIN
 *   (ok:false, delivery:"uncertain") — never auto-resend. The send
 *   listener keeps the async response channel open (returns true) while
 *   it waits, so sendResponse stays valid.
 *
 * RC4-HOTFIX2 (ChatGPT review of the RC4 hotfix, 2026-11-20 10:13):
 * - TASK 1: read_latest() only accepts nodes that positively identify
 *   as assistant replies ([data-message-author-role='assistant']).
 *   The generic "article" fallback is REMOVED for both ChatGPT and
 *   Muse: a user message rendered as an <article> could be the last
 *   block, and latestReply() would then report it as sender:"chatgpt".
 *   If no positively-identified assistant node exists, latestReply()
 *   returns null and read_latest reports found:false — NEVER guess.
 *   The completion watch uses the same latestReply(), so it also
 *   never reports a user message as a reply.
 * - TASK 2: send confirmation takes a snapshot of the user message
 *   blocks BEFORE send.click() and requires a NEW node (count
 *   increased, or a new dom_id, or a new content fingerprint)
 *   containing the sent text. The old check only scanned all user
 *   blocks for indexOf(text), so if the same text already existed in
 *   history and the composer cleared without a new message, it still
 *   returned ok:true. The new node's data-message-id (when present)
 *   is bound and reported as message_id. Only the old identical text
 *   with no new node → UNCERTAIN, never auto-resend.
 *
 * RC4-HOTFIX3 (ChatGPT review of the RC4 hotfix2, 2026-11-20 11:00):
 * - TASK 1 (boundary defect in the HOTFIX 2 rule): the HOTFIX 2 rule
 *   treated a node as new when its (dom_id, text) pair was not in the
 *   pre-send snapshot. An OLD node whose content changed in place —
 *   same dom_id, new text, NO new node — therefore counted as a new
 *   message and returned ok:true, delivery:"message_sent" with the
 *   OLD message_id. ChatGPT reproduced this on the real code with an
 *   adversarial test (old node "old-id", text changed in place).
 *   The HOTFIX 3 rule: newness is dom_id identity ONLY. A node is
 *   new only when its dom_id was NOT present in the pre-send
 *   snapshot (a set of dom_ids, not (dom_id, text) pairs). A node
 *   whose dom_id IS in the snapshot is ignored no matter how its
 *   text changed. When dom_id is missing on every block, the
 *   position fallback (index >= snapshot length) still applies.
 *   No genuinely new node containing the sent text → UNCERTAIN,
 *   never auto-resend.
 *
 * RC4-HOTFIX4 (ATTEMPT-07, ChatGPT's acceptance summary,
 *   2026-11-20 21:21 — three defects, all in this file; plus
 *   ChatGPT's ROUND-22 reply, 2026-11-20 21:31, with precise
 *   source locations and the new GATE-SEAMLESS-CONTINUITY):
 * - DEFECT 1 (B2 send confirmation misjudged): the message was
 *   actually sent and ChatGPT replied, but the system reported
 *   send_unconfirmed. Causes fixed here: (a) the confirmation
 *   timeout (5s) was too short for a slow page render / a
 *   backgrounded (minimised) tab whose timers are throttled — now
 *   10s; (b) confirmation required ONLY a new user node, so when
 *   the page rendered the sent message in a form the node check
 *   missed, delivery was reported uncertain even though the AI
 *   was already replying — now a corroborating signal also
 *   confirms: composer cleared AND the AI started replying
 *   (stop button present, or a new assistant reply block
 *   appeared). That is explicit delivery evidence (the AI can
 *   only reply to a delivered message), and it is reported with
 *   confirmation:"reply_started" so the coordinator can tell it
 *   apart from confirmation:"new_user_node". UNCERTAIN still
 *   never auto-resends. (c) THE CLEAREST BUG (ROUND 22):
 *   doSend() looked the send button up FIRST and filled the
 *   content after — but the button does NOT exist while the
 *   composer is empty; it only appears AFTER text is typed
 *   (ATTEMPT-07). The old order failed before ever typing
 *   whenever the button was not yet there. The order is now:
 *   locate the composer, snapshot, fill, WAIT (bounded, on
 *   actual DOM state — the button appearing and becoming
 *   enabled, never a fixed delay) for the usable button, then
 *   ONE DOM send action. If no button ever appears after the
 *   input, the result is not_sent
 *   (send_button_missing_after_input — never clicked). (d)
 *   doHealth() wrongly reported ok:false when the composer was
 *   empty and no send button existed — that is the normal state,
 *   not a failure. ok now requires only the composer;
 *   send_button_found stays informational.
 * - DEFECT 2 (B3 read_latest found=false although the AI reply
 *   is on the page): read_latest only accepted a reply block
 *   whose own innerText was non-empty. On the real page the
 *   assistant role attribute can sit on a wrapper whose own text
 *   is empty (the text lives in the turn container), and innerText
 *   can be empty while the text is present (rendering state).
 *   Fixed here WITHOUT reintroducing the generic "article"
 *   fallback (that caused misidentification; hotfix2 removed it):
 *   text is read as innerText if non-empty, else textContent;
 *   and when a positively-identified node's own text is empty,
 *   its immediate parent (one level, never MAIN/BODY) is used as
 *   the turn container (effectiveText, shared by assistant
 *   replies and user messages). The parent is only ever reached
 *   from an already-identified node, so the sender is never
 *   guessed from an article. doReadLatest also retries briefly
 *   (up to 3s) when no assistant node is found on the first
 *   check — the reply may still be rendering; the retry only
 *   ever accepts a positively-identified assistant node.
 *   NOTE (ROUND 22): no real reply-node DOM structure has been
 *   collected for independent confirmation yet — these are
 *   precise suspected locations, not verified final root causes.
 *   Real-page verification needs ATTEMPT-08.
 * - DEFECT 3 (B4 minimised background send unstable) + P2 (real
 *   send): doSend() used to fail immediately when the send button
 *   was disabled at the start — but the button is disabled while
 *   the composer is empty, which is normal, not streaming — and
 *   it clicked immediately after setting the composer, before
 *   React had synced the input state (the button could still be
 *   disabled, or the app had not registered the text). Now:
 *   the pre-send streaming check uses the stop button only
 *   (a definitive streaming signal); after setting the composer
 *   it WAITS for the send button to appear and become usable
 *   (up to 5s, on actual DOM state) before the single click;
 *   setComposerValue dispatches a proper InputEvent
 *   (inputType "insertText") when available, falling back to
 *   Event, plus a change event for textarea/input. Background
 *   DOM only — still no focus, no activation, no system input.
 *   The longer 10s confirmation timeout also covers the timer
 *   throttling of a minimised tab. (P2-C, background.js: the
 *   tab a command is routed to is now BOUND to the discussion
 *   session — see background.js — so a later round cannot go
 *   to the wrong tab when several tabs of the same site are
 *   open; this is what GATE-SEAMLESS-CONTINUITY needs.)
 *
 * RC4-HOTFIX5 (ATTEMPT-08, 2026-11-20 22:54): the Hotfix4 doSend
 * order fix did NOT fix B2 — the real send still failed. The text
 * stayed in the composer, the result was send_unconfirmed
 * (UNCERTAIN), and the Adapter timed out. Diagnosis from the
 * evidence: waitForSendButton resolved "whatever button exists"
 * at its deadline, INCLUDING a disabled button, and doSend clicked
 * it — but a click on a disabled button is a DOM no-op, so
 * nothing was submitted and confirmation timed out as UNCERTAIN
 * instead of an honest not_sent. Fix: (1) waitForSendButton never
 * resolves a disabled button (null at the deadline); (2) doSend
 * verifies the fill took immediately after setComposerValue and
 * fails fast with composer_input_not_accepted instead of waiting
 * 5s for a button that can never enable; (3) when no enabled
 * button appears, doSend distinguishes composer reverted
 * (composer_input_not_accepted), button exists but never enabled
 * (new error send_button_never_enabled — the ATTEMPT-08 failure
 * mode), and no button at all
 * (send_button_missing_after_input). All three are
 * DEFINITELY_NOT_SENT in adapter.py: we never clicked, so the
 * message was definitely not sent. The deeper "why didn't the
 * page register the input" is NOT proven from the evidence (no
 * real page DOM was collected) and is diagnosed honestly through
 * these distinct errors in ATTEMPT-09 — not by speculating about
 * a beforeinput event (deliberately NOT added: it could duplicate
 * text in a contenteditable editor, and there is no evidence the
 * page gates on it).
 *
 * LEAST PRIVILEGE (condition 1):
 * - No file access, no system commands, no approval-release permission.
 * - Page content is ALWAYS untrusted data: it is only read and reported,
 *   never eval()ed, never executed, never inserted as HTML.
 * - Never calls focus() / window.focus(), never uses system keyboard or
 *   mouse input, never activates the tab. Sending is DOM-level fill +
 *   DOM-level click only. If sending would need activation, it reports
 *   failure instead of activating.
 * - Provenance is bound to the page origin: a reply read from the
 *   chatgpt.com tab is sender=chatgpt because it came from that origin,
 *   not because a sender field said so (Security-2b).
 *
 * SELECTORS ARE FRAGILE: chatgpt.com / muse.ai change their DOM. The
 * selectors below are best-effort with fallbacks; the adapter runs a health
 * check before every send and stops (never forces a send) when a selector
 * no longer matches. Real-Chrome end-to-end load testing has NOT been done
 * here (no Windows Chrome in this environment) — see KNOWN-LIMITATIONS.md.
 */

(function () {
  "use strict";

  var SITE = window.location.hostname;
  var IS_CHATGPT = SITE.indexOf("chatgpt.com") !== -1;
  var IS_MUSE = SITE.indexOf("muse.ai") !== -1;

  // --- selectors (best-effort, with fallbacks) ---------------------------
  function first(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var el = document.querySelector(selectors[i]);
      if (el) return el;
    }
    return null;
  }

  function all(selectors) {
    var out = [];
    for (var i = 0; i < selectors.length; i++) {
      var nodes = document.querySelectorAll(selectors[i]);
      for (var j = 0; j < nodes.length; j++) out.push(nodes[j]);
    }
    return out;
  }

  // --- multi-strategy message recognition (HOTFIX 6, B2/B3) ----------
  // One querySelectorAll with a comma-joined selector returns nodes
  // in document order in a real DOM. Dedupe by identity (a node
  // can match several strategies).
  function queryUnion(selectors) {
    var nodes = document.querySelectorAll(selectors.join(", "));
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      if (out.indexOf(nodes[i]) === -1) out.push(nodes[i]);
    }
    return out;
  }

  function nodeDomId(el) {
    if (!el) return null;
    var id = null;
    try { id = el.getAttribute(TURN_ID_ATTR); } catch (e) { id = null; }
    if (id) return id;
    return el.id || null;
  }

  // The role-identifying attribute value on this node, if any.
  function roleAttrOf(el) {
    if (!el || !el.getAttribute) return null;
    for (var i = 0; i < ROLE_ATTRS.length; i++) {
      var v = null;
      try { v = el.getAttribute(ROLE_ATTRS[i]); } catch (e) { v = null; }
      if (v) return { attr: ROLE_ATTRS[i], value: v };
    }
    return null;
  }

  // Attribute NAMES only (never values, except role values via
  // roleAttrOf). Used by the diagnostic inventory.
  function attributeNames(el) {
    if (!el) return [];
    if (typeof el.getAttributeNames === "function") {
      try { return el.getAttributeNames(); } catch (e) { /* fall through */ }
    }
    var known = [TURN_ID_ATTR, "id", "class", "data-testid",
                 "data-message-author-role", "data-author-role",
                 "data-role", "data-sender"];
    var out = [];
    for (var i = 0; i < known.length; i++) {
      var v = null;
      try { v = el.getAttribute(known[i]); } catch (e) { v = null; }
      if (v !== null && v !== undefined) out.push(known[i]);
    }
    return out;
  }

  // The turn container of a role-marked node: the nearest
  // ancestor-or-self carrying a data-message-id, or an ARTICLE.
  // The role attribute may sit on a child of the turn (an inner
  // marker) or on a wrapper around it; the turn container is what
  // carries the message text.
  function turnContainerOf(node) {
    var el = node;
    while (el) {
      if (el.getAttribute) {
        var id = null;
        try { id = el.getAttribute(TURN_ID_ATTR); } catch (e) { id = null; }
        if (id) return el;
      // Verified DIL turn boundary.
      if (el.getAttribute("data-content-search-unit-key")) return el;
      }
      if (el.tagName && el.tagName.toUpperCase() === "ARTICLE") return el;
      el = el.parentElement;
    }
    return node;
  }

  // Authorship evidence on the actual ChatGPT DIL message unit:
  // the screen-reader heading must be a DIRECT child (not quoted content).
  function hasDirectConversationRole(turn, expected) {
    if (!turn || !turn.children) return false;
    var key = turn.getAttribute && turn.getAttribute("data-content-search-unit-key");
    if (!key || key.slice(-(expected.length + 1)) !== ":" + expected) return false;
    for (var k = 0; k < turn.children.length; k++) {
      var child = turn.children[k];
      if (child && child.tagName && child.tagName.toUpperCase() === "H4" &&
          child.getAttribute && child.getAttribute("data-conversation-role") === expected) return true;
    }
    return false;
  }

  // Strategy 1+2: nodes carrying a role attribute (primary, then
  // alternate attribute names), resolved to their turn containers.
  function roleTurnEls(primarySelectors, altSelectors) {
    var nodes = queryUnion(primarySelectors.concat(altSelectors));
    var turns = [];
    for (var i = 0; i < nodes.length; i++) {
          var ownRole = nodes[i].getAttribute && nodes[i].getAttribute("data-message-role");
    var ownSide = nodes[i].getAttribute && nodes[i].getAttribute("data-message-side");
    var museExact = IS_MUSE && nodes[i].getAttribute("data-message-item") === "true" &&
      ((ownRole === "assistant" && ownSide === "agent") ||
       (ownRole === "user" && ownSide === "user"));
    var turn = museExact ? nodes[i] : turnContainerOf(nodes[i]);
    var markerRole = nodes[i].getAttribute && nodes[i].getAttribute("data-conversation-role");
    if (markerRole) {
      // A quoted author marker inside message content must not become authority.
      var unitKey = turn && turn.getAttribute && turn.getAttribute("data-content-search-unit-key");
      if (!unitKey || unitKey.slice(-(markerRole.length + 1)) !== ":" + markerRole ||
          !hasDirectConversationRole(turn, markerRole)) continue;
    }
    if (turns.indexOf(turn) === -1) turns.push(turn);
      if (turns.indexOf(turn) === -1) turns.push(turn);
    }
    return turns;
  }

  // Every message turn in the conversation, in document order.
  function allTurnEls() {
    return queryUnion([TURN_ID_SELECTOR]);
  }

  // Positive user identification: a user role marker on the turn
  // or any ancestor.
  function isUserTurn(el) {
    if (hasDirectConversationRole(el, "user")) return true;
    var node = el;
    while (node) {
      var role = roleAttrOf(node);
      if (role && role.value === "user") return true;
      node = node.parentElement;
    }
    return false;
  }

  function isAssistantTurn(el) {
    if (hasDirectConversationRole(el, "assistant")) return true;
    var node = el;
    while (node) {
      var role = roleAttrOf(node);
      if (role && role.value === "assistant") return true;
      node = node.parentElement;
    }
    return false;
  }

  // The user turn confirmed by the most recent successful send in
  // this content-script session, and the text that was sent. Used
  // as the anchor for the turn-after-user-turn assistant fallback
  // (B3), and to reject a turn that merely echoes the sent text
  // (a user message rendered without any role marker must never
  // be reported as an assistant reply - the Hotfix2 error).
  var lastConfirmedUserTurn = null;
  var lastSentText = null;

  // User-turn candidates, in order:
  //  S1/S2 role-attribute turns (primary + alternate attribute
  //        names), resolved to their turn containers;
  //  S3 text-anchored turns: a turn whose text contains the sent
  //       text and which is NOT an assistant turn. (Before the
  //       send this finds old duplicates of the text, which the
  //       snapshot must contain so they are never mistaken for
  //       the new message.)
  // Returns [{el, strategy}]. A turn only counts when it is
  // positively identified - never "any new node".
  function userCandidates(text) {
    var out = [];
    var seen = [];
    var roleTurns = roleTurnEls(USER_ROLE_SELECTORS,
                                USER_ROLE_ALT_SELECTORS);
    for (var i = 0; i < roleTurns.length; i++) {
      out.push({ el: roleTurns[i], strategy: "role_attribute" });
      seen.push(roleTurns[i]);
    }
    if (text && !IS_CHATGPT) {
      var want = normText(text);
      var turns = allTurnEls();
      for (var j = 0; j < turns.length; j++) {
        var turn = turns[j];
        if (seen.indexOf(turn) !== -1) continue;
        if (isAssistantTurn(turn)) continue;
        if (normText(effectiveText(turn)).indexOf(want) !== -1) {
          out.push({ el: turn, strategy: "text_anchor" });
          seen.push(turn);
        }
      }
    }
    return out;
  }

  // Assistant-turn candidates, in order:
  //  S1/S2 role-attribute turns (primary + alternate attribute
  //        names), resolved to their turn containers;
  //  S3 turn-after-user-turn: only when S1/S2 find NOTHING, the
  //       turn after the last positively-identified user turn (a
  //       confirmed send, else a role-identified user turn) is
  //       the reply to it. The turn must not itself be a user turn
  //       and must have text. This is the only fallback, and it is
  //       anchored on a confirmed user turn - it never treats an
  //       arbitrary last article as a reply (the Hotfix2 error).
  // Returns [{el, strategy}].
  function assistantCandidates() {
    // Muse: a historical assistant role is not a receipt for this send.
    if (!IS_CHATGPT && !lastConfirmedUserTurn) return [];
    var out = [];
    var roleTurns = roleTurnEls(ASSISTANT_ROLE_SELECTORS,
                                ASSISTANT_ROLE_ALT_SELECTORS);
    for (var i = 0; i < roleTurns.length; i++) {
            var unit = roleTurns[i];
      var body = hasDirectConversationRole(unit, "assistant") && unit.querySelector
        ? unit.querySelector("[data-response-body]") : null;
      out.push({ el: body || unit, strategy: "role_attribute" });
    }
    // Run 54998652: data-response-body bounds content, not authorship.
    // data-turn-key contains both user and reply; never promote it to
    // an assistant message boundary. Exact text/order is insufficient.
    // Adjacency alone cannot establish ChatGPT assistant authorship.
    var bubbles = observedUserBubbles();
    if (bubbles.length) {
      var current = bubbles[bubbles.length - 1];
      if (lastConfirmedUserTurn && lastConfirmedUserTurn !== current) return [];
      // After reload the in-memory anchor disappears. Recover only from
      // an independently role-identified latest ChatGPT user turn.
      if (!lastConfirmedUserTurn) {
        // .bg-user-message is the verified ChatGPT user-bubble class.
        // Its nested search unit does not carry the direct H4 role marker.
        // Keep independent assistant-role verification and strict ordering.
        if (!IS_CHATGPT || !current.isConnected ||
            !observedBubbleText(current) ||
            current.closest("blockquote,pre,[contenteditable]")) return [];
      }
      return out.filter(function (candidate) {
        // FOLLOWING (4) without CONTAINED_BY (16): a separate later turn.
        var order = current.compareDocumentPosition(candidate.el);
        return (order & 4) !== 0 && (order & (1 | 16)) === 0;
      });
    }
    if (out.length || IS_CHATGPT) return out;
    var anchor = lastConfirmedUserTurn;
    if (!anchor && !IS_CHATGPT) return out;
    if (!anchor) {
      var userTurns = roleTurnEls(USER_ROLE_SELECTORS,
                                  USER_ROLE_ALT_SELECTORS);
      if (userTurns.length) anchor = userTurns[userTurns.length - 1];
    }
    if (!anchor) return out;
    var turns = allTurnEls();
    var idx = turns.indexOf(anchor);
    if (idx === -1 || idx + 1 >= turns.length) return out;
    var next = turns[idx + 1];
    if (isUserTurn(next)) return out;
    if (!effectiveText(next)) return out;
    // A turn that merely echoes the text just sent is the user's
    // own message, not a reply (it may be rendered without any
    // role marker). Rejecting it is a safe false negative; the
    // reply that quotes the user is the only casualty, and it is
    // still found by the role-attribute strategies.
    if (lastSentText &&
        normText(effectiveText(next)).indexOf(normText(lastSentText)) !== -1) {
      return out;
    }
    out.push({ el: next, strategy: "after_user_turn" });
    return out;
  }

  function visibilityState() {
    try {
      return document.visibilityState || "unknown";
    } catch (e) {
      return "unknown";
    }
  }

  // De-sensitized inventory of the candidate turns observed, for
  // diagnosis when every recognition strategy fails. NEVER message
  // content, NEVER personal data: only tag names, attribute NAMES,
  // role-identifying attribute VALUES, message-id presence, text
  // LENGTH, class patterns, and container depth. The coordinator
  // can capture this from ATTEMPT-10 and the next fix can target
  // the real structure exactly.
  function diagnoseRecognition(kind) {
    var turns = allTurnEls();
    var roleCounts = {
      user_primary: all(USER_ROLE_SELECTORS).length,
      user_alt: all(USER_ROLE_ALT_SELECTORS).length,
      assistant_primary: all(ASSISTANT_ROLE_SELECTORS).length,
      assistant_alt: all(ASSISTANT_ROLE_ALT_SELECTORS).length
    };
    var inventory = [];
    var start = Math.max(0, turns.length - DIAG_INVENTORY_MAX);
    for (var i = start; i < turns.length; i++) {
      var el = turns[i];
      var role = roleAttrOf(el);
      var cls = "";
      try { cls = el.getAttribute("class") || ""; } catch (e) { cls = ""; }
      var depth = 0;
      var node = el.parentElement;
      while (node && node.tagName) {
        var tag = node.tagName.toUpperCase();
        if (tag === "MAIN" || tag === "BODY" || tag === "HTML") break;
        depth++;
        if (depth >= 12) break;
        node = node.parentElement;
      }
      inventory.push({
        tag: el.tagName || null,
        attrs: attributeNames(el),
        role: role ? role.value : null,
        has_message_id: nodeDomId(el) !== null,
        text_len: effectiveText(el).length,
        cls: cls ? cls.split(/\s+/).slice(0, 4) : [],
        depth: depth
      });
    }
    return {
      kind: kind,
      strategies_tried: kind === "user"
        ? ["role_attribute", "text_anchor"]
        : ["role_attribute", "after_user_turn"],
      turn_count: turns.length,
      role_node_counts: roleCounts,
      reply_debug: kind !== "assistant" ? null : (function () {
        var bubbles = observedUserBubbles();
        var current = bubbles[bubbles.length - 1] || null;
        var unit = current && current.closest("[data-content-search-unit-key]");
        var roles = roleTurnEls(ASSISTANT_ROLE_SELECTORS, ASSISTANT_ROLE_ALT_SELECTORS);
        return {bubble_count: bubbles.length, anchor_present: !!lastConfirmedUserTurn,
          latest_user_role_verified: !!unit && hasDirectConversationRole(unit, "user"),
          role_turn_count: roles.length, candidate_count: assistantCandidates().length,
          verified_user_turns: roleTurnEls(USER_ROLE_SELECTORS, USER_ROLE_ALT_SELECTORS).length,
          containing_verified_user_turns: current ? roleTurnEls(USER_ROLE_SELECTORS, USER_ROLE_ALT_SELECTORS).filter(function (t) { return t.contains(current) && hasDirectConversationRole(t, "user"); }).length : 0,
          last_verified_user_contains: current ? (function () { var u=roleTurnEls(USER_ROLE_SELECTORS, USER_ROLE_ALT_SELECTORS); return !!u.length && u[u.length-1].contains(current); })() : false,
          following_role_count: current ? roles.filter(function (el) {
            var flags = current.compareDocumentPosition(el);
            return (flags & 4) !== 0 && (flags & (1 | 16)) === 0;
          }).length : 0};
      })(),
      inventory: inventory
    };
  }

  // ChatGPT composer (2026-11): textarea#prompt-textarea; fallback: any
  // contenteditable in the composer form.
  var COMPOSER_SELECTORS = IS_CHATGPT
    ? ["#prompt-textarea", "form textarea", "[contenteditable='true']"]
    : ["textarea", "[contenteditable='true']"];
  // ChatGPT send button; fallback: the submit button inside the composer form.
  // HOTFIX 4 (P2-A): the send button is DYNAMIC — it does not exist
  // while the composer is empty and only appears after text is typed
  // (ATTEMPT-07). SEND_SELECTORS may not cover the current button, so
  // an aria-label fallback is added; the button is always looked up
  // AFTER setComposerValue, never before (see doSend).
  var SEND_SELECTORS = IS_CHATGPT
    ? ["button[data-testid='send-button']",
       "button[data-testid='composer-send-button']",
       "button[aria-label='Send message']",
       "button[aria-label='发送消息']",
       "button[aria-label='Send prompt']",
       "button[aria-label='发送']",
       "button[aria-label='Send']",
       "form button[type='submit']"]
    : ["button[aria-label='发送']", "button[aria-label='Send']", "button[type='submit']", "form button"];
  // ChatGPT stop button (present while a reply is streaming).
  var STOP_SELECTORS = IS_CHATGPT
    ? ["button[data-testid='stop-button']", "button[aria-label='停止']", "button[aria-label='停止生成']", "button[aria-label='Stop']", "button[aria-label='Stop generating']"]
    : [];
  // Assistant reply blocks. HOTFIX 2 (TASK 1): ONLY nodes that
  // positively identify as assistant replies. The generic "article"
  // fallback is REMOVED for both ChatGPT and Muse — a user message
  // rendered as an <article> could be the last block, and
  // latestReply() would then report it as sender:"chatgpt". If no
  // positively-identified assistant node exists, latestReply()
  // returns null and read_latest reports found:false — NEVER guess.
  // If this selector stops matching the page, reads degrade to
  // "not found" (safe) instead of being confirmed on a guess.
  var REPLY_SELECTORS = ["[data-message-author-role='assistant']"];
  var ASSISTANT_ROLE_SELECTORS = REPLY_SELECTORS;
  var ASSISTANT_ROLE_ALT_SELECTORS = [
    "[data-author-role='assistant']",
    "[data-role='assistant']",
    "[data-sender='assistant']",
    "[data-conversation-role='assistant']",
    "[data-message-role='assistant']"
  ];
  // User message blocks (the message we just sent). Used only to confirm
  // delivery: the sent text must appear here before a send counts as
  // MESSAGE_SENT. If this selector stops matching the page, sends degrade
  // to UNCERTAIN (safe) instead of being confirmed on a guess.
  var USER_SELECTORS = ["[data-message-author-role='user']"];
  var USER_ROLE_SELECTORS = USER_SELECTORS;
  var USER_ROLE_ALT_SELECTORS = [
    "[data-author-role='user']",
    "[data-role='user']",
    "[data-sender='user']",
    "[data-conversation-role='user']",
    "[data-message-role='user']"
  ];
  // HOTFIX 6 (B2/B3): recognition must not depend on a single
  // selector. ATTEMPT-09 showed the adapter reporting
  // send_unconfirmed / found=false while the two test messages
  // were present on the page (confirmed via the accessibility
  // tree). The role selectors below are UNVERIFIED hypotheses
  // (round 25): the raw HTML DOM was never collected, so no claim
  // is made that the page lacks these attributes - the failure
  // could be the selectors, the text location, or the send state
  // machine. The multi-strategy recognition is a robustness
  // fallback: it only ADDS candidates when the primary finds
  // nothing, and a node still only counts when it is POSITIVELY
  // identified (role marker, or turn identity + content match) -
  // never "any new node". The collector (doCollectDom) is the
  // instrument that determines the real structure in ATTEMPT-10;
  // until its JSON arrives, no selector is declared broken.
  var TURN_ID_SELECTOR = "[data-message-id], [data-content-search-unit-key]";
  var TURN_ID_ATTR = "data-message-id";
  var ROLE_ATTRS = [
    "data-message-author-role", "data-author-role", "data-role",
    "data-sender", "data-conversation-role", "data-message-role"
  ];
  var DIAG_INVENTORY_MAX = 8;

  var REPLY_SETTLE_MS = 3000; // no DOM mutations for this long = settled
  // Send confirmation: wait this long for the sent message to appear in
  // the chat history (composer cleared AND message in the DOM).
  // HOTFIX 4 (DEFECT 1 + DEFECT 3): 5s was too short for a slow page
  // render and for a minimised tab whose timers are throttled — the
  // message was sent and the AI replied, but confirmation gave up
  // first and reported send_unconfirmed. 10s is still well inside
  // the adapter's 60s send timeout. A genuinely failed send now
  // takes up to 10s to report UNCERTAIN (slower feedback, but a
  // sent message is no longer misjudged).
  var SEND_CONFIRM_TIMEOUT_MS = 10000;
  var SEND_CONFIRM_POLL_MS = 100;
  // Send-button appearance: after the composer is filled, wait this
  // long for the send button to APPEAR and become enabled before
  // clicking (HOTFIX 4, P2-A). The button does not exist while the
  // composer is empty — it only appears after text is typed — so the
  // wait is on actual DOM state (button present and enabled), never
  // a fixed delay. 5s covers a slow React render; a longer wait
  // would only delay an honest not_sent failure.
  var SEND_BUTTON_TIMEOUT_MS = 5000;
  // HOTFIX 6 (B4): when the tab is hidden/backgrounded (minimised
  // Chrome), the page may throttle or defer rendering, so the send
  // button can take longer to appear after input than on a visible
  // tab. ATTEMPT-09's minimised send was not resolved within the
  // 5s wait (send_button_missing_after_input) - but round 25
  // showed the input WAS accepted (the text stayed in the input
  // box) and the button was visible after the tab was restored, so
  // it is UNPROVEN whether the button never renders, renders late,
  // or renders disabled while minimised. The longer bound (10s,
  // twice the visible bound) is a bound on a state-based wait,
  // not a fix by itself: the button_timeline recorded by doSend
  // is what distinguishes the four cases (never appeared /
  // appeared but disabled / appeared then disappeared / state
  // sync too slow). The tab is never activated (GATE-NO-FOCUS).
  var HIDDEN_BUTTON_TIMEOUT_MS = 10000;
  var INPUT_SYNC_POLL_MS = 50;
  // HOTFIX 4 (P2-B): how long doReadLatest retries when no assistant
  // reply node is found on the first check. The reply may still be
  // rendering; a single immediate check can miss it (ATTEMPT-07).
  var READ_RETRY_TIMEOUT_MS = 3000;
  var READ_RETRY_POLL_MS = 200;

  // --- helpers ------------------------------------------------------------
  function sha256Hex(text) {
    if (window.crypto && window.crypto.subtle && window.crypto.subtle.digest) {
      var data = new TextEncoder().encode(text);
      return window.crypto.subtle.digest("SHA-256", data).then(function (buf) {
        return Array.prototype.map
          .call(new Uint8Array(buf), function (b) {
            return ("00" + b.toString(16)).slice(-2);
          })
          .join("");
      });
    }
    // No subtle crypto (non-secure context): report the hash as unavailable
    // rather than faking one. The coordinator re-hashes on receipt.
    return Promise.resolve(null);
  }

  // --- text helpers (HOTFIX 4) -------------------------------------------
  // Normalise whitespace so a text match does not fail when the page
  // re-renders the sent text with different spacing / line breaks.
  function normText(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }

  // Rendered text of a node: innerText when present (what the user
  // sees), else textContent. innerText can be empty while the text is
  // present (rendering state / hidden ancestor); textContent is not
  // affected by visibility. HOTFIX 4 (DEFECT 2): read_latest missed
  // a reply that was on the page because it only looked at innerText.
  function nodeText(el) {
    if (!el) return "";
    var t = "";
    if (typeof el.innerText === "string") t = el.innerText;
    if (!t || !t.trim()) {
      if (typeof el.textContent === "string") t = el.textContent;
    }
    return (t || "").trim();
  }

  function replyBlocks() {
    // A block counts when its EFFECTIVE text is non-empty — its own
    // text, or (HOTFIX 4, DEFECT 2) its turn container's text when
    // the role attribute sits on an empty wrapper. HOTFIX 6: the
    // candidates come from the multi-strategy recognition
    // (role attribute, alternate attributes, turn-after-user-turn),
    // not a single selector.
    return assistantCandidates().filter(function (c) {
      return c.el && effectiveText(c.el).length > 0;
    }).map(function (c) { return c.el; });
  }

  // Effective text of a positively-identified message node
  // (assistant OR user). If the role attribute sits on a wrapper
  // whose own text is empty, the message text lives in the turn
  // container — use the immediate parent (one level only, never
  // MAIN/BODY/HTML). The parent is only ever reached from an
  // already-identified node, so the sender is never guessed from an
  // arbitrary article (the generic "article" fallback stays removed
  // — HOTFIX 2). Used for both assistant replies and user messages.
  function effectiveText(el) {
    var text = nodeText(el);
    if (text) return text;
    var parent = el && el.parentElement;
    if (!parent || !parent.tagName) return "";
    var tag = parent.tagName.toUpperCase();
    if (tag === "MAIN" || tag === "BODY" || tag === "HTML") return "";
    return nodeText(parent);
  }

  function latestReply() {
    var cands = assistantCandidates().filter(function (c) {
      return c.el && effectiveText(c.el).length > 0;
    });
    if (!cands.length) return null;
    var last = cands[cands.length - 1];
    return {
      text: effectiveText(last.el),
      // A stable-ish id: prefer a DOM id, else the content hash (set below).
      dom_id: nodeDomId(last.el),
      strategy: last.strategy,
    };
  }

  function isStreaming() {
    if (first(STOP_SELECTORS)) return true;
    var send = first(SEND_SELECTORS);
    if (send && send.disabled) return true;
    return false;
  }

  // Definitive streaming signal: the stop button is present. Unlike
  // isStreaming(), this does NOT treat a disabled send button as
  // streaming — the button is disabled while the composer is empty,
  // which is normal, not streaming. HOTFIX 4 (DEFECT 1): the
  // corroborating delivery signal uses this only.
  function replyStreaming() {
    return !!first(STOP_SELECTORS);
  }

  function composer() {
    return first(COMPOSER_SELECTORS);
  }

  function sendButton() {
    return first(SEND_SELECTORS);
  }

  // --- completion detection ------------------------------------------------
  // Watches the chat container for mutations. When nothing changes for
  // REPLY_SETTLE_MS and no stop button is present, the reply is complete.
  var settleTimer = null;
  var observing = false;
  var lastReportedHash = null;

  function startCompletionWatch() {
    if (observing) return;
    var container =
      document.querySelector("main") || document.body;
    if (!container || !window.MutationObserver) return;
    observing = true;
    var observer = new MutationObserver(function () {
      if (settleTimer) clearTimeout(settleTimer);
      settleTimer = setTimeout(function () {
        if (isStreaming()) return; // still going; keep watching
        var latest = latestReply();
        if (!latest) return;
        sha256Hex(latest.text).then(function (hash) {
          if (hash && hash === lastReportedHash) return;
          lastReportedHash = hash;
          chrome.runtime.sendMessage({
            type: "reply_complete",
            origin: window.location.origin,
            sender: IS_CHATGPT ? "chatgpt" : IS_MUSE ? "muse" : "unknown",
            dom_id: latest.dom_id,
            content: latest.text,
            content_sha256: hash,
            content_len: latest.text.length,
          });
        });
      }, REPLY_SETTLE_MS);
    });
    observer.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  // --- actions --------------------------------------------------------------
  function setComposerValue(el, text) {
    // React-controlled inputs need the native setter + an input event,
    // otherwise the app never sees the change. HOTFIX 4 (P2): dispatch
    // a proper InputEvent (inputType "insertText") when the page
    // provides it — some editors ignore a plain Event — and fall back
    // to Event. For textarea/input also fire a change event so
    // frameworks listening to change pick the value up.
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      var proto = el.tagName === "TEXTAREA"
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      var desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) {
        desc.set.call(el, text);
      } else {
        el.value = text;
      }
    } else {
      // RC14: ChatGPT uses a stateful contenteditable editor. Assigning
      // textContent and dispatching an untrusted synthetic input event only
      // changes the DOM; React may never enable its real send control.
      // A browser-native editing transaction emits the editor's input
      // pathway. If unavailable, fail closed: NEVER click and NEVER claim sent.
      if (!el.isContentEditable &&
          el.getAttribute("contenteditable") !== "true") {
        throw new Error("rich_editor_not_editable");
      }
      if (!document.execCommand || !document.createRange ||
          !window.getSelection) {
        throw new Error("rich_editor_native_input_unsupported");
      }
      var sel = window.getSelection();
      if (!sel) throw new Error("rich_editor_selection_missing");
      var range = document.createRange();
      range.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(range);
      if (!document.execCommand("insertText", false, text)) {
        throw new Error("rich_editor_native_insert_rejected");
      }
      // execCommand delivers the native input event. Avoid a second,
      // artificial input notification which could re-enter the editor.
      return;
    }
    var inputEvent;
    if (typeof window.InputEvent === "function") {
      try {
        inputEvent = new window.InputEvent("input", {
          bubbles: true, cancelable: true, inputType: "insertText",
          data: text,
        });
      } catch (e) {
        inputEvent = null;
      }
    }
    el.dispatchEvent(inputEvent ||
      new Event("input", { bubbles: true }));
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  // Does the composer currently hold the text we set? (Normalised
  // comparison — the page may re-render the text with different
  // spacing.) Used to confirm the input state synced before clicking.
  function composerHasText(comp, text) {
    if (!comp) return false;
    if (comp.tagName === "TEXTAREA" || comp.tagName === "INPUT") {
      return normText(comp.value) === normText(text);
    }
    // Rich editors can represent inserted newlines as sibling blocks.
    // textContent concatenates block text without separators, while
    // innerText retains the visible line breaks. Require complete
    // normalized text equality in at least one representation.
    return ((typeof comp.innerText === "string" &&
             normText(comp.innerText) === normText(text)) ||
            normText(comp.textContent) === normText(text));
  }

  function doHealth(nonce) {
    // FIX 1 (P0): echo the request nonce so adapter.py _wait_outbox()
    // can match this reply to the health command that asked for it.
    var comp = composer();
    var send = sendButton();
    return {
      type: "health_result",
      origin: window.location.origin,
      nonce: nonce || null,
      // HOTFIX 4 (P2-A): ok means the page is ready for a send. The
      // send button does NOT exist while the composer is empty — it
      // only appears after text is typed — so its absence when the
      // composer is empty is normal, not a failure. ok therefore
      // requires only the composer; send_button_found stays
      // informational (true once the composer holds text).
      ok: !!comp,
      composer_found: !!comp,
      send_button_found: !!send,
      streaming: isStreaming(),
    };
  }

  function doReadLatest(nonce) {
    // FIX 1 (P0): echo the request nonce in both outcomes.
    // HOTFIX 4 (P2-B): retry briefly. A single immediate check can
    // miss a reply that is still rendering — the ATTEMPT-07 page
    // showed the AI reply, yet one read returned found:false.
    // The retry only ever accepts a positively-identified assistant
    // node (latestReply); it never relaxes identification.
    return new Promise(function (resolve) {
      var deadline = Date.now() + READ_RETRY_TIMEOUT_MS;
      (function poll() {
        var latest = latestReply();
        if (!latest) {
          if (Date.now() >= deadline) {
            // HOTFIX 6: attach the de-sensitized diagnostic
            // inventory (what recognition observed) so ATTEMPT-10
            // can capture the real structure instead of guessing.
            resolve({
              type: "read_result",
              origin: window.location.origin,
              nonce: nonce || null,
              found: false,
              diagnostics: diagnoseRecognition("assistant"),
            });
            return;
          }
          setTimeout(poll, READ_RETRY_POLL_MS);
          return;
        }
        sha256Hex(latest.text).then(function (hash) {
          resolve({
            type: "read_result",
            origin: window.location.origin,
            nonce: nonce || null,
            found: true,
            sender: IS_CHATGPT ? "chatgpt" : IS_MUSE ? "muse" : "unknown",
            dom_id: latest.dom_id,
            content: latest.text,
            content_sha256: hash,
            content_len: latest.text.length,
            streaming: replyStreaming(),
            strategy: latest.strategy || null,
          });
        });
      })();
    });
  }

  // --- de-sensitized DOM collector (HOTFIX 6, ROUND 25) ------------
  // Optional read-only diagnostic mode. ChatGPT could not obtain the
  // raw HTML DOM in round 25 (the accessibility tree proves the two
  // test messages exist, but not the HTML tags/attributes), so it
  // supplied this collector (ported verbatim in structure, adapted
  // to this file's style). It runs in the page, matches the two
  // known test messages, and returns ONLY de-sensitized structure:
  // whether each marker was found, how many nodes the role
  // selectors match, and the tag / role / testid / class / parent
  // chain of the two matched nodes (up to 12 levels). NO message
  // content, NO cookie, NO token, NO URL, NO real message id, NO
  // network upload, NO extra window, and it does not read the whole
  // history - only the two marker nodes and the role-selector
  // counts. Key diagnostic: user_found=true with
  // role_selector_counts.user=0 is direct evidence the user role
  // selector is broken; same for assistant. This is how ATTEMPT-10
  // captures the real structure so the next fix can target it
  // exactly, instead of guessing DOM structure to change code.
  function collectMatchingLeaf(root, marker, exact) {
    var allEls = (root && typeof root.querySelectorAll === "function")
      ? root.querySelectorAll("*") : document.querySelectorAll("*");
    var want = normText(marker);
    var matches = [];
    for (var i = 0; i < allEls.length; i++) {
      var t = normText(nodeText(allEls[i]));
      var ok = exact ? t === want : t.indexOf(want) !== -1;
      if (ok) matches.push(allEls[i]);
    }
    // The leaf: a match that is not an ancestor of any other match.
    for (var j = 0; j < matches.length; j++) {
      var candidate = matches[j];
      var isAncestor = false;
      for (var k = 0; k < matches.length; k++) {
        if (j === k) continue;
        var node = matches[k].parentElement;
        while (node) {
          if (node === candidate) { isAncestor = true; break; }
          node = node.parentElement;
        }
        if (isAncestor) break;
      }
      if (!isAncestor) return candidate;
    }
    return null;
  }

  function collectNodeStructure(el, root) {
    var rows = [];
    for (var level = 0; el && level < 12; level++, el = el.parentElement) {
      var testId = null;
      var role = null;
      var authorRole = null;
      var hasMessageId = false;
      var hasTurnId = false;
      var hasId = false;
      var classes = [];
      try { testId = el.getAttribute("data-testid"); } catch (e) { /* ignore */ }
      try { role = el.getAttribute("role"); } catch (e) { /* ignore */ }
      try { authorRole = el.getAttribute("data-message-author-role"); } catch (e) { /* ignore */ }
      try { hasMessageId = el.hasAttribute("data-message-id"); } catch (e) { /* ignore */ }
      try { hasTurnId = el.hasAttribute("data-turn-id"); } catch (e) { /* ignore */ }
      try { hasId = el.hasAttribute("id"); } catch (e) { /* ignore */ }
      try {
        if (el.classList) {
          for (var c = 0; c < el.classList.length && classes.length < 12; c++) {
            var cls = el.classList[c];
            if (cls && cls.length <= 60) classes.push(cls);
          }
        }
      } catch (e) { /* ignore */ }
      rows.push({
        level: level,
        tag: el.tagName ? el.tagName.toLowerCase() : null,
        role: role,
        authorRole: authorRole,
        testId: testId,
        hasMessageId: hasMessageId,
        hasTurnId: hasTurnId,
        hasId: hasId,
        classes: classes,
      });
      if (el === root) break;
    }
    return rows;
  }

  function doCollectDom(userMarker, assistantMarker, nonce) {
    var root = document.querySelector("main") || document.body;
    function countInRoot(sel) {
      try {
        if (root && typeof root.querySelectorAll === "function") {
          return root.querySelectorAll(sel).length;
        }
      } catch (e) { /* fall through to document scope */ }
      return document.querySelectorAll(sel).length;
    }
    var user = userMarker
      ? collectMatchingLeaf(root, userMarker, false) : null;
    var assistant = assistantMarker
      ? collectMatchingLeaf(root, assistantMarker, true) : null;
    return {
      type: "collect_dom_result",
      origin: window.location.origin,
      nonce: nonce || null,
      ok: true,
      user_found: !!user,
      assistant_found: !!assistant,
      role_selector_counts: {
        user: countInRoot("[data-message-author-role='user']"),
        assistant: countInRoot("[data-message-author-role='assistant']"),
      },
      user_structure: user ? collectNodeStructure(user, root) : [],
      assistant_structure: assistant
        ? collectNodeStructure(assistant, root) : [],
    };
  }

  // --- send confirmation (FIX 4, hardened in HOTFIX 2, HOTFIX 3,
  // HOTFIX 4) ------
  // MESSAGE_SENT means: delivery is confirmed after send.click().
  // HOTFIX 4 adds a second, corroborating confirmation path: the
  // composer cleared AND the AI started replying (stop button, or a
  // new assistant reply block) — the AI can only reply to a
  // delivered message. HOTFIX 2 (TASK 2): the old
  // check only scanned all user blocks for indexOf(text) — if the
  // same text already existed in history and the composer cleared
  // without a new message, it still returned ok:true. Now we snapshot
  // the user blocks BEFORE the click and require a NEW node
  // containing the sent text. HOTFIX 3: newness is dom_id identity
  // ONLY — a node counts as new only when its dom_id was not in the
  // pre-send snapshot. An old node whose content changed in place
  // (same dom_id, new text) is NOT new, even though its (dom_id,
  // text) pair differs from the snapshot. The new node's
  // data-message-id (when present) is bound and reported as
  // message_id. If only the old identical text exists with no new
  // node → UNCERTAIN, never auto-resend. It is NOT the AI reply
  // being done — that is RESPONSE_COMPLETED, reported separately by
  // the completion watch.
  function userMessageFingerprints(text) {
    var out = [];
    var cands = userCandidates(text);
    for (var i = 0; i < cands.length; i++) {
      var el = cands[i].el;
      if (!el) continue;
      // HOTFIX 4: use effectiveText (own text, else the turn
      // container's text one level up) so a block is not dropped
      // when the role attribute sits on an empty wrapper.
      var fpText = effectiveText(el);
      // Muse may render a localised author label inside the user turn.
      // Strip ONLY a leading visible author label on a verified user-role node.
      if (!IS_CHATGPT && isUserTurn(el)) {
        fpText = fpText.replace(/^\s*(?:你|You)\s*[:：]\s*/, "");
      }
      if (!fpText) continue;
      out.push({
        dom_id: nodeDomId(el),
        text: fpText,
        el: el,
        strategy: cands[i].strategy,
      });
    }
    return out;
  }

  // Snapshot of the assistant side before the send, for the
  // corroborating delivery signal: the set of assistant dom_ids and
  // the latest reply text. A reply that appears after the click can
  // only be a response to the message just sent (doSend refuses to
  // run while a reply is already streaming).
  function assistantSnapshot() {
    var cands = assistantCandidates();
    var ids = {};
    for (var i = 0; i < cands.length; i++) {
      var id = nodeDomId(cands[i].el);
      if (id !== null) ids[id] = true;
    }
    var latest = latestReply();
    return { ids: ids, latestText: latest ? latest.text : null };
  }

  // True when a NEW assistant reply has appeared since the snapshot
  // (a new dom_id, or the latest reply text changed). HOTFIX 4
  // (DEFECT 1): corroborating delivery evidence.
  function newAssistantReplyAppeared(snap) {
    var cands = assistantCandidates();
    for (var i = 0; i < cands.length; i++) {
      var id = nodeDomId(cands[i].el);
      if (id !== null && !snap.ids[id]) return true;
    }
    var latest = latestReply();
    if (latest && latest.text !== snap.latestText) return true;
    return false;
  }

  // Find a user message node that was NOT in the snapshot and whose
  // text contains the sent text. Returns its fingerprint, or null.
  function findNewUserMessage(snapshot, text) {
    var current = userMessageFingerprints(text);
    var oldIds = {};
    var oldEls = [];
    for (var i = 0; i < snapshot.length; i++) {
      if (snapshot[i].dom_id !== null) oldIds[snapshot[i].dom_id] = true;
      if (snapshot[i].el) oldEls.push(snapshot[i].el);
    }
    // HOTFIX 4: compare normalised text — the page may re-render the
    // sent text with different spacing / line breaks, which broke an
    // exact indexOf match and reported a sent message as uncertain.
    var want = normText(text);
    for (var j = 0; j < current.length; j++) {
      var fp = current[j];
      // HOTFIX 3: newness is dom_id identity only. An old node whose
      // content changed in place (same dom_id, new text) is NOT new —
      // the hotfix2 (dom_id, text) pair check wrongly treated it as new.
      // HOTFIX 6: when dom_id is missing, element identity is the
      // second rule (the same node object in the snapshot is not
      // new, even if its text changed). The old position fallback
      // (j >= snapshot.length) is dropped: it misjudged a genuinely
      // new node inserted mid-list as old, and an old node after a
      // re-render as new. dom_id is present on real ChatGPT turns,
      // so the re-render case is covered by the dom_id rule.
      var isNew = true;
      if (fp.dom_id !== null && oldIds[fp.dom_id]) isNew = false;
      else if (fp.el && oldEls.indexOf(fp.el) !== -1) isNew = false;
      if (isNew && normText(fp.text) === want) return fp;
    }
    return null;
  }

  function composerCleared(comp) {
    if (!comp) return true;
    if (comp.tagName === "TEXTAREA" || comp.tagName === "INPUT") {
      return !comp.value;
    }
    return !(comp.textContent && comp.textContent.trim());
  }

  // Run 54998652: the ChatGPT text leaf sits inside a user bubble
  // without role attributes or a platform message ID.
  function observedUserBubbles() {
    var root = IS_CHATGPT && document.querySelector("main");
    return root ? Array.from(root.querySelectorAll(".bg-user-message")) : [];
  }

  function observedBubbleText(bubble) {
    var leaves = bubble.querySelectorAll(".text-size-chat.whitespace-pre-wrap");
    if (leaves.length !== 1 ||
        leaves[0].closest("blockquote,pre,[contenteditable]")) return null;
    return nodeText(leaves[0]);
  }

  function sameRenderedSentText(rendered, raw) {
    if (rendered === raw) return true;
    // A multiline request can render as spaces in the ChatGPT user bubble.
    // Require complete whitespace-normalized equality; marker-only matches fail.
    if (IS_CHATGPT && typeof rendered === "string" && typeof raw === "string" &&
        /[\r\n]/.test(raw) && normText(rendered) === normText(raw)) return true;
    if (!IS_CHATGPT || typeof rendered !== "string" ||
        typeof raw !== "string" || raw.indexOf("`") === -1) return false;
    // ChatGPT renders Markdown inline code without its literal backticks.
    // Still require full normalized equality, not merely a matching marker.
    return normText(rendered) === normText(raw.replace(/`/g, ""));
  }
  function confirmObservedBubble(before, after, text) {
    // Primary: append exactly one new bubble with stable previous bubbles.
    var stableAppend = after.length === before.length + 1;
    if (stableAppend) {
      for (var i = 0; i < before.length; i++) {
        if (before[i].el !== after[i] ||
            before[i].text !== observedBubbleText(after[i]) ||
            sameRenderedSentText(before[i].text, text)) {
          stableAppend = false;
          break;
        }
      }
      if (stableAppend) {
        var appended = after[before.length];
        if (sameRenderedSentText(observedBubbleText(appended), text) &&
            !appended.closest("blockquote,pre,[contenteditable]")) {
          return {el: appended, dom_id: nodeDomId(appended),
                  strategy: "observed_user_bubble"};
        }
      }
    }
    // A rerender is acceptable only with stable, independently identified
    // historical messages and exactly one appended user bubble. Otherwise
    // an edited or remounted history could be mistaken for a new delivery.
    if (after.length !== before.length + 1) return null;
    if (before.some(function (old) {
      return sameRenderedSentText(old.text, text);
    })) return null;
    for (var i = 0; i < before.length; i++) {
      var previous = before[i];
      var idBefore = nodeDomId(previous.el);
      var idAfter = nodeDomId(after[i]);
      if (!idBefore || idBefore !== idAfter ||
          previous.text !== observedBubbleText(after[i])) return null;
    }
    var candidate = after[before.length];
    if (!candidate ||
        !sameRenderedSentText(observedBubbleText(candidate), text) ||
        candidate.closest("blockquote,pre,[contenteditable]")) return null;
    var newId = nodeDomId(candidate);
    if (newId && before.some(function (old) {
      return nodeDomId(old.el) === newId;
    })) return null;
    return {el: candidate, dom_id: newId,
            strategy: "observed_unique_bubble_after_rerender"};
  }

  // RC14-v3: highly restricted corroboration for relay test messages ONLY.
  // React may remount/virtualize old ChatGPT bubbles, invalidating every
  // positional before/after comparison. A unique full-text user bubble
  // alone does not prove it was sent by this transaction. Require a NEW
  // positively identified assistant reply starting with this round's
  // exact unique marker as independent corroboration. Ordinary sends
  // never use this fallback.
  function confirmMarkerCorroboratedBubble(before, after, text, assistSnap) {
    if (!IS_CHATGPT || typeof text !== "string" || !assistSnap) return null;
    var match = text.match(/Reply starting exactly with (R11-\d+-CHATGPT-[A-F0-9]{6,32}):/);
    var b4 = text.match(/^Agent Relay RC14-v6 isolated background DOM confirmation test\. Unique nonce (RC14V6-B4-[A-F0-9]{12})\. Reply exactly \1 and nothing else\.$/);
    if (!match && !b4) return null;
    var marker = match ? match[1] : b4[1];
    var replyPrefix = match ? marker + ":" : marker;
    if (before.some(function (old) {
      return sameRenderedSentText(old.text, text);
    })) return null;
    if (typeof assistSnap.latestText === "string" &&
        (match ? assistSnap.latestText.indexOf(replyPrefix) === 0 :
          assistSnap.latestText === replyPrefix)) return null;
    var matches = after.filter(function (bubble) {
      return sameRenderedSentText(observedBubbleText(bubble), text);
    });
    if (matches.length !== 1) return null;
    var bubble = matches[0];
    if (!bubble || before.some(function (old) { return old.el === bubble; }) ||
        bubble.closest("blockquote,pre,[contenteditable]")) return null;
    var reply = latestReply();
    if (!reply || typeof reply.text !== "string" ||
        (match ? reply.text.indexOf(replyPrefix) !== 0 :
          reply.text !== replyPrefix) ||
        !newAssistantReplyAppeared(assistSnap)) return null;
    // Real ChatGPT assistant turns may lack a stable DOM id after React remount.
    // If an id exists, it must not have been present before the send.
    if (b4 && reply.dom_id && assistSnap.ids[reply.dom_id]) return null;
    return {el: bubble, dom_id: nodeDomId(bubble),
            strategy: "verified_marker_reply_after_rerender"};
  }

  function waitForSendConfirmation(comp, text, snapshot, assistSnap, beforeBubbles) {
    // MutationObserver is the primary clock: background setTimeout callbacks
    // can be severely throttled. No retry of send.click() is ever attempted.
    // The DOM is also scanned immediately to cover mutations before observer
    // registration. All observations use the same pre-click immutable snapshot.
    return new Promise(function (resolve) {
      var begunAt = Date.now();
      var deadline = begunAt + SEND_CONFIRM_TIMEOUT_MS;
      var diagnostic = {
        version: "B4_DOM_EVENTS_V1",
        observer_available: typeof MutationObserver === "function",
        observer_installed: false,
        observer_triggers: 0,
        mutation_records_total: 0,
        scan_count: 0,
        initial_bubble_count: beforeBubbles.length,
        initial_full_match_count: beforeBubbles.filter(function (old) {
          return sameRenderedSentText(old.text, text);
        }).length,
        last_scan: null,
        timeout_scan: null,
        termination_reason: null
      };
      var finished = false;
      var observer = null;
      var fallbackTimer = null;
      var deadlineTimer = null;
      function finish(message, confirmation, reason) {
        if (finished) return;
        finished = true;
        diagnostic.termination_reason = reason;
        if (observer) observer.disconnect();
        if (fallbackTimer !== null) clearTimeout(fallbackTimer);
        if (deadlineTimer !== null) clearTimeout(deadlineTimer);
        resolve({
          message: message,
          confirmation: confirmation,
          diagnostics: diagnostic
        });
      }
      function inspect(trigger) {
        if (finished) return;
        var now = Date.now();
        var bubbles = observedUserBubbles();
        var observedLayout = beforeBubbles.length > 0 || bubbles.length > 0;
        var fullMatches = 0;
        for (var i = 0; i < bubbles.length; i++) {
          if (sameRenderedSentText(observedBubbleText(bubbles[i]), text)) {
            fullMatches++;
          }
        }
        var found = observedLayout
          ? confirmObservedBubble(beforeBubbles, bubbles, text)
          : findNewUserMessage(snapshot, text);
        // Resolve composer from current DOM, not a detached React node.
        var currentComposer = composer();
        var empty = !!currentComposer && composerCleared(currentComposer);
        if (!found && IS_CHATGPT && observedLayout && empty &&
            fullMatches === 1) {
          found = confirmMarkerCorroboratedBubble(
            beforeBubbles, bubbles, text, assistSnap);
        }
        var scan = {
          elapsed_ms: now - begunAt,
          trigger: trigger,
          visibility: visibilityState(),
          bubble_count: bubbles.length,
          full_text_match_count: fullMatches,
          full_text_match: fullMatches === 1,
          new_user_candidate: !!found,
          composer_found: !!currentComposer,
          composer_empty: empty
        };
        diagnostic.scan_count++;
        diagnostic.last_scan = scan;
        // Never permit a late observer callback to confirm delivery.
        if (now >= deadline) {
          diagnostic.timeout_scan = scan;
          finish(null, null, "timeout");
          return;
        }
        if (empty && found) {
          finish(found, "new_user_node", "verified_user_bubble");
          return;
        }
        // Muse-only fallback; ChatGPT requires an independent user bubble.
        if (!IS_CHATGPT && !observedLayout && empty &&
            (replyStreaming() || newAssistantReplyAppeared(assistSnap))) {
          finish(found, "reply_started", "muse_reply_started");
        }
      }
      var target = document.documentElement || document.body;
      if (target && typeof MutationObserver === "function") {
        observer = new MutationObserver(function (records) {
          diagnostic.observer_triggers++;
          diagnostic.mutation_records_total += records ? records.length : 0;
          inspect("mutation");
        });
        observer.observe(target, {
          childList: true, subtree: true, characterData: true, attributes: true,
          attributeFilter: ["class", "data-message-author-role", "data-message-role"]
        });
        diagnostic.observer_installed = true;
      }
      inspect("immediate"); // also covers changes before observer registration
      function fallback() {
        if (finished) return;
        inspect("fallback");
        if (!finished) fallbackTimer = setTimeout(fallback, 250);
      }
      if (!finished) {
        fallbackTimer = setTimeout(fallback, 250);
        deadlineTimer = setTimeout(function () {
          // Include a final actual DOM snapshot, not just the preceding poll.
          inspect("deadline");
          if (!finished) finish(null, null, "timeout");
        }, SEND_CONFIRM_TIMEOUT_MS);
      }
    });
  }

  // HOTFIX 6 (B4, ROUND 25): one time-series sample of the send
  // state. Recorded at four points - before input, after input,
  // during the button wait, at timeout (plus at the moment the
  // button is found) - so ATTEMPT-10 can distinguish: button never
  // appeared / appeared but disabled / appeared then disappeared /
  // state sync too slow. Contains only state (visibility, input
  // type, content acceptance, button existence + disabled state),
  // never message content.
  function buttonSample(comp, text, label, t0) {
    var btn = sendButton();
    var sample = {
      t_ms: Date.now() - t0,
      label: label,
      visibility: visibilityState(),
      composer_tag: comp ? (comp.tagName || null) : null,
      composer_has_text: comp ? composerHasText(comp, text) : false,
      button: null,
    };
    if (btn) {
      var testid = null;
      var aria = null;
      try { testid = btn.getAttribute("data-testid"); } catch (e) { /* ignore */ }
      try { aria = btn.getAttribute("aria-label"); } catch (e) { /* ignore */ }
      sample.button = {
        exists: true,
        disabled: !!btn.disabled,
        testid: testid,
        aria_label: aria,
      };
    } else {
      sample.button = { exists: false, disabled: null,
                        testid: null, aria_label: null };
    }
    return sample;
  }

  // Wait for an ENABLED send button to APPEAR after
  // setComposerValue. The button does NOT exist while the composer
  // is empty — it only appears after text is typed (ATTEMPT-07) —
  // so it must be looked up AFTER the input, and the wait is on
  // actual DOM state (the button appearing and becoming enabled),
  // never a fixed delay. HOTFIX 5 (P2, ATTEMPT-08): a DISABLED
  // button is NEVER resolved. Hotfix4 resolved "whatever button
  // exists" at the deadline and doSend clicked it — but a click on
  // a disabled button is a DOM no-op, so nothing was submitted,
  // the text stayed in the composer, and confirmation timed out
  // as send_unconfirmed (UNCERTAIN) instead of an honest
  // not_sent. Resolving null here lets doSend report
  // send_button_never_enabled (the page never registered the
  // input: definitely not sent, we never clicked) when a button
  // exists but never enabled, or send_button_missing_after_input
  // when no button ever appeared.
  // HOTFIX 6 (B4): the wait records a time series of button
  // samples (every ~500ms plus a final sample at timeout) into
  // the timeline passed in, and resolves {button, timeline}.
  // A hidden tab gets the longer HIDDEN_BUTTON_TIMEOUT_MS bound.
  function waitForSendButton(comp, text, timeline, t0) {
    return new Promise(function (resolve) {
      var timeout = visibilityState() === "hidden"
        ? HIDDEN_BUTTON_TIMEOUT_MS : SEND_BUTTON_TIMEOUT_MS;
      var deadline = Date.now() + timeout;
      var lastSampleAt = Date.now();
      (function poll() {
        var btn = sendButton();
        if (btn && composerHasText(comp, text) && !btn.disabled) {
          timeline.push(buttonSample(comp, text, "button_found", t0));
          resolve({ button: btn, timeline: timeline });
          return;
        }
        var now = Date.now();
        if (now - lastSampleAt >= 500) {
          timeline.push(buttonSample(comp, text, "during_wait", t0));
          lastSampleAt = now;
        }
        if (now >= deadline) {
          timeline.push(buttonSample(comp, text, "timeout", t0));
          resolve({ button: null, timeline: timeline });
          return;
        }
        setTimeout(poll, INPUT_SYNC_POLL_MS);
      })();
    });
  }

  function doSend(text, nonce) {
    // NEVER activate the tab, never focus anything, never use system input.
    // Order is the HOTFIX 4 (P2-A) fix, per ChatGPT ROUND 22: the
    // send button does NOT exist while the composer is empty — it
    // only appears AFTER text is typed. So: locate the composer,
    // snapshot, fill, WAIT (bounded, on actual button state) for
    // the usable button to appear, then ONE DOM send action. The
    // old code looked the button up FIRST and failed before ever
    // typing whenever the button was not yet there.
    function fail(error) {
      return Promise.resolve({
        type: "send_result",
        origin: window.location.origin,
        nonce: nonce,
        ok: false,
        // These errors prove the message was definitely NOT sent.
        delivery: "not_sent",
        error: error,
        visibility_state: visibilityState(),
        button_timeline: timeline,
      });
    }
    // HOTFIX 6 (B4, ROUND 25): the button time series. Samples are
    // recorded before input, after input, during the button wait
    // (every ~500ms) and at timeout, and carried on every result
    // so ATTEMPT-10 can tell a hidden-tab timeout from a
    // visible-tab one and distinguish the four button states.
    var timeline = [];
    var t0 = Date.now();
    var comp = composer();
    if (!comp) {
      return fail("composer_or_send_button_missing");
    }
    // HOTFIX 4 (DEFECT 3 + P2): only the stop button proves a reply
    // is streaming. A disabled send button at the start proves
    // nothing — the button is disabled while the composer is empty,
    // which is normal, not streaming. The old check failed here
    // whenever the button started disabled.
    if (replyStreaming()) {
      return fail("send_button_disabled_streaming");
    }
    // HOTFIX 2 (TASK 2): snapshot the user message blocks AND the
    // assistant side BEFORE the click. Confirmation requires a NEW
    // node after the click — the old identical text already sitting
    // in history is not proof. HOTFIX 6: the snapshot is taken
    // with the sent text, so old duplicates of the same text are
    // in the snapshot (text-anchored strategy) and are never
    // mistaken for the new message.
    var beforeBubbles = observedUserBubbles().map(function (el) {
      return { el: el, text: observedBubbleText(el) };
    });
    var snapshot = userMessageFingerprints(text);
    var assistSnap = assistantSnapshot();
    if (IS_CHATGPT) lastConfirmedUserTurn = null;
    lastSentText = text;
    timeline.push(buttonSample(comp, text, "before_input", t0));
    try {
      setComposerValue(comp, text);
    } catch (e) {
      return fail("send_failed:" + (e && e.message ? e.message : String(e)));
    }
    // HOTFIX 4 (P2-A): the button is looked up AFTER the input, and
    // we wait for it to appear and become usable before the single
    // DOM click. React may not have synced yet; clicking
    // immediately — or failing because no button existed at the
    // start — is the ATTEMPT-07 failure mode.
    // HOTFIX 5 (P2): verify the fill took BEFORE waiting for a
    // button. If the composer does not hold the text right after
    // setComposerValue, the input was not accepted at all — fail
    // fast with composer_input_not_accepted (definitely not sent)
    // instead of waiting 5s for a button that can never enable.
    // Hotfix4 only checked this after the button wait.
    if (!composerHasText(comp, text)) {
      // A stateful rich editor may finish rendering a multiline edit
      // after the native editing transaction returns. Do not call it
      // not_sent immediately when text is present but still settling:
      // the existing bounded button poll will check exact text and
      // enabled button together before the ONE permitted click.
      // Empty/rejected editors and legacy input fields still fail fast.
      var richTextPending = comp.tagName !== "TEXTAREA" &&
        comp.tagName !== "INPUT" &&
        (Boolean(comp.textContent && comp.textContent.trim()) ||
         Boolean(comp.innerText && comp.innerText.trim()));
      if (!richTextPending) return fail("composer_input_not_accepted");
    }
    timeline.push(buttonSample(comp, text, "after_input", t0));
    return waitForSendButton(comp, text, timeline, t0).then(function (res) {
      var send = res.button;
      if (!send) {
        // No ENABLED button ever appeared after the input, and we
        // never clicked. Distinguish the three ways this happens:
        // the composer no longer holds the text (the page reverted
        // the input, or it never stuck); a button exists but never
        // enabled (the page never registered the input — the
        // ATTEMPT-08 failure: the text sat in the composer, the
        // button stayed disabled, and Hotfix4 clicked it anyway,
        // a DOM no-op that reported send_unconfirmed instead of
        // an honest not_sent); or no button ever appeared.
        if (!composerHasText(comp, text)) {
          return fail("composer_input_not_accepted");
        }
        if (sendButton()) {
          return fail("send_button_never_enabled");
        }
        return fail("send_button_missing_after_input");
      }
      try {
        send.click(); // DOM-level click only; does not activate the window.
      } catch (e) {
        return fail("send_failed:" + (e && e.message ? e.message : String(e)));
      }
      startCompletionWatch();
      return waitForSendConfirmation(comp, text, snapshot, assistSnap, beforeBubbles)
        .then(function (res) {
          if (!res.confirmation) {
            // Delivery cannot be confirmed: UNCERTAIN. Never
            // auto-resend; the coordinator marks it UNCERTAIN and stops.
            // HOTFIX 6: attach the de-sensitized diagnostic inventory
            // (what recognition observed) and the button time series,
            // so ATTEMPT-10 can capture the real structure and the
            // button state instead of guessing.
            return {
              type: "send_result",
              origin: window.location.origin,
              nonce: nonce,
              ok: false,
              delivery: "uncertain",
              error: "send_unconfirmed",
              diagnostics: diagnoseRecognition("user"),
              send_confirmation_diagnostics: res.diagnostics || null,
              visibility_state: visibilityState(),
              button_timeline: timeline,
            };
          }
          // ok:true means MESSAGE_SENT only — delivery is confirmed,
          // either by a NEW user message node in the chat history
          // (confirmation:"new_user_node", bound to its
          // data-message-id when the page provides one) or by the AI
          // having started to reply (confirmation:"reply_started").
          // It does NOT mean the AI reply is done; the completion
          // watch reports RESPONSE_COMPLETED separately via
          // reply_complete when the reply finishes streaming.
          // HOTFIX 6: anchor the confirmed user turn so a later
          // read_latest can use the turn-after-user-turn fallback
          // (B3), and report which recognition strategy confirmed
          // the node.
          if (res.message && res.message.el) {
            lastConfirmedUserTurn = res.message.el;
          }
          return {
            type: "send_result",
            origin: window.location.origin,
            nonce: nonce,
            ok: true,
            delivery: "message_sent",
            message_id: res.message ? res.message.dom_id || null : null,
            confirmation: res.confirmation,
            send_confirmation_diagnostics: res.diagnostics || null,
            node_strategy: res.message ? res.message.strategy || null : null,
            visibility_state: visibilityState(),
            button_timeline: timeline,
            note: "sent_via_dom_click_no_activation",
          };
        });
    });
  }

  // --- message handling -------------------------------------------------------
  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    // Messages arrive only from our own background service worker.
    // msg.content (if any) is untrusted data: it is only placed into the
    // composer as text, never executed.
    if (!msg || typeof msg.type !== "string") {
      sendResponse({ type: "error", error: "bad_message" });
      return true;
    }
    if (msg.type === "ping") {
      // FIX 1 (P0): echo the request nonce in the pong.
      sendResponse({ type: "pong", origin: window.location.origin,
                     nonce: msg.nonce || null, document_ready_state: document.readyState });
      return true;
    }
    if (msg.type === "health") {
      sendResponse(doHealth(msg.nonce || null));
      return true;
    }
    if (msg.type === "read_latest") {
      doReadLatest(msg.nonce || null).then(sendResponse);
      return true; // async response
    }
    if (msg.type === "collect_dom") {
      // HOTFIX 6 (ROUND 25): optional read-only diagnostic mode.
      // Returns de-sensitized DOM structure for the two known test
      // markers (no message content, no history, no network).
      if (typeof msg.user_marker !== "string" ||
          typeof msg.assistant_marker !== "string" ||
          !msg.user_marker || !msg.assistant_marker) {
        sendResponse({
          type: "collect_dom_result",
          origin: window.location.origin,
          nonce: msg.nonce || null,
          ok: false,
          error: "missing_marker",
        });
        return true;
      }
      sendResponse(doCollectDom(msg.user_marker, msg.assistant_marker,
                                msg.nonce || null));
      return true;
    }
    if (msg.type === "send") {
      if (typeof msg.text !== "string" || !msg.text) {
        sendResponse({
          type: "send_result",
          origin: window.location.origin,
          nonce: msg.nonce || null,
          ok: false,
          delivery: "not_sent",
          error: "empty_text",
        });
        return true;
      }
      // FIX 4: doSend() is async (it waits for delivery confirmation).
      // Return true to keep the message response channel open until
      // the confirmation resolves — do NOT close it early, or the
      // ACK (and the nonce) is lost.
      doSend(msg.text, msg.nonce || null).then(sendResponse);
      return true;
    }
    sendResponse({ type: "error", error: "unknown_type:" + msg.type });
    return true;
  });

  // Start watching for reply completion as soon as the page is ready.
  if (document.readyState === "complete" ||
      document.readyState === "interactive") {
    startCompletionWatch();
  } else {
    document.addEventListener("DOMContentLoaded", startCompletionWatch);
  }
})();
