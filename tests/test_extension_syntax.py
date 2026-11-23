#!/usr/bin/env python3
"""RC3 tests for the Chrome extension (condition 1: least privilege).

Checks manifest.json is valid JSON with minimal permissions (only
nativeMessaging + tabs — background.js calls chrome.tabs.query();
site scope chatgpt.com + muse.ai, never <all_urls>), that it carries
the fixed public key whose derived extension ID matches
EXTENSION_ID.txt, that content.js / background.js pass a syntax check
(node --check), and that neither script contains forbidden
capabilities (eval, innerHTML, focus stealing, tab creation, child
processes). Also checks the native host manifest template points at
the .exe launcher (never .bat / .py) with the real extension ID.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
EXT = os.path.join(PKG, "transport", "extension")

FORBIDDEN_SUBSTRINGS = (
    "eval(",
    "innerHTML",
    "window.focus",
    ".focus(",
    "chrome.tabs.create",
    "child_process",
    "exec(",
    "Function(",
)


import re


def _strip_js_comments(src):
    """Remove /* */ block comments so the forbidden check looks at code,
    not at comment text (which may legitimately mention e.g. 'never
    eval()ed'). Line comments are kept: stripping them would also strip
    '//' inside string literals such as 'https://...' and could hide real
    code."""
    return re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)


class TestExtension(unittest.TestCase):
    def test_manifest_valid_and_minimal(self):
        with open(os.path.join(EXT, "manifest.json"), "r",
                  encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest.get("manifest_version"), 3)
        # RC3: tabs added because background.js calls chrome.tabs.query().
        # Nothing else: still no <all_urls>, no file access, no cookies.
        self.assertEqual(sorted(manifest.get("permissions", [])),
                         sorted(["nativeMessaging", "tabs"]))
        host_perms = manifest.get("host_permissions", [])
        self.assertEqual(sorted(host_perms), sorted([
            "https://chatgpt.com/*", "https://muse.ai/*"]))
        self.assertNotIn("<all_urls>", host_perms)
        self.assertNotIn("<all_urls>",
                         json.dumps(manifest, ensure_ascii=False))
        self.assertIn("background", manifest)
        self.assertIn("content_scripts", manifest)
        matches = []
        for cs in manifest["content_scripts"]:
            matches.extend(cs.get("matches", []))
        self.assertEqual(sorted(matches), sorted([
            "https://chatgpt.com/*", "https://muse.ai/*"]))

    def test_fixed_extension_id_matches_key(self):
        """The manifest carries a fixed public key; Chrome derives the
        extension ID from it (first 16 bytes of SHA-256 of the DER
        public key, each nibble mapped to 'a'..'p'). The derived ID
        must equal EXTENSION_ID.txt, so the installer can write the
        real ID into the host manifest without asking the user."""
        with open(os.path.join(EXT, "manifest.json"), "r",
                  encoding="utf-8") as f:
            manifest = json.load(f)
        key_b64 = manifest.get("key")
        self.assertIsInstance(key_b64, str)
        der = base64.b64decode(key_b64)
        digest = hashlib.sha256(der).digest()[:16]
        derived = "".join(
            chr(ord("a") + ((b >> 4) & 0xF)) + chr(ord("a") + (b & 0xF))
            for b in digest)
        with open(os.path.join(EXT, "EXTENSION_ID.txt"), "r",
                  encoding="ascii") as f:
            recorded = f.read().strip()
        self.assertEqual(derived, recorded)
        self.assertEqual(len(recorded), 32)
        self.assertTrue(all("a" <= c <= "p" for c in recorded))

    def test_js_syntax_with_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available for JS syntax check")
        for name in ("content.js", "background.js"):
            proc = subprocess.run([node, "--check",
                                   os.path.join(EXT, name)],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0,
                             f"{name}: {proc.stderr}")

    def test_no_forbidden_capabilities(self):
        for name in ("content.js", "background.js"):
            with open(os.path.join(EXT, name), "r",
                      encoding="utf-8") as f:
                src = _strip_js_comments(f.read())
            for bad in FORBIDDEN_SUBSTRINGS:
                self.assertNotIn(bad, src, f"{name} contains {bad!r}")

    def test_native_host_manifest_template(self):
        with open(os.path.join(EXT, "com.agentrelay.host.json"), "r",
                  encoding="utf-8") as f:
            host = json.load(f)
        self.assertEqual(host.get("name"), "com.agentrelay.host")
        self.assertEqual(host.get("type"), "stdio")
        self.assertIn("allowed_origins", host)
        # RC3 Correction 1: the path MUST point at the .exe launcher,
        # never at a .bat or .py file.
        path = host.get("path", "")
        self.assertTrue(path.endswith("agent-relay-host.exe"), path)
        self.assertNotIn(".bat", path)
        self.assertNotIn("native_host.py", path)
        # RC3: the template carries the REAL extension ID (fixed key),
        # so the installer can generate the manifest without asking
        # the user to look the ID up.
        with open(os.path.join(EXT, "EXTENSION_ID.txt"), "r",
                  encoding="ascii") as f:
            ext_id = f.read().strip()
        self.assertIn(f"chrome-extension://{ext_id}/",
                      host["allowed_origins"])


if __name__ == "__main__":
    unittest.main()
