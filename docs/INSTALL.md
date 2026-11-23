# 安装说明（INSTALL.md）

版本：v1.0.0-rc4。Windows 优先。**支持的安装路径是 Muse 会话里的首次安装向导**；`install.bat` 现在会调用 `install.py` 做真正的安装（检查、复制、自动生成 host 清单、写注册表、生成安装 PIN、写安装清单、失败回滚）。

## 1. 安装前确认

- Windows 电脑，装了 Chrome 浏览器。
- Chrome 里登录了 ChatGPT（chatgpt.com 能正常打开、能发消息）。
- 正在用 Muse（muse.ai）。
- Python 3.8+（装 Python 时勾选 "Add python.exe to PATH"；协调器与 native host 都需要 Python）。

## 2. 安装（两步）

1. 解压 `agent-relay-skill-v1.0.0-rc4.zip`，得到 `agent-relay-skill` 文件夹。
2. 在 Muse 里说一句话：**安装 Agent Relay**。Muse 会带你走首次安装向导。

也可以双击 `install.bat`：它找到 Python 后调用 `install.py`，安装器会先检查再动手——目标文件夹已存在就拒绝；注册表里已有 Native Messaging Host 项且指向别处时，交互会先问你，非交互直接拒绝；任何一步失败都会回滚。装好后它会：把 skill 文件夹复制到 `%USERPROFILE%\agent-relay-skill`；**自动生成 host 清单**（真实扩展 ID + 真实 .exe 路径，用户不用手动改 JSON、不用查扩展 ID、不用改注册表）；写注册表项；生成本地审批页的安装 PIN（**只显示一次，请记下来**）；写一份安装清单（`install-manifest.json`，记录本次创建的每一个路径/注册表项，供卸载时只清理这些）。

## 2b. Chrome 扩展与 native host（向导会带你走，手动步骤也在此）

向导的第 1 问通过后，会帮你装好浏览器适配器：

1. 打开 Chrome → `chrome://extensions` → 打开右上角“开发者模式” → 点“加载已解压的扩展程序”，选 `agent-relay-skill/transport/extension/` 文件夹。扩展 ID 是固定的（`jeelmedmciafjnfdpnjgbgipplcddhka`，manifest.json 里有固定 key），不用你查。
2. 注册 native host：**安装器已经自动做好了**——它生成了 `<目标>\transport\extension\com.agentrelay.host.json`（path 指向 `agent-relay-host.exe`，绝不是 .bat 或 .py），并写了注册表项 `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.agentrelay.host`。你只需要重启 Chrome。
3. 向导做一次连通检查：发一条 ping 经 native host 到扩展再回来；通不过就告诉你缺哪一步，不硬装。

**注意：以上步骤尚未在真实 Windows Chrome 上实测**（见 `docs/KNOWN-LIMITATIONS.md`）。扩展代码只做了语法与结构检查，native host 的往返只在本地模拟过；`agent-relay-host.exe` 是真实编译的 Windows 程序（mingw-w64 交叉编译，PE32+），但还没有在真实 Windows 上运行过。如果向导的连通检查不通过，讨论仍可用浏览器任务方式兜底（Muse 会话直接操作浏览器），只是没有扩展那条路快。要在真实 Windows 上验证整条链路（扩展 → host .exe → 协调器 → 状态记录 → 扩展），用 `windows_e2e_test/` 里的计划与脚本（隔离环境，不碰日常 Chrome 配置）；Windows E2E 在实测通过前不标 PASS。

## 3. 首次安装向导（Muse 一步一步问，每步只问一个选择）

**第 1 问——检查环境。** 向导会自己检查并告诉你结果：Chrome 是否打开、ChatGPT 是否登录、ChatGPT 标签页是否还在。哪项不过，就按提示处理好再继续；向导不会替你登录。

**第 2 问——选聊天方式。**

- **浏览器方式（默认，推荐）**：不用服务器，不用填地址，直接下一步。
- **服务器方式（只有你自己有 Relay 服务器才选）**：填你自己的 Relay 地址和你自己的 Bearer 令牌。令牌只存在你自己的环境里，绝不写进安装包或聊天记录。**绝不要填别人的地址或令牌。**

**第 3 问——文件放哪。** 讨论中要校验的文件存在哪里：

- 你自己的云盘（需你自己已登录可用）；
- 你自己的 GitHub 仓库（私有；向导只记录你填的仓库名，不替你建、不替你授权）；
- 或者“不存文件，只讨论文字”。

向导绝不会让你用别人的仓库或别人的云电脑。

**第 4 问——通知方式。** 有结论或要你做决定时怎么告诉你：

