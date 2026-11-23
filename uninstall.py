#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — Windows 卸载器（uninstall.py）.

由 uninstall.bat 调用（或直接运行：python uninstall.py）。
卸载安全规则（RC3，ChatGPT 审核要求）：
- 只清理本次安装创建的资源：读 install-manifest.json，里面列出的
  路径/注册表项才删；清单之外的东西一律不动。
- 注册表项只在它“仍然指向本次安装的清单”时才删；如果它后来被
  改成了别的值，留着它并报告，不删。
- 如果安装时覆盖过一个旧的注册表值，卸载时把它恢复回去。
- 删之前先备份讨论记录（--keep-state）：备份失败就拒绝删除。
- 目标文件夹必须确实是 skill 文件夹（里面有 SKILL.md，且路径里
  含 agent-relay-skill），否则拒绝删除，防止误删。

用法：
    python uninstall.py [--dest <dir>] [--keep-state]
                        [--non-interactive]
    --keep-state：先把讨论记录备份到桌面再删；备份失败拒绝删除。
    不带 --keep-state：讨论记录随 skill 文件夹一起删。

退出码：0 成功；1 拒绝/失败；2 用法错误。
注意：本文件只在 Windows 上写注册表；单元测试用 FakeRegistry。
"""

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from install import (FakeRegistry, InstallError, MANIFEST_FILE,  # noqa: E402
                     REG_KEY, WindowsRegistry)


def default_dest():
    home = os.path.expanduser("~")
    return os.path.join(home, "agent-relay-skill")


def _is_skill_dir(path):
    return ("agent-relay-skill" in path
            and os.path.exists(os.path.join(path, "SKILL.md")))


def uninstall(dest_dir, registry, keep_state=False, backup_dir=None,
              non_interactive=False, input_fn=input):
    """Uninstall from dest_dir using its install manifest.

    Returns a dict of what was removed. Raises InstallError on refusal.
    """
    if not _is_skill_dir(dest_dir):
        raise InstallError(
            f"目标不是 skill 文件夹，拒绝删除：{dest_dir}")
    manifest_path = os.path.join(dest_dir, MANIFEST_FILE)
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            record = json.load(f)
    except OSError:
        raise InstallError(
            f"找不到安装清单 {manifest_path}。没有清单就不知道本次安装"
            "创建了哪些资源，为防止误删，拒绝自动卸载。"
            "请手动删除该文件夹，或先确认清单。")
    # 1. Optional state backup (must succeed before anything is deleted).
    state_dirs = []
    for rel in ("orchestrator/state", "transport/state"):
        p = os.path.join(dest_dir, rel)
        if os.path.isdir(p):
            state_dirs.append(p)
    if keep_state and state_dirs:
        backup_dir = backup_dir or os.path.join(
            os.path.expanduser("~"), "Desktop", "agent-relay-state-backup")
        try:
            os.makedirs(backup_dir, exist_ok=True)
            for src in state_dirs:
                name = os.path.basename(os.path.dirname(src)) + "-" + \
                    os.path.basename(src)
                shutil.copytree(src, os.path.join(backup_dir, name),
                                dirs_exist_ok=True)
        except OSError as e:
            raise InstallError(
                f"备份讨论记录失败（{e}），拒绝删除。你的记录还在 "
                f"{dest_dir} 里，没有动。")
        # Backup must be non-empty.
        if not any(os.listdir(backup_dir)):
            raise InstallError("备份目录是空的，拒绝删除。")
    # 2. Registry: only remove it if it still points at OUR manifest.
    # RC4-hotfix FIX 3: the registry key comes from the install
    # manifest (record.get("registry_key")), not from the REG_KEY
    # constant — a test install (host com.agentrelay.host.e2e) must
    # remove the TEST key, never the production key. Old manifests
    # without registry_key fall back to the production key.
    reg_key = record.get("registry_key") or REG_KEY
    current = registry.get(reg_key)
    expected = record.get("host_manifest")
    registry_action = "none"
    if current is None:
        registry_action = "already_gone"
    elif current == expected:
        prior = record.get("registry_prior_value")
        if prior is not None:
            registry.set(reg_key, prior)
            registry_action = "restored_prior"
        else:
            registry.delete(reg_key)
            registry_action = "deleted"
    else:
        registry_action = "left_alone_changed"
    # 3. Delete only the paths the manifest lists (the skill folder).
    removed = []
    for path in record.get("created_paths", [dest_dir]):
        if os.path.isdir(path) and not os.path.islink(path):
            if not _is_skill_dir(path):
                raise InstallError(
                    f"清单里的路径不是 skill 文件夹，拒绝删除：{path}")
            shutil.rmtree(path, ignore_errors=False)
            removed.append(path)
        elif os.path.exists(path):
            os.remove(path)
            removed.append(path)
    return {"removed": removed, "registry": registry_action,
            "registry_key": reg_key,
            "backup_dir": backup_dir if keep_state else None}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay Skill uninstaller (Windows)")
    parser.add_argument("--dest", default=None,
                        help="installed skill folder (default: "
                             "%USERPROFILE%\\agent-relay-skill)")
    parser.add_argument("--keep-state", action="store_true",
                        help="back up discussion state to the Desktop first")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args(argv)
    dest = args.dest or default_dest()
    if os.name != "nt":
        print("uninstall.py: 本卸载器只在 Windows 上写注册表；"
              "当前系统不是 Windows。", file=sys.stderr)
        print("（单元测试用 FakeRegistry；见 tests/test_install.py。）")
        return 2
    if not args.non_interactive:
        answer = input(
            f"将要卸载 Agent Relay Skill（{dest}）。继续吗？[y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("已取消，没有改动。")
            return 0
    try:
        result = uninstall(dest, WindowsRegistry(),
                           keep_state=args.keep_state,
                           non_interactive=args.non_interactive)
    except InstallError as e:
        print(f"卸载拒绝/失败：{e}", file=sys.stderr)
        return 1
    print("卸载完成。")
    print(f"  已删除：{result['removed']}")
    print(f"  注册表：{result['registry']}")
    if result["registry"] == "left_alone_changed":
        print("  注意：注册表项后来被改成了别的值，留着没动，"
              "请手动检查。")
    if result.get("backup_dir"):
        print(f"  讨论记录已备份到：{result['backup_dir']}")
    print("你的 Chrome、ChatGPT 登录状态和 Muse 账号不受影响。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
