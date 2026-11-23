# Agent Relay RC14-v6 — Dual-channel commerce review (2026-11-24)

**NOT SUBMITTED / NO PRODUCTION CHANGES.**

## Decision
- Chrome extension: Agent Relay functionality and *owner-verified* Agensi product purchase entry only.
- Affiliate referrals: standalone opt-in explanatory website, **not** inside the extension.
- No automated redirects, affiliate parameters, tracking cookies or injection into AI chat sites.

## Build in this review folder
`Agent_Relay_CWS_RC14-v6_COMMERCE_REVIEW.zip`: Chrome upload-format candidate with a **visible but disabled** product-purchase section. It is intentionally not a ready-to-submit sales version. Seller's actual Agensi product URL is not verified, so this ZIP does not link to third-party listings, Agensi's homepage masquerading as checkout, or a referral URL.

**SHA-256:** `d430b5f707983b6f059441b53bfdf09acf73564591782d2d4c520fbf8abfa7fa`
**Original release ZIP SHA-256:** `81f3505b3535d53bf8910fda3ee8abe076e9160cdc1befce6a1c660a5c0def3f`

The RC14-v6 core is byte-for-byte unchanged:
- content.js SHA-256 `9039b7b543016ddf3589380ae559576c57ce0633a7e260979fcc2c49aea98f15`
- background.js SHA-256 `0477786da76bcb1dd764c736d536d1caa561d3baf02fbdcfaac2ec0f959ea47c`
- Permissions remain `nativeMessaging`, `tabs`, and only `https://chatgpt.com/*`, `https://muse.ai/*`.

## Independent website
A standalone static website ZIP is also prepared separately for user review:
- product landing page, GitHub release and an intentionally inactive purchase CTA
- independent Agensi overview page with an explicit affiliate disclosure and separate non-referral link
- no external analytics, JavaScript trackers, injected codes or automatic redirects
- no chosen domain and not yet deployed

The publisher-provided Agensi referral link is included **only in the independent website's voluntary page**, never this browser ZIP. The user formerly supplied `https://www.agensi.io/r/CREATOR1080E05C`. Verify Agensi terms before publication.

## Blocks before customer-facing use
1. Confirm the publisher's own Agensi product listing is approved and record the **exact product URL**. Prior listing note describes **“Agent Relay — Muse × ChatGPT Verified Discussions”** at intended **US$3 one-time**, previously pending review. Price and published status require verification. Do not use unrelated `AgentRelay` or `Agent Relay AI` products.
2. Replace disabled purchase CTA with an explicit opt-in link to the verified owner product URL; test actual checkout landing in browser.
3. Choose the independent website domain and deploy it deliberately (not on user's unrelated finance or newcomer sites by default).
4. Host an accurate Privacy Policy and support page; verify local Native Host data flow and retention.
5. Validate published Chrome Web Store extension ID and Native Host allowlist together.
6. Test Chrome candidate in a real Windows Chrome profile and confirm stop/uncertain-send behavior (previous headless extension load test timed out).
7. Finish CWS listing/screenshot/user-consent disclosures; submit only after owner's final approval.

## Status
- Standalone website **authored, not deployed**.
- Chrome product CTA **visibly prepared but disabled** pending verified seller link.
- Affiliate referral **segregated from extension**.
- Not a claim of Chrome Web Store acceptance.
