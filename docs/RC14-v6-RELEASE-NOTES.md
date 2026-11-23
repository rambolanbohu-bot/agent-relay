# RC14 v6 — Public Pre-release Notes

Release date: 2026-11-23. License: MIT. Price: Free.

## Verified

- Windows Chrome extension + Native Host transport, with real Windows installation and use.
- Isolated Chrome background send and recovery tests.
- B5-A explicit rebinding and B5-B browser restart persistence.
- ATTEMPT-11: **6/6 sends and 6/6 replies in one run**, verified against independent native receipt records, authors, message hashes and nonce uniqueness.
- Release gate: **232/232 automated tests passed**, with 88 manifest-controlled files and 92 ZIP entries.
- Source and packaged executable SHA-256 verified.

## Security

Stops on uncertain delivery; does not automatically resend the same nonce. Local approval is required for constrained execution. Never share a PIN, secret, cookie or personal message ledger.

## Known limits

- Conversation text alone is not an automatic local command; Muse needs local computer-tool access or an operator must run the coordinator.
- Long-running unattended operation and clean-room Windows install/uninstall have not been fully certified.
- Development-mode unpacked Chrome extension, not Chrome Web Store.
- Some inherited packaged documentation references historic RC4 implementation. Follow these RC14 v6 guides.

## Frozen binary checksum

`agent-relay-skill-1.0.0-rc6-RC14-v6-REVIEW.zip`
SHA-256: `81f3505b3535d53bf8910fda3ee8abe076e9160cdc1befce6a1c660a5c0def3f`.

Only consider the installer downloadable when the asset is actually present on the GitHub Release page.