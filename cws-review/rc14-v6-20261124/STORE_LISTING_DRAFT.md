# Agent Relay — Chrome Web Store Listing (DRAFT)

This text is for developer review only. Do not publish before the privacy policy, extension ID, purchase URL and test instructions are finalized.

## Name
Agent Relay - AI Conversation Relay

## Short description
Connect the Agent Relay local app to authorized ChatGPT and Muse tabs for user-controlled AI discussion relays.

## Detailed description

Agent Relay is a local-first browser adapter for structured discussions between ChatGPT and Muse. It works with a separately installed Windows Native Messaging Host and a local coordinator.

**What it does**
- Connects only to supported ChatGPT and Muse conversation tabs.
- Sends coordinator-requested messages to the selected discussion and reads verified replies.
- Supports a stop-on-uncertain-delivery approach to avoid automatic duplicate sends.
- Works with a local coordinator for session state, receipts, and pause/resume operations.

**Installation prerequisites**
You must download and install the Windows Native Host separately from the official Agent Relay GitHub release. The Chrome extension alone is not a standalone AI chatbot or a substitute for subscriptions/accounts with ChatGPT or Muse.

**Permissions**
- nativeMessaging: local coordinator communication.
- tabs: bind the intended discussion browser tab.
- chatgpt.com and muse.ai: read/write discussions on these explicitly supported sites.

**Data handling**
Conversation text may be relayed between these browser tabs and your local coordinator. Messages submitted to ChatGPT and Muse are processed by those respective services. Local state and logs may store discussion text and metadata. Read the final linked Privacy Policy before installing.

**Commercial disclosure**
Product support, licenses, and purchases (when available) are provided on an external Agensi listing. There are no affiliate links, referral redirects, advertising insertions, or tracking cookies in this review candidate. Future affiliate functionality, if any, will require separate disclosures, reviewer assessment and user controls.

This is a technical preview. No claim is made of verified long-term unattended operation or compatibility with future website redesigns.

## Store privacy fields — DRAFT / VALIDATION REQUIRED
- Purpose: user-authorized AI conversation relay through supported tabs and a separately installed local host.
- User data accessed: messages or other text visible within the chosen discussion; related session metadata.
- Storage/transfer: extension↔local host; AI site↔its service when sends occur; local coordinator files may persist data.
- No extension analytics/ads/affiliate tracking found in the RC14-v6 CWS candidate itself.
- Public privacy URL: **BLOCKED — must publish externally and verify consistency.**
- Permission justification: nativeMessaging / tabs / 2 site patterns only.
- Automated send disclosure: **must show that user's explicit configuration/authorization precedes sends.**

## Upload metadata / screenshots needed
- 128x128 item icon already provided inside candidate.
- At least one genuine 1280x800 or 640x400 store screenshot from real installed extension and local host.
- Native Host installation walkthrough screenshot; avoid exposing passwords, cookies, personal chat content.
- Full description, support URL, privacy policy URL, license or payment URL.
- Reviewer instructions with a dedicated test profile and benign nonce messages.

## Pre-submission release gates
- Match Chrome Web Store-assigned extension ID to local Native Host allowed_origins and installer flow.
- Demonstrate correct stop, resume, uncertain delivery and no duplicate sending under real Chrome.
- Confirm no unrelated website modification and no affiliate traffic hijack.
- Provide honest local log/data-retention controls and privacy disclosures.
- Validate Agensi seller-owned listing; do not point to similar products from another publisher.