# Agent Relay

Open-source Windows tooling for verified message relay between Muse and ChatGPT.

**Status:** RC14 v6 public preview. Core functionality has been tested in an isolated Chrome environment, including a six-send/six-reply discussion run. An installation on a real Windows computer has also been used successfully. Long-running unattended operation and a clean-room Windows installation are **not yet validated**.

## What it does

- Uses a Chrome extension and Windows Native Messaging Host to communicate with supported chat tabs.
- Uses a Python coordinator for project state, message receipts, pause/resume and safe reconciliation.
- Fences duplicate dispatch and stops on uncertain delivery rather than retrying automatically.
- Provides a local, approval-gated execution path with limited scope.

## Before you install

Read the [English quick-start](docs/START-HERE-English.md) or [中文使用说明](docs/START-HERE-中文.md) first, once available. Verify the downloadable ZIP SHA-256 against the release's published checksum. Keep local approval PINs, browser cookies and personal logs private.

**Important:** Typing "start a discussion" into an ordinary Muse chat is not itself an automatic trigger. Muse needs access to local computer tools or an operator must call the coordinator. Creating a project does not itself send six messages.

## Version

RC14 v6 installer ZIP SHA-256 (for identifying the already-tested candidate):

`81f3505b3535d53bf8910fda3ee8abe076e9160cdc1befce6a1c660a5c0def3f`

This checksum identifies the frozen candidate; do not assume an asset is uploaded until it is visible in GitHub Releases.

## License

MIT. See [LICENSE](LICENSE).

## Security

Do not commit or share approval PINs, access tokens, cookies, credentials, raw user conversations, Native Host state journals or browser profiles. The project is a **pre-release**, not a promise of unattended production reliability.