- 先在 Muse 会话里等你看（已验证，可用）；
- 手机推送（待验证：需你先在手机上装好 Muse 并登录，之后按 tests/acceptance_gates.md 做一次真实推送测试；向导会如实告诉你这项还没验证通过）。

**第 5 问——确认并完成。** 向导把你选的写进一份本地安装记录（只在你自己的电脑上），然后做一次冒烟测试：读一次 ChatGPT 最新回复；发一条带唯一标记的测试消息并等确认；检查全程不抢焦点。冒烟测试通过，向导结束。

## 4. 启动、停止、继续、卸载

- **启动讨论**：在 Muse 里说“开始讨论：……（你的问题）”。
- **查看进度**：说“查看进度”。
- **停止**：说“暂停讨论”。正在进行的那轮会写完记录再停，不丢进度。
- **继续**：说“继续讨论”，从断点接着来。继续前向导会检查 Chrome 是否还开着、ChatGPT 是否还登录；不满足会直接告诉你缺哪一项。
- **卸载**：双击 `uninstall.bat`（调用 `uninstall.py`），或直接删掉整个 `agent-relay-skill` 文件夹。卸载只清理本次安装创建的资源（读 `install-manifest.json`）；注册表项只在它仍指向本次安装时才删，安装时覆盖过的旧值会恢复回去。删之前会问你要不要保留讨论记录（状态文件）；选保留会先把状态文件备份到桌面再删，备份失败就拒绝删除。卸载不碰你的 Chrome、ChatGPT 登录状态和任何别的软件。

## 5. 升级

- 新版本就是一个新的 ZIP；解压后按第 2 节重新走向导。向导会问你要不要保留旧的状态文件（默认保留，讨论可以接着来）。
- 版本号规则：`v主版本.次版本.修订-候选标记`（例如 v1.0.0-rc4）。

## 6. 卸载后残留

- 卸载只删 skill 文件夹和（经你同意的）状态文件。
- 你的 Chrome、ChatGPT 登录状态、Muse 账号、你自己的 Relay 服务器（如果有）、你自己的 GitHub 仓库都不受影响。

## 7. 发布流程（给发布者：强制门槛，任何人不得跳过）

**没有任何 ZIP 可以在不跑发布门的情况下交付。** .exe 在传输途中被剥掉过两次（原 RC4 与第一份 hotfix：ChatGPT 收到的文件都没有 .exe，而交付的文件里明明有），所以“人工检查一下文件在不在”不够——发布必须跑 `tests/release_gate.py`，不通过不许发。

发布一个新 ZIP 的步骤（在包目录的上一级跑）：

```bash
python3 agent-relay-skill/tests/release_gate.py \
    --package-dir agent-relay-skill \
    --zip agent-relay-skill-v1.0.0-rc4-hotfix2.zip \
    --sha256 agent-relay-skill-v1.0.0-rc4-hotfix2.zip.sha256
```

发布门按顺序做六件事，任何一步失败都非零退出、不写 .sha256、并删掉刚建的 ZIP：

1. 删掉目标 ZIP 旁已有的 .sha256（失败的跑次不能留一个过期哈希）。
2. 从包目录当前内容（重新）生成 `MANIFEST.json`（每个文件 + SHA-256；见下）。
3. 跑 `tests/check_package.py --dir`（必需文件、.exe 哈希、清单与包目录一致）。
4. 从包目录建 ZIP（排序、去 `__pycache__` / `.pyc`）。
5. 跑 `tests/check_package.py --dir --zip`（ZIP 里的文件与哈希、ZIP 里的清单与包目录的清单逐字节一致）。
6. 全部通过才写 .sha256（写完再读一遍核对）。

**`MANIFEST.json`（在 ZIP 里面）**：列出包里每个文件 + SHA-256，外加 file_count 与 total_bytes。接收方可以马上核对完整性：数 ZIP 里的条目数、核对每个文件的哈希，发现传输途中被剥掉的文件（首先是 .exe）。清单故意不覆盖三类文件（清单本身写明）：MANIFEST.json 自己（自己不能给自己哈希）、`__pycache__` / `*.pyc`（字节码缓存，从不发）、`tests/test-output-*.txt`（每次跑测试字节都变——unittest 打印耗时秒数，含独立复现；哈希它们会让清单一跑测试就过期）。

**注意**：清单是发布时生成的，不是手工维护的。改了包里的任何文件后，清单就过期了——发布前必须重新跑发布门（它会重新生成清单），不要手工改 MANIFEST.json。测试套件里 `test_real_package_dir_passes` 会核对包目录的清单是否与当前内容一致；跑完测试套件后如果改了文件，重新生成清单再跑发布门。
