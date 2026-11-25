#!/usr/bin/env python3
"""Deterministic RC14-v6 Windows Portable review package from verified Release ZIP."""
from pathlib import Path
import hashlib, json, sys, zipfile
ROOT=Path("/workspace/agent-relay-cws-rc14v6")
UP=ROOT/"upstream.zip"
OUT=ROOT/"output"
OUT.mkdir(exist_ok=True)
ORIGINAL="81f3505b3535d53bf8910fda3ee8abe076e9160cdc1befce6a1c660a5c0def3f"
sha=lambda raw: hashlib.sha256(raw).hexdigest()
assert sha(UP.read_bytes())==ORIGINAL
with zipfile.ZipFile(UP) as z:
    assert z.testzip() is None
    m=json.loads(z.read("MANIFEST.json"))
    assert len(m["files"])==m["file_count"]==88
    for name,v in m["files"].items():
        assert sha(z.read(name))==v, f"Upstream integrity failure: {name}"
    # Runtime folders copied without alteration. Original installer and test harnesses are NOT shipped.
    runtime=[]
    for n in sorted(z.namelist()):
        if n=="SKILL.md" or n.startswith(("approvals/","orchestrator/","protocol/","transport/")):
            if n.endswith("/") or n.startswith("transport/tests/"):
                continue
            runtime.append(n)
    # Confirm exact native host EXE in this frozen RC14-v6 release.
    assert "transport/agent-relay-host.exe" in runtime
    assert sha(z.read("transport/agent-relay-host.exe"))=="0e6a9748685d48e435a7f07775bdb9ba020f1348661a154b9276e3bc37bf36de"
    extras={
        "portable_host.py":(ROOT/"portable_host.py").read_bytes(),
        "Register_Agent_Relay.cmd":(ROOT/"Register_Agent_Relay.cmd").read_bytes(),
        "Unregister_Agent_Relay.cmd":(ROOT/"Unregister_Agent_Relay.cmd").read_bytes(),
        "Check_Agent_Relay.cmd":(ROOT/"Check_Agent_Relay.cmd").read_bytes(),
        "README-PORTABLE-中文.md":(ROOT/"README-PORTABLE-中文.md").read_bytes(),
        "README-PORTABLE-English.md":(ROOT/"README-PORTABLE-English.md").read_bytes(),
        "ORIGINAL_MANIFEST_RC14v6.json":z.read("MANIFEST.json"),
    }
    # Add original MIT license from repository if available; publisher must verify.
    license_file=ROOT/"LICENSE"
    if license_file.exists():
        extras["LICENSE"]=license_file.read_bytes()
    files={n:z.read(n) for n in runtime}
    for n,b in extras.items():
        assert n not in files
        files[n]=b

report={
  "artifact_kind":"Windows Portable Native Host (NOT Chrome extension)",
  "review_status":"REVIEW_CANDIDATE_NOT_WINDOWS_VALIDATED",
  "source_release_url":"https://github.com/rambolanbohu-bot/agent-relay/releases/tag/v1.0.0-rc14-v6",
  "upstream_release_zip_sha256":ORIGINAL,
  "upstream_manifest_entries_verified":m["file_count"],
  "runtime_files_carried_byte_identically":len(runtime),
  "native_host_exe_sha256":sha(files["transport/agent-relay-host.exe"]),
  "native_host_authenticode_certificate_table_size":0,
  "registry_scope":"HKCU only, opt-in, reversible",
  "system_admin_required":False,
  "windows_traditional_installer":False,
  "code_signing_added":False,
  "python_runtime_required":"3.8+",
  "default_unpacked_extension_id":"jeelmedmciafjnfdpnjgbgipplcddhka",
  "store_extension_id":"Not validated; must be checked after store upload",
  "privacy":"Local state logs may contain sensitive chat text; no secrets prepopulated",
  "known_blockers":["Real Windows 10/11 user-profile E2E pending","Chrome Web Store final extension ID pending","Windows SmartScreen and security-policy behavior not validated","Portable and existing host migration must be tested on isolated computer"],
  "upstream_files":{n:sha(files[n]) for n in runtime},
  "added_files":{n:sha(files[n]) for n in extras}
}
files["PORTABLE_MANIFEST.json"]=(json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
name="Agent_Relay_Windows_Portable_RC14-v6_REVIEW.zip"
dest=OUT/name
with zipfile.ZipFile(dest,"w") as zout:
    for n,b in sorted(files.items()):
        zi=zipfile.ZipInfo("AgentRelayPortable/"+n,(2026,11,25,0,0,0))
        zi.compress_type=zipfile.ZIP_DEFLATED
        zi.external_attr=(0o644<<16)
        zout.writestr(zi,b,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
with zipfile.ZipFile(dest) as z:
    assert z.testzip() is None
    assert len(z.namelist())==len(files)
    assert z.read("AgentRelayPortable/transport/agent-relay-host.exe")==files["transport/agent-relay-host.exe"]
    assert all(not s.startswith("AgentRelayPortable/install.") and not s.startswith("AgentRelayPortable/uninstall.") for s in z.namelist())
    assert not any(s.endswith(".pyc") or "/state/" in s for s in z.namelist())

digest=sha(dest.read_bytes())
(OUT/(name+".sha256")).write_text(digest+"  "+name+"\n",encoding="utf-8")
(OUT/"PORTABLE_BUILD_REPORT.json").write_text(json.dumps({
    "archive":name,"sha256":digest,"size_bytes":dest.stat().st_size,
    "contents":len(files),"upstream_hash":ORIGINAL,
    "runtime_files_untouched":len(runtime),"unit_tests":"13/13 PASS; FakeRegistry simulation only",
    "real_windows_test":"PENDING",
},ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"archive":str(dest),"sha256":digest,"bytes":dest.stat().st_size,"files":len(files),"runtime_files_untouched":len(runtime),"extras":list(extras)},ensure_ascii=False,indent=2))