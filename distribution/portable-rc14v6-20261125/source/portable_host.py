#!/usr/bin/env python3
"""Agent Relay Portable Native Host registration, RC14-v6.

Does NOT copy/install software or require admin. Registers only HKCU; can
remove only its own registration. Existing RC14-v6 transport code is unchanged.
Python 3.8+ required, as the published Native Host EXE launches Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone

HOST_NAME = "com.agentrelay.host"
KEY = r"Software\Google\Chrome\NativeMessagingHosts" + "\\" + HOST_NAME
ORIGIN_RE = re.compile(r"[a-p]{32}\Z")


class PortableError(Exception):
    pass


class WinRegistry:
    def __init__(self):
        if os.name != "nt":
            raise PortableError("Windows only; run tests with FakeRegistry on other systems")
        import winreg
        self.api = winreg

    def get(self, key):
        try:
            with self.api.OpenKey(self.api.HKEY_CURRENT_USER, key) as h:
                v, kind = self.api.QueryValueEx(h, "")
                if kind != self.api.REG_SZ or not isinstance(v, str):
                    raise PortableError("Existing Host registry value is not REG_SZ; refuse changes")
                return v
        except FileNotFoundError:
            return None

    def set(self, key, value):
        with self.api.CreateKey(self.api.HKEY_CURRENT_USER, key) as h:
            self.api.SetValueEx(h, "", 0, self.api.REG_SZ, value)

    def delete(self, key):
        try:
            self.api.DeleteKey(self.api.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


class FakeRegistry:
    def __init__(self, initial=None):
        self.items = dict(initial or {})

    def get(self, key):
        return self.items.get(key)

    def set(self, key, value):
        self.items[key] = value

    def delete(self, key):
        self.items.pop(key, None)


def validate_extension_id(value):
    value = str(value or "").strip().lower()
    if not ORIGIN_RE.fullmatch(value):
        raise PortableError("Chrome extension ID must be exactly 32 letters from a to p")
    return value


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                                         prefix=".portable-", suffix=".tmp", delete=False) as f:
            name = f.name
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, str(path))
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def restore(path, old_bytes):
    if old_bytes is None:
        if path.exists():
            path.unlink()
    else:
        with open(path, "wb") as f:
            f.write(old_bytes)


class PortableManager:
    def __init__(self, root, registry):
        self.root = Path(root).resolve()
        self.registry = registry
        self.exe = self.root / "transport" / "agent-relay-host.exe"
        self.checksum = self.root / "transport" / "agent-relay-host.exe.sha256"
        self.native_host = self.root / "transport" / "native_host.py"
        self.manifest = self.root / "transport" / "extension" / "com.agentrelay.host.portable.json"
        self.record = self.root / "portable-registration.json"
        self.pin = self.root / "orchestrator" / "state" / "approval_pin.json"
        self.ext_file = self.root / "transport" / "extension" / "EXTENSION_ID.txt"

    def ensure_runtime(self):
        for p in [self.exe, self.checksum, self.native_host, self.ext_file,
                  self.root / "SKILL.md",
                  self.root / "approvals" / "local_approval_page.py",
                  self.root / "orchestrator" / "run.py"]:
            if not p.is_file():
                raise PortableError("Required RC14-v6 runtime file missing: " + str(p))
        expected = self.checksum.read_text(encoding="utf-8").split()[0].lower()
        if not re.fullmatch(r"[a-f0-9]{64}", expected) or sha256(self.exe) != expected:
            raise PortableError("Native Host EXE checksum mismatch; aborting")
        # C launcher uses MAX_PATH and looks for Python on the machine.
        if len(str(self.exe)) >= 245:
            raise PortableError("Path is too long for the original native host launcher; relocate ZIP")

    def default_extension_id(self):
        return validate_extension_id(self.ext_file.read_text(encoding="ascii").strip())

    def _load_record(self):
        if not self.record.exists():
            return None
        try:
            data = json.loads(self.record.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise PortableError("Registration record is corrupt, refuse changes: " + str(e))
        if (data.get("root") != str(self.root)
                or data.get("manifest") != str(self.manifest)
                or data.get("registry_key") != KEY
                or data.get("host") != HOST_NAME
                or not isinstance(data.get("prior_value"), (str, type(None)))):
            raise PortableError("Registration record fails safety checks; refuse changes")
        return data

    def status(self):
        r = self._load_record()
        return {
            "portable_root": str(self.root),
            "registry_key": r"HKCU\\" + KEY,
            "registry_value": self.registry.get(KEY),
            "expected_manifest": str(self.manifest),
            "owns_current_registration": bool(r and self.registry.get(KEY) == str(self.manifest)),
            "record_exists": bool(r),
            "approval_pin_exists": self.pin.exists(),
            "extension_id": r.get("extension_id") if r else None,
        }

    def register(self, extension_id=None, replace_existing=False, dry_run=False):
        self.ensure_runtime()
        extension_id = validate_extension_id(extension_id or self.default_extension_id())
        current = self.registry.get(KEY)
        old_record = self._load_record()
        ours = str(self.manifest)
        if current == ours and not old_record:
            raise PortableError("Registry points here but no ownership record exists; manual review required")
        if old_record and current not in (ours, None):
            raise PortableError("Registry changed since this portable registration; refuse overwrite")
        if current and current != ours and not replace_existing:
            raise PortableError("An existing Agent Relay Host registration is present. "
                                "Not overwritten. Back it up; use --replace-existing deliberately.")
        prior = old_record["prior_value"] if old_record else current
        data = {
            "name": HOST_NAME,
            "description": "Agent Relay RC14-v6 Portable Native Host",
            "path": str(self.exe),
            "type": "stdio",
            "allowed_origins": [f"chrome-extension://{extension_id}/"],
        }
        state = {
            "schema_version": 1,
            "host": HOST_NAME,
            "root": str(self.root),
            "registry_key": KEY,
            "manifest": ours,
            "extension_id": extension_id,
            "prior_value": prior,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "portable_version": "RC14-v6-portable-review",
        }
        if dry_run:
            return {"action": "dry-run", "extension_id": extension_id,
                    "registry_conflict": bool(current and current != ours),
                    "will_generate_pin": not self.pin.exists(),
                    "host_path": str(self.exe)}
        old_manifest_bytes = self.manifest.read_bytes() if self.manifest.exists() else None
        old_record_bytes = self.record.read_bytes() if self.record.exists() else None
        pin_was_present = self.pin.exists()
        pin = None
        try:
            # Initial PIN is needed for local approvals; preserve existing PIN on re-registration.
            if not pin_was_present:
                sys.path.insert(0, str(self.root / "approvals"))
                from local_approval_page import set_pin
                pin = set_pin(str(self.pin))
            atomic_json(self.manifest, data)
            atomic_json(self.record, state)
            self.registry.set(KEY, str(self.manifest))  # only registry mutation, last
        except Exception as exc:
            restore(self.manifest, old_manifest_bytes)
            restore(self.record, old_record_bytes)
            if not pin_was_present and self.pin.exists():
                self.pin.unlink()
            try:
                if current is None:
                    self.registry.delete(KEY)
                else:
                    self.registry.set(KEY, current)
            except Exception:
                raise PortableError("Partial failure and registry rollback failed; inspect HKCU key") from exc
            raise
        return {"action": "registered", "extension_id": extension_id,
                "manifest": str(self.manifest), "pin_new": pin is not None, "pin_once": pin,
                "previous_host_saved": prior is not None}

    def unregister(self, dry_run=False):
        r = self._load_record()
        if not r:
            raise PortableError("No portable registration record here; refusing to touch registry")
        current = self.registry.get(KEY)
        if current != str(self.manifest):
            raise PortableError("Registry no longer points at this portable Host; no changes made")
        if dry_run:
            return {"action": "dry-run-unregister", "would_restore_prior": r["prior_value"] is not None}
        prior = r["prior_value"]
        if prior is None:
            self.registry.delete(KEY)
        else:
            self.registry.set(KEY, prior)
        # Leave every user file, PIN, chat log, and EXE in place, only remove our generated metadata.
        if self.manifest.exists():
            self.manifest.unlink()
        if self.record.exists():
            self.record.unlink()
        return {"action": "unregistered", "previous_host_restored": prior is not None,
                "data_kept": True, "pin_kept": self.pin.exists()}


def main(argv=None):
    p = argparse.ArgumentParser(description="Agent Relay RC14-v6 portable host registration")
    p.add_argument("command", choices=("register", "unregister", "status"))
    p.add_argument("--extension-id", help="Chrome Store's ACTUAL 32-letter ID; default is unpacked RC14-v6 ID")
    p.add_argument("--replace-existing", action="store_true",
                   help="Explicitly replace existing Host; restore it on unregister")
    p.add_argument("--dry-run", action="store_true", help="Read-only check, no writes")
    args = p.parse_args(argv)
    if sys.version_info < (3, 8):
        print("Python 3.8 or newer is required", file=sys.stderr)
        return 2
    if os.name != "nt":
        print("Windows required to modify real HKCU registry; FakeRegistry is used in unit tests.",
              file=sys.stderr)
        return 2
    m = PortableManager(Path(__file__).parent, WinRegistry())
    try:
        if args.command == "register":
            r = m.register(args.extension_id, replace_existing=args.replace_existing,
                           dry_run=args.dry_run)
        elif args.command == "unregister":
            r = m.unregister(dry_run=args.dry_run)
        else:
            r = m.status()
        pin_once = r.pop("pin_once", None)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if pin_once:
            print("\nIMPORTANT: Local approval PIN (shown only once): " + pin_once)
            print("Keep this PIN private. Never paste it into a chat.")
        if args.command == "register":
            print("\nIf the Chrome Web Store extension ID differs, re-run with --extension-id ACTUAL_ID.")
            print("Portable folder must remain at this same path until it is unregistered.")
        return 0
    except PortableError as e:
        print("REFUSED (no intentional installation changes): " + str(e), file=sys.stderr)
        return 1
    except Exception as e:
        print("FAILED: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())