# Agent Relay — Chrome Web Store RC14-v6 Candidate Review Guide

**Status:** REVIEW CANDIDATE / NOT SUBMITTED / NOT GOOGLE-APPROVED  
**Created:** 2026-11-24 (Australia/Sydney)  
**Upstream GitHub release:** https://github.com/rambolanbohu-bot/agent-relay/releases/tag/v1.0.0-rc14-v6  
**Source artifact:** `agent-relay-skill-1.0.0-rc6-RC14-v6-REVIEW.zip`  
**Original SHA-256:** `81f3505b3535d53bf8910fda3ee8abe076e9160cdc1befce6a1c660a5c0def3f`  
**Chrome ZIP SHA-256:** `f1c17f9019b281705da27d3a5b595c1ff2741580e395464a2d5f431735a4ff6d`  
**Version:** extension 1.0.2, version_name "RC14-v6 CWS Review Candidate"

## Scope and provenance

The GitHub original Release ZIP SHA-256 matched its published digest. Its MANIFEST.json listed 88 files; all 88 SHA-256 checks passed. This candidate was extracted from that exact Release ZIP.

The ZIP for Chrome Web Store contains a root-level `manifest.json`, `background.js`, `content.js`, a static informational popup, static local help, styling and 16/48/128px PNG icons. No Windows EXE, installer, Python source, or unrelated test artifacts are inside the Chrome ZIP.

**The original `background.js` and `content.js` are preserved byte-for-byte**:
- `background.js`: `0477786da76bcb1dd764c736d536d1caa561d3baf02fbdcfaac2ec0f959ea47c`
- `content.js`: `9039b7b543016ddf3589380ae559576c57ce0633a7e260979fcc2c49aea98f15`

Manifest-only changes:
1. Clear English product name.
2. Replace mojibake description with accurate English text.
3. Keep `key`, version, nativeMessaging/tabs, two host permissions, service worker, content script matches.
4. Add static `action.default_popup` and three icons.
5. Mark `version_name` for human review.

## Manual review steps

1. On Windows, first verify the separately distributed upstream full ZIP hash using `certutil -hashfile <file> SHA256`.
2. Install the original Windows Native Host using the upstream instructions; do not install the Chrome ZIP as a Windows app.
3. Open `chrome://extensions`, enable Developer Mode, use **Load unpacked** on the extracted Chrome candidate ZIP.
4. Check that clicking the extension icon opens the informational popup, including working links to the upstream Release and local help page.
5. Check permissions are limited to `nativeMessaging`, `tabs`, `https://chatgpt.com/*`, `https://muse.ai/*`.
6. Check the extension ID in Chrome. The embedded key currently derives `jeelmedmciafjnfdpnjgbgipplcddhka`; **Chrome Web Store may assign a different published ID**. Native Host `allowed_origins` must be updated if so, and the Windows installer must be validated on a clean profile.
7. On a dedicated test profile with non-sensitive messages, inspect service-worker logs, Native Host connection, manual start/stop permissions and DOM read/send results. Never re-run already accepted RC14-v6 acceptance work as a prerequisite; only test Chrome packaging deltas.
8. Verify that clicking the release button is user-initiated and that no additional tabs or external pages open automatically.
9. Verify no third-party tracking, affiliate link rewriting, or advertisement injections.
10. Run a new Chrome Web Store developer dashboard review, including Privacy tab, before submitting.

## Mandatory pre-submission blockers

- **CWS-P0-ID:** Store-assigned extension ID and Windows Native Host origin allowlist have not been tested together.
- **CWS-P0-PRIVACY:** Publicly hosted, final reviewed Privacy Policy URL not yet configured.
- **CWS-P0-AUTH:** User-consent UX for automatic sends / stop and pause needs policy review and a reproducible demonstration for reviewer.
- **CWS-P0-TEST:** Real installed Chrome candidate and Native Host pair not yet tested. JS syntax and ZIP verification alone are insufficient.
- **CWS-P1-STORE:** Chrome Web Store screenshots, listing, permissions justifications and publisher identity to finalize.
- **CWS-P1-COMMERCE:** Verified *seller-owned* Agent Relay Agensi product URL not available. Do not point to unrelated Agent Relay products.
- **CWS-P1-AFFILIATE:** User's Agensi referral program is separate. Affiliate URL is intentionally **not embedded**; launch only with verified direct-user-benefit design and disclosure compliant with Chrome policy.

## Commercial architecture

Chrome Web Store distributes the browser extension. The Windows Native Host remains separately installed from the GitHub release. Agensi hosts the separately verified product purchase/license offer. An optional affiliate introduction must not interfere with core functionality, append link parameters, set cookies, open pages without user interaction or inject promotions into supported chat websites.

**Release candidate has no affiliate or Agensi purchase link**, because seller-owned product URL and Chrome-policy fit must be verified. It intentionally has only a user-clicked, official GitHub Release link.

## Data disclosure briefing (for publisher to adapt)

The extension operates on the user's chosen ChatGPT/Muse discussion tabs, reading text and response metadata and sending user-authorized local coordinator messages. Those messages pass to a separately installed local Native Host; the coordinator may store state and logs. ChatGPT/Muse will process text submitted to those sites under their own privacy terms. The extension does not include telemetry or advertiser tracking code in this candidate. **Do not claim “no data processed” merely because there is no backend analytics.** Inspect the Native Host and coordinator handling of conversation bodies before final Privacy answers.

## Technical validation done

- Original full Release SHA-256: PASS
- Original Release MANIFEST.json 88/88 SHA-256: PASS
- Zip CRC, root-level manifest.json: PASS
- Original background/content JS SHA-256 unchanged: PASS
- Node --check background.js and content.js: PASS
- Manifest MV3, 2 permissions and 2 host patterns: PASS
- Embedded key to extension ID consistency: PASS
- Google CWS actual acceptance: NOT TESTED
- Standalone popup HTML rendering in Linux headless Chrome: PASS (preview only)
- Full extension-ID headless Chrome smoke test: BLOCKED (headless invocation timed out; no live PASS claimed)
- Installed-extension ↔ Native Host live integration: NOT TESTED
- Agensi seller purchase and affiliate integration: NOT ADDED

## Google references

- Prepare upload ZIP: https://developer.chrome.com/docs/webstore/prepare/
- Native Messaging: https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging/
- Chrome Web Store policies: https://developer.chrome.com/docs/webstore/program-policies/
- Affiliate marketing violation guidance: https://developer.chrome.com/docs/webstore/troubleshooting/
- July 2026 policy update (in force August 2026): https://developer.chrome.com/blog/cws-policy-updates-2026