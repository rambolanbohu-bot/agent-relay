# Agent Relay RC14-v6 — Windows Portable 便携版

**状态：内部验收候选（未进行新版本 Windows 真机联调），不是 Chrome Web Store 已审核版本。**

## 本版本与原版的区别
- 保留 GitHub RC14-v6 原始核心代码，不重新编译或替换 Native Host EXE。
- **不运行原版 `install.bat`，不把程序复制到用户目录，不制作 Setup.exe/MSI。**
- 双击 `Register_Agent_Relay.cmd`，只在当前 Windows 用户的 HKCU 注册 Native Messaging Host，并在解压目录生成独立 Host 清单与登记记录。
- 双击 `Unregister_Agent_Relay.cmd` 撤销登记；不删除任何程序文件、对话日志或原有 PIN。
- 不购买、不生成 Windows Authenticode 代码签名。请勿因此关闭 SmartScreen、Defender、Smart App Control。

## 使用前
1. Windows 10/11（64 位）；**Python 3.8+** 须已安装，`py -3` 或 `python` 能在命令行正常运行。因为 RC14-v6 原始 EXE 仅负责启动 Python Native Host，此条件不可省略。
2. 从可信的 GitHub 发布渠道下载 ZIP，**先核对发布的 SHA-256**。
3. 解压到一个长期固定且本人可写的本地位置，例如 `%LOCALAPPDATA%\AgentRelayPortable\`。不要从 ZIP 内部直接运行，也不要放到 OneDrive 同步共享文件夹或需要管理员写权限的 `Program Files`。
4. 确认要使用的 Chrome 扩展 ID。默认 `jeelmedmciafjnfdpnjgbgipplcddhka` 是原 RC14-v6 解压测试扩展 ID。**Chrome 商店正式安装 ID 如果不同，必须指定实际 ID，不能直接沿用默认值**。
5. **如果旧版已注册**，便携脚本默认拒绝覆盖。不要先删除旧版。先备份其数据，并确认是否需要改用此便携版。

## 一键注册
双击 `Register_Agent_Relay.cmd`。脚本会：
- 验证原始 EXE 与随包 SHA-256 文件完全一致；
- 读取扩展 ID（仅接受 32 个 a–p 字符，不支持通配符）；
- 若已存在其他 Host 注册，**拒绝覆盖**，并报告路径；
- 在当前目录生成 `transport\extension\com.agentrelay.host.portable.json`；
- 将 `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.agentrelay.host` 指向该清单；
- 第一次初始化本地审批 PIN，**只显示一次**；重复注册不重置 PIN。

若商店 ID 不同，从命令提示符在这个文件夹执行：

```bat
Register_Agent_Relay.cmd --extension-id abcdefghijklmnopabcdefghijklmnop
```

请以 Chrome 扩展详情页面的**真实 ID** 替换示例，不要照抄。

## 如已有旧版 Host
**默认不会修改旧版注册。** 明确决定切换便携版、备份现有数据后，才在命令行手工执行：

```bat
Register_Agent_Relay.cmd --replace-existing --extension-id YOUR_ACTUAL_EXTENSION_ID
```

`YOUR_ACTUAL_EXTENSION_ID` 请替换为真实的 32 位 a–p 字母 ID。脚本会保存旧 Host 清单的注册表路径；撤销本次便携注册时会恢复原路径。不会复制或删除旧安装文件，也不会迁移旧版对话日志、PIN 或配置。

## 检查与撤销
- `Check_Agent_Relay.cmd`：只读显示本机登记状态。
- `Unregister_Agent_Relay.cmd`：只在注册表仍指向**本便携包**的 Host 清单时撤销，否则拒绝，避免误删其他安装。
- 撤销后保留解压目录、PIN 和所有对话数据。**先备份用户状态，再手动删除文件夹**。
- 移动或删除文件夹前必须先撤销登记；否则注册表仍指向旧地址，无法连接。

## Chrome 配套
Chrome Web Store 插件的 ZIP 与本 Windows Portable ZIP **分开分发**。Windows ZIP 不要上传 Chrome Web Store。Chrome 插件一旦正式安装，核对其扩展 ID 与 Native Host `allowed_origins` 相同；商店扩展和 Host 连接需要真实 Windows 用户态验证。

## 安全与隐私
- 不获取管理员权限；只修改该用户 HKCU 下的指定 Native Messaging Hosts 注册表项。
- 首次生成的审批 PIN 只在本机显示一次，文件里仅保存盐化哈希。请勿把 PIN 贴入聊天。
- 不植入广告、推广 Cookie 或 Agensi Affiliate 归因；付费购买属于 Chrome 插件和独立官网另行开展的业务。
- 本便携包内含 GitHub RC14-v6 既有未签名的 Windows EXE，已验证其 PE Authenticode Certificate Table 为 0；这不代表它不会被 SmartScreen/企业策略拦截。不要禁用系统安全防护；若被拦截，使用经过确认的签名发行版或在受控测试环境验证。
- 解压后的所有文件、讨论日志、PIN 属于用户本地数据；请勿将其公开分享。

## 验收情况
原始发布 ZIP SHA-256：`81f3505b3535d53bf8910fda3ee8abe076e9160cdc1befce6a1c660a5c0def3f`。
独立模拟 HKCU 注册表单元测试 13/13 PASS（见评审材料）；这**不等于 Windows 真机用户级注册、Chrome Web Store ID、SmartScreen 均 PASS**。

官方参考：https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging/