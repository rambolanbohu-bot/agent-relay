# Agent Relay RC14-v6 Windows Portable — Build & QA Report

## Status
- **2026-11-25, Australia/Sydney**
- Candidate: **REVIEW_ONLY / NOT PRODUCTION INSTALLED / UNSIGNED**
- Built from exact GitHub Release: https://github.com/rambolanbohu-bot/agent-relay/releases/tag/v1.0.0-rc14-v6
- Original full Release ZIP SHA-256: `81f3505b3535d53bf8910fda3ee8abe076e9160cdc1befce6a1c660a5c0def3f`
- Native Host EXE SHA-256: `0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de`
- Portable ZIP SHA-256: `0207ea6ff3da9e4716d391d3a2581156fdb7baf619f11fb7fd9648b768a2c8bb`
- ZIP bytes: 223674; files: 38; unchanged upstream runtime files: 29.

## What changed
**Added only:**
- `Register_Agent_Relay.cmd` / `Unregister_Agent_Relay.cmd` / `Check_Agent_Relay.cmd`
- `portable_host.py` Windows HKCU manager
- Chinese and English usage instructions
- Portable manifest and upstream integrity manifest
- Original project MIT LICENSE

**Kept byte-for-byte:** all included RC14-v6 core runtime files, including `content.js`, `background.js`, `transport/native_host.py`, compiled `transport/agent-relay-host.exe`, orchestrator and approval code. No new signing or ad/affiliate logic.

**Excluded from user ZIP:** legacy `install.bat`, `install.py`, `uninstall.bat`, `uninstall.py`, test harnesses, Windows installer E2E scripts and generated state files. These are not needed for standalone portable runtime.

## Checks completed
| Test | Result |
| --- | --- |
| Original Release digest verified | PASS |
| Original Release 88-file manifest | PASS 88/88 |
| Original EXE SHA-256 | PASS |
| EXE Authenticode Certificate Table size | 0 (no embedded certificate) |
| Portable file CRC and ZIP integrity | PASS |
| Runtime byte-for-byte comparison to original | PASS 29/29 |
| Portable Python syntax | PASS |
| Registration unit tests with isolated FakeRegistry | PASS 13/13 |
| Extracted ZIP registration / status / unregister simulated end-to-end | PASS |
| Native Host pre-existing registry overwrite refused by default | PASS |
| Repeated registration preserves PIN | PASS |
| Unregister restores previous opt-in registration & keeps logs | PASS |
| Missing or tampered EXE refused | PASS |
| Actual Windows user registry + Chrome Native Messaging E2E | NOT TESTED |
| Chrome Web Store-assigned extension ID compatibility | NOT TESTED |
| Defender SmartScreen / enterprise Smart App Control behavior | NOT TESTED |

## Safety properties
- User-specific HKCU key `Software\\Google\\Chrome\\NativeMessagingHosts\\com.agentrelay.host`; no HKLM.
- Host manifest created at `transport\\extension\\com.agentrelay.host.portable.json`.
- Manifest points to the EXE in the *same unzipped directory*. Do not move it while registered.
- Allowed origins exactly one real 32-character extension ID; wildcard rejected.
- Refuses replacing pre-existing host unless explicit `--replace-existing` specified.
- Saves original registry value and restores on unregister.
- No install or uninstall of Python; Python 3.8+ is still required.
- Approval PIN created on first registration only; never reset silently.
- No logs or user state deleted on unregister.
- No instruction to disable SmartScreen, Defender, or Windows security policies.

## Reviewer Windows acceptance steps (not performed yet)
1. On a clean Windows 10/11 test account, ensure Python 3.8+ installed; verify archive digest.
2. Extract under a permanent user-writable folder with a space in its path.
3. Run `Check_Agent_Relay.cmd` to show no existing record, then `Register_Agent_Relay.cmd`.
4. Confirm `reg query HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.agentrelay.host /ve` points at the portable JSON; ensure only one specific allowed origin.
5. Use a separate Chrome test profile to load approved candidate, confirm actual ID, connect Native Host, and exchange harmless nonce messages.
6. Test user stop, restart, uncertain delivery, and no resend. Distinguish from already verified core RC14-v6 acceptance.
7. Unregister; confirm prior registry entry restored (if intentionally replaced), user files and PIN preserved.
8. Check Windows reputation warnings without disabling any security controls.

Official Chrome Native Messaging documentation:
https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging/