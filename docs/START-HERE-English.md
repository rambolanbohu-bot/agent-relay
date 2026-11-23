# Agent Relay RC14 v6 — Windows Quick Start

**Public pre-release.** This tool is a Chrome extension + Windows Native Messaging Host + Python coordinator for exchanging and validating real messages between Muse and ChatGPT.

### Requirements and installation

You need Windows, Google Chrome, Python 3, and signed-in Muse and ChatGPT sessions. Verify Python with `py -3 --version`.

Download the ZIP and matching `.sha256` from GitHub Releases **only after the release assets appear**. Check the ZIP:

```powershell
(Get-FileHash ".\agent-relay-skill-1.0.0-rc6-RC14-v6-REVIEW.zip" -Algorithm SHA256).Hash
```

Expected SHA-256: `81F3505B3535D53BF8910FDA3EE8ABE076E9160CDC1BEFCE6A1C660A5C0DEF3F`. Do not install if it differs.

Extract the ZIP, run `install.bat` from the extracted `agent-relay-skill` directory, and save the one-time local approval PIN privately. Default install path is `%USERPROFILE%\agent-relay-skill`.

In Chrome open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select `%USERPROFILE%\agent-relay-skill\transport\extension`. Enable **Agent Relay Browser Adapter RC14-v6** and refresh both chat tabs. This is not a Chrome Web Store extension.

### Read-only connectivity checks

```powershell
$root = Join-Path $env:USERPROFILE 'agent-relay-skill'
py -3 "$root\transport\adapter.py" --skill-root "$root" health --site chatgpt
py -3 "$root\transport\adapter.py" --skill-root "$root" health --site muse
```

Both should report `ok=true` and `document_readiness_verified=true`. Wait while `streaming=true`. If `ambiguous_site_tabs_explicit_binding_required` appears, close extra matching tabs or have a local operator explicitly bind the correct tab. Production Host: `com.agentrelay.host`, not the isolated `.e2e11` Host.

### Discussion workflow

Ask Muse to use its local computer-tool access to health-check both sites, create a Discussion project, and coordinate real turns with ChatGPT. **Typing a request into an ordinary chat does not itself trigger the local coordinator.** Verify the project ID and actual Native Host receipts.

Operator commands:

```powershell
$root = Join-Path $env:USERPROFILE 'agent-relay-skill'
py -3 "$root\orchestrator\run.py" --skill-root "$root" create --topic "Example topic" --mode discussion
py -3 "$root\orchestrator\run.py" --skill-root "$root" status
py -3 "$root\orchestrator\run.py" --skill-root "$root" status --project-id "REAL_PROJECT_ID"
py -3 "$root\orchestrator\run.py" --skill-root "$root" pause --project-id "REAL_PROJECT_ID" --reason "manual review"
py -3 "$root\orchestrator\run.py" --skill-root "$root" resume --project-id "REAL_PROJECT_ID"
py -3 "$root\orchestrator\run.py" --skill-root "$root" reconcile --project-id "REAL_PROJECT_ID"
```

`create` creates a project but does not automatically send six messages. `advance` requires a genuinely produced reply and the correct `--reply-file`. Do not reuse fabricated responses.

### Safety, errors and scope

A true three-round PASS requires six unique sends and six real replies in one run, correct authors and content hashes, and zero unresolved records. If `UNCERTAIN`, **stop; never blindly resend**. Compare the native receipt and chat history before any recovery.

To uninstall, save needed logs, run `uninstall.bat`, then remove the extension from Chrome. Keep PINs, cookies, credentials and private chat logs secret.

Validated: isolated Chrome B4/B5 and six-send/six-reply run, plus a real Windows install and discussion. **Not yet fully validated**: clean-room first installation, unattended long-term operation, Firefox, mobile, or automatic Muse wake-up.

Licensed under MIT; the installer is free.