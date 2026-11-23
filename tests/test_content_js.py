#!/usr/bin/env python3
"""RC4-hotfix6 tests for transport/extension/content.js (FIX 1 +
FIX 4, HOTFIX 2 TASK 1 + TASK 2, HOTFIX 3 TASK 1, HOTFIX 4
DEFECT 1 + 2 + 3 and P2-A / P2-B, HOTFIX 5 P2, HOTFIX 6 B2/B3/B4
+ ROUND 25 collector).

Runs the Node harness (tests/content_js_harness.js), which loads the
REAL content.js with stubbed browser globals and checks the hotfix
contract:
- ping / health / read_latest echo the request nonce (FIX 1);
- health with an EMPTY composer (no send button — the normal state
  before typing) reports ok:true (HOTFIX 4 P2-A);
- read_latest only accepts nodes that positively identify as
  assistant replies; a user message rendered as an <article> is
  never reported as a reply, and with only user articles it reports
  found:false; the completion watch never reports a user message as
  a reply (HOTFIX 2 TASK 1);
- read_latest finds a reply whose own innerText is empty but whose
  textContent holds the text, and a reply whose role attribute sits
  on an empty wrapper while the turn container (parent) holds the
  text — WITHOUT reintroducing the generic "article" fallback
  (HOTFIX 4 DEFECT 2); a role node whose parent is MAIN still
  reports found:false; read_latest retries briefly so a reply that
  is still rendering is found (HOTFIX 4 P2-B);
- send returns ok:true + delivery:"message_sent" only after a NEW
  user message node appears in the DOM with the composer cleared,
  and reports the new node's data-message-id (FIX 4 + HOTFIX 2
  TASK 2: MESSAGE_SENT, not RESPONSE_COMPLETED);
- a send of text that already exists in history, where the composer
  clears but NO new node appears, returns ok:false +
  delivery:"uncertain" (HOTFIX 2 TASK 2);
- an old user message node whose content changes IN PLACE (same
  dom_id, new text, NO new node) is NOT treated as a new message:
  the send returns ok:false + delivery:"uncertain" (HOTFIX 3
  TASK 1 — the hotfix2 (dom_id, text) pair check wrongly returned
  message_sent for this case; the hotfix3 rule judges newness by
  dom_id identity only);
- a send whose message was genuinely delivered but the user-node
  check missed it is confirmed via the corroborating signal —
  composer cleared AND the AI started replying — and reports
  confirmation:"reply_started" (HOTFIX 4 DEFECT 1); a slow render
  (new node after 6.5s) is still confirmed within the 10s timeout;
  a send whose text the page re-renders with different whitespace
  is still confirmed by the normalised text match; a send whose
  button is disabled until React syncs waits before clicking;
  a send whose button only appears after text is typed is
  confirmed (doSend fills first, waits for the button, then
  clicks once — HOTFIX 4 P2-A); when the button NEVER appears
  after the input, the result is not_sent (never clicked);
- a send whose button EXISTS but NEVER enables after the input
  returns not_sent with the new error send_button_never_enabled
  and NEVER clicks (HOTFIX 5 P2 — the ATTEMPT-08 failure: Hotfix4
  clicked the disabled button, a DOM no-op, and the confirmation
  timed out as UNCERTAIN); a send whose fill does not stick
  returns not_sent with composer_input_not_accepted immediately
  (fast-fail) and never clicks (HOTFIX 5 P2);
- HOTFIX 6 (B2/B3): multi-strategy recognition — a user node
  with an alternate role attribute, a role attribute on an empty
  wrapper whose turn ARTICLE holds the text, a user turn with no
  role marker at all (sent-text anchor), and an assistant reply
  found via the turn-after-user-turn fallback are all recognised;
  the ATTEMPT-09 exact scenario (message delivered + reply
  present, primary selectors missing both) is recognised; a bare
  turn echoing the sent text is never reported as a reply;
  unconfirmed sends and not-found reads carry a de-sensitized
  diagnostic inventory (never message content);
- HOTFIX 6 (B4, ROUND 25): a hidden tab's send records a button
  time series (before input, after input, during the wait, at
  timeout / button found) with visibilityState;
- HOTFIX 6 (ROUND 25): the optional read-only de-sensitized DOM
  collector (collect_dom) finds both test markers, reports the
  role-selector counts and the node structures, never returns
  message content, and proves the key diagnostic (found=true
  with role count 0);
- a send that cannot be confirmed returns ok:false +
  delivery:"uncertain" and never auto-resends (FIX 4);
- the send / read_latest listeners keep the async response
  channel open (return true) so the ACK is not lost.

Skipped if node is not available. The harness simulates the page
(the send button's click clears the composer and appends a user
message), so it proves the content script's own logic — not real
Chrome. Real-Chrome load testing is still PENDING (see
docs/KNOWN-LIMITATIONS.md).
"""

import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class TestContentJs(unittest.TestCase):
    def test_harness_all_checks_pass(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available for content.js harness")
        # HOTFIX 6: the harness now takes ~98s (four UNCERTAIN
        # tests at 10s each + a 6.5s slow render + 3s read retries
        # + a 5s button-never-appears test + a 6s hidden-tab late
        # button + a 10s hidden-tab button timeout). Three ChatGPT
        # fail-closed cases now also wait out the actual send timer. 180s leaves
        # margin; the ATTEMPT-09 batch timeout is a batch-level
        # limit, not this test's.
        proc = subprocess.run(
            [node, os.path.join(HERE, "content_js_harness.js")],
            capture_output=True, text=True, timeout=180)
        try:
            result = json.loads(proc.stdout)
        except ValueError:
            self.fail(
                f"harness did not print JSON: stdout={proc.stdout!r} "
                f"stderr={proc.stderr!r}")
        failed = [c for c in result.get("checks", [])
                  if not c.get("pass")]
        self.assertEqual(failed, [],
                         f"failing harness checks: {failed}")
        self.assertTrue(result.get("all_pass"), result)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
