# Agent Relay RC14-v6 Portable Windows Host — Review Candidate

This is **not** an installer and is **not signed**. It is also **not yet verified on a clean Windows 10/11 user profile**.

**Requirements:** 64-bit Windows; Python 3.8+ accessible as `py -3` or `python`; separate Chrome extension. The original RC14-v6 EXE is only a launcher for Python.

## Quick setup
1. Verify the downloaded archive SHA-256 against the published digest.
2. Unzip to a permanent local user-writable directory, e.g. `%LOCALAPPDATA%\AgentRelayPortable`. Do not move the folder while registered.
3. Double-click `Register_Agent_Relay.cmd`. The script verifies the Host EXE checksum and writes **only** the current user's HKCU NativeMessagingHosts registration plus local manifest/record and an initial PIN hash.
4. Save the newly printed local approval PIN somewhere private. Do not paste it into chats.
5. Install the Chrome extension. **Confirm the actual extension ID** in Chrome. If the Web Store ID differs from the upstream test extension ID, re-register by running `Register_Agent_Relay.cmd --extension-id ACTUAL_CHROME_EXTENSION_ID`.
6. Check with `Check_Agent_Relay.cmd`.

## Existing Host registration
The script refuses to replace another `com.agentrelay.host` registration by default. After reviewing and backing up the old installation, use the explicit `--replace-existing` CLI flag to opt into replacing it. The previous registry value will be restored on unregister. No old files or user-state are migrated or removed.

## Unregister
Double-click `Unregister_Agent_Relay.cmd`. It only unregisters the host it owns; it leaves portable files, the approval PIN, discussion logs and user state untouched. Back up state before manually deleting the directory.

The Chrome Web Store extension ZIP is a separate artifact. Do not upload this Windows archive to the Store.

### Security boundaries
- No elevation / no system-wide registry changes.
- No silent replacement of preexisting Host; no wildcard extension origins.
- No bypass of SmartScreen, Defender or Windows security policy. An unsigned executable may be blocked; do not advise disabling protections.
- No ad/affiliate tracking in this portable host.
- Native Host and coordinator can access/save user chat text in local state and send messages to supported AI websites; review privacy disclosures.

Source: https://github.com/rambolanbohu-bot/agent-relay/releases/tag/v1.0.0-rc14-v6