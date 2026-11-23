#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc4 — Windows 安装器（install.py）.

由 install.bat 调用（或直接运行：python install.py）。
安装器安全规则（RC3，ChatGPT 审核要求）：
- 安装前先检查，绝不悄悄覆盖：目标文件夹已存在 → 拒绝并报告；
  Native Messaging Host 注册表项已存在且指向别处 → 交互时询问，
  非交互时拒绝并报告。
- 安装失败必须回滚：删掉已建的文件，恢复被覆盖的注册表旧值。
- 卸载只清理本次安装创建的资源：安装清单（install-manifest.json）
  记录本次创建的每一个路径/注册表项，卸载时只删清单里的东西
  （见 uninstall.py）。

安装步骤：
  1. 定位 skill 源文件夹（本文件所在的文件夹）。
  2. 检查目标与注册表（见上）。
  3. 复制 skill 文件夹到 %USERPROFILE%\\agent-relay-skill
     （跳过 __pycache__ / *.pyc）。
  4. 检查 agent-relay-host.exe 在位（没有它就拒绝——host 清单的
     path 永远指向 .exe，绝不回退到 .bat 或 .py）。
  5. 自动生成 host 清单：真实扩展 ID
     （transport/extension/EXTENSION_ID.txt）+ 真实 .exe 路径，
     写到 <目标>\\transport\\extension\\com.agentrelay.host.json。
     用户不需要手动改 JSON、不用查扩展 ID、不用改注册表。
  6. 写注册表项
     HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\
     com.agentrelay.host（默认值 = 上一步的清单路径）。
  7. 生成本地审批页的安装 PIN（只显示一次），只存加盐哈希。
  8. 写安装清单 install-manifest.json。
  9. 任何一步失败 → 回滚（恢复原状），退出码 1。

用法：
    python install.py [--dest <dir>] [--non-interactive]
    python install.py --check-only   （只做检查，不安装）
    python install.py --host-name com.agentrelay.host.e2e
        （测试安装：只写测试专用的注册表项，不碰正式的
        com.agentrelay.host；Windows E2E 测试用这个，见
        windows_e2e_test/run_e2e_test.bat）

退出码：0 成功；1 拒绝/失败（已回滚）；2 用法错误。
注意：本文件只能在 Windows 上真正安装（要写注册表）；在别的系统
上运行时，注册表操作会明确报错并回滚。单元测试用 FakeRegistry。
"""

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "approvals"))
sys.path.insert(0, os.path.join(HERE, "orchestrator"))

HOST_NAME = "com.agentrelay.host"
DEFAULT_HOST_NAME = "com.agentrelay.host"
REG_KEY = ("Software\\Google\\Chrome\\NativeMessagingHosts\\"
           + HOST_NAME)
EXTENSION_ID_FILE = os.path.join(
    HERE, "transport", "extension", "EXTENSION_ID.txt")
HOST_EXE_REL = os.path.join("transport", "agent-relay-host.exe")
HOST_MANIFEST_REL = os.path.join("transport", "extension",
                                 "com.agentrelay.host.json")
PIN_FILE_REL = os.path.join("orchestrator", "state", "approval_pin.json")
MANIFEST_FILE = "install-manifest.json"


class InstallError(Exception):
    """Refusal or failure; the installer rolls back and reports."""


# -- registry abstraction ----------------------------------------------------
#
# Windows: winreg. Anywhere else (tests): FakeRegistry (dict-backed).
# The installer never touches the registry except through this object.


class WindowsRegistry:
    def __init__(self):
        import winreg  # noqa: F401  (Windows only; raises on other OSes)
        self._winreg = winreg

    def get(self, key_path):
        try:
            with self._winreg.OpenKey(self._winreg.HKEY_CURRENT_USER,
                                      key_path) as key:
                value, _ = self._winreg.QueryValueEx(key, "")
                return value
        except FileNotFoundError:
            return None

    def set(self, key_path, value):
        with self._winreg.CreateKey(self._winreg.HKEY_CURRENT_USER,
                                    key_path) as key:
            self._winreg.SetValueEx(key, "", 0,
                                    self._winreg.REG_SZ, value)

    def delete(self, key_path):
        try:
            self._winreg.DeleteKey(self._winreg.HKEY_CURRENT_USER,
                                   key_path)
        except FileNotFoundError:
            pass


class FakeRegistry:
    """Dict-backed registry for tests (and for --check-only dry runs)."""

    def __init__(self, initial=None):
        self.values = dict(initial or {})

    def get(self, key_path):
        return self.values.get(key_path)

    def set(self, key_path, value):
        self.values[key_path] = value

    def delete(self, key_path):
        self.values.pop(key_path, None)


# -- installer ----------------------------------------------------------------


class Installer:
    def __init__(self, source_dir, dest_dir, registry,
                 non_interactive=False, input_fn=input,
                 host_name=DEFAULT_HOST_NAME):
        # RC4-hotfix FIX 3: the host name is a parameter, not a
        # constant. Production installs use "com.agentrelay.host";
        # the Windows E2E test installs with "com.agentrelay.host.e2e"
        # so the test never touches the production registry entry.
        # The name must be exactly com.agentrelay.host or under
        # com.agentrelay.host.* — a bare startswith would also accept
        # "com.agentrelay.hostx", a different key.
        if not isinstance(host_name, str) \
                or not (host_name == "com.agentrelay.host"
                        or host_name.startswith("com.agentrelay.host.")):
            raise InstallError(
                f"host 名不对：{host_name!r}（必须是 "
                "com.agentrelay.host 或 com.agentrelay.host.*）")
        self.host_name = host_name
        self.reg_key = ("Software\\Google\\Chrome\\"
                        "NativeMessagingHosts\\" + host_name)
        self.source_dir = os.path.abspath(source_dir)
        self.dest_dir = os.path.abspath(dest_dir)
        self.registry = registry
        self.non_interactive = non_interactive
        self.input_fn = input_fn
        self.created = []          # paths created (files/dirs), for rollback
        self.prior_registry = None  # (existed, value) before we touched it
        self.registry_changed = False

    # -- helpers ---------------------------------------------------------------

    def _confirm(self, prompt):
        if self.non_interactive:
            return False
        answer = self.input_fn(prompt + " [y/N] ").strip().lower()
        return answer in ("y", "yes")

    def _rollback(self):
        for path in reversed(self.created):
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        if self.registry_changed:
            if self.prior_registry is not None:
                try:
                    self.registry.set(self.reg_key, self.prior_registry)
                except OSError:
                    pass
            else:
                try:
                    self.registry.delete(self.reg_key)
                except OSError:
                    pass
        self.created = []
        self.registry_changed = False

    def _extension_id(self):
        try:
            with open(EXTENSION_ID_FILE, "r",
                       encoding="ascii") as f:
                ext_id = f.read().strip()
        except OSError as e:
            raise InstallError(f"找不到扩展 ID 文件：{e}")
        if not ext_id or len(ext_id) != 32 or not all(
                "a" <= c <= "p" for c in ext_id):
            raise InstallError(f"扩展 ID 文件内容不对：{ext_id!r}")
        return ext_id

    # -- steps -------------------------------------------------------------------

    def check(self):
        """Pre-install checks. Raises InstallError on refusal."""
        if not os.path.isdir(self.source_dir):
            raise InstallError(f"找不到 skill 源文件夹：{self.source_dir}")
        if not os.path.exists(os.path.join(self.source_dir, "SKILL.md")):
            raise InstallError("源文件夹里没有 SKILL.md，不是 skill 文件夹")
        exe = os.path.join(self.source_dir, HOST_EXE_REL)
        if not os.path.exists(exe):
            raise InstallError(
                "找不到 agent-relay-host.exe——host 清单的 path 永远指向 "
                ".exe，绝不回退到 .bat 或 .py。请先在 Windows 上用 "
                "transport\\native_host\\build_host_exe.bat 重新编译，"
                "或用包里已编译好的 .exe。")
        if os.path.exists(self.dest_dir):
            raise InstallError(
                f"目标已存在：{self.dest_dir}。为防止覆盖你已有的安装，"
                "本次安装拒绝继续。请先卸载旧版（uninstall.bat）或手动"
                "改名，再重新安装。")
        existing = self.registry.get(self.reg_key)
        self.prior_registry = existing
        if existing is not None:
            if not self._confirm(
                    f"注册表里已经有一个 Native Messaging Host 项：\n"
                    f"  {self.reg_key}\n  当前值：{existing}\n"
                    "继续安装会把它改成指向本次安装。是否继续？"):
                raise InstallError(
                    "注册表项已存在且指向别处，未经确认不覆盖。安装已"
                    "拒绝，没有改动任何东西。")

    def install(self):
        """Run the install. Returns the install manifest dict.
        Rolls back on any failure."""
        try:
            self.check()
            # 1. Copy the skill folder.
            shutil.copytree(
                self.source_dir, self.dest_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            self.created.append(self.dest_dir)
            # 2. Generate the real host manifest (real extension ID +
            #    real .exe path). The user never edits this by hand.
            ext_id = self._extension_id()
            exe_path = os.path.join(self.dest_dir, HOST_EXE_REL)
            manifest_path = os.path.join(self.dest_dir, HOST_MANIFEST_REL)
            manifest = {
                "name": self.host_name,
                "description": "Agent Relay native messaging host "
                               "(connects the Chrome extension to "
                               "orchestrator/run.py via the local file "
                               "state log)",
                "path": exe_path,
                "type": "stdio",
                "allowed_origins": [f"chrome-extension://{ext_id}/"],
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            # 3. Write the registry entry.
            self.registry.set(self.reg_key, manifest_path)
            self.registry_changed = True
            # 4. Install PIN for the local approval page (shown once).
            from local_approval_page import set_pin
            pin = set_pin(os.path.join(self.dest_dir, PIN_FILE_REL))
            # 5. Install manifest: everything this install created.
            manifest_record = {
                "version": "1.0.0-rc4",
                "dest_dir": self.dest_dir,
                "host_name": self.host_name,
                "host_manifest": manifest_path,
                "registry_key": self.reg_key,
                "registry_prior_value": self.prior_registry,
                "extension_id": ext_id,
                "pin_file": os.path.join(self.dest_dir, PIN_FILE_REL),
                "created_paths": list(self.created),
            }
            manifest_file = os.path.join(self.dest_dir, MANIFEST_FILE)
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest_record, f, ensure_ascii=False, indent=2)
            return manifest_record, pin
        except Exception:
            self._rollback()
            raise


def default_dest():
    home = os.path.expanduser("~")
    return os.path.join(home, "agent-relay-skill")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Agent Relay Skill installer (Windows)")
    parser.add_argument("--source", default=HERE,
                        help="skill source folder (default: this script's "
                             "folder)")
    parser.add_argument("--dest", default=None,
                        help="install destination (default: "
                             "%USERPROFILE%\\agent-relay-skill)")
    parser.add_argument("--non-interactive", action="store_true",
                        help="never ask; refuse instead of confirming")
    parser.add_argument("--check-only", action="store_true",
                        help="only run the pre-install checks")
    parser.add_argument("--host-name", default=DEFAULT_HOST_NAME,
                        help="Native Messaging host name (default: "
                             "com.agentrelay.host; the Windows E2E test "
                             "uses com.agentrelay.host.e2e so it never "
                             "touches the production registry entry)")
    args = parser.parse_args(argv)
    dest = args.dest or default_dest()
    if os.name != "nt":
        print("install.py: 本安装器只在 Windows 上写注册表；"
              "当前系统不是 Windows。", file=sys.stderr)
        print("（单元测试用 FakeRegistry；见 tests/test_install.py。）")
        return 2
    try:
        installer = Installer(args.source, dest, WindowsRegistry(),
                              non_interactive=args.non_interactive,
                              host_name=args.host_name)
    except InstallError as e:
        print(f"安装拒绝：{e}", file=sys.stderr)
        return 1
    try:
        if args.check_only:
            installer.check()
            print("检查通过：可以安装。")
            return 0
        record, pin = installer.install()
    except InstallError as e:
        print(f"安装拒绝/失败，已回滚：{e}", file=sys.stderr)
        return 1
    print("安装完成。")
    print(f"  位置：{record['dest_dir']}")
    print(f"  扩展 ID：{record['extension_id']}")
    print(f"  host 清单：{record['host_manifest']}")
    print(f"  注册表：HKCU\\{record['registry_key']}")
    print()
    print(f"安装 PIN（只显示一次，请记下来）：{pin}")
    print("这个 PIN 是本地审批页的身份验证；丢了它就批不了决策，"
          "需要重装才能重置。")
    print()
    print("下一步：")
    print("  1. 打开 Chrome → chrome://extensions → 打开“开发者模式”。")
    print("  2. 点“加载已解压的扩展程序”，选 "
          f"{record['dest_dir']}\\transport\\extension\\。")
    print("     扩展 ID 应该和上面显示的一致（manifest.json 里有固定 key）。")
    print("  3. 重启 Chrome。")
    print("  4. 在 Muse 里说“安装 Agent Relay”，向导会检查扩展与 "
          "native host 是否连通。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
