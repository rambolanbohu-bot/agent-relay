# Relay 服务器规范：按参与方发令牌、按令牌强制 sender（v1.0.0-rc4）

版本：v1.0.0-rc4。给**自己搭 Relay 服务器的用户**（或 Relay 的实现者）
看。浏览器方式（默认）不用 Relay 服务器，不用看这份文件。

## 0. 为什么需要这份规范（Security-2）

客户端的 `sender == "chatgpt"` 检查（`relay_client.py`）只能核对
sender **字段的值**，不能证明消息真的来自 ChatGPT 会话。任何人
只要拿到一个能写消息的令牌，都可以在字段里写 `sender=chatgpt`。
所以真正的来源保证必须在 **Relay 服务器一侧**强制执行；
客户端检查只是纵深防御，绝不能单独宣称“证明了来源”。

浏览器方式的来源保证是另一条路：扩展从 chatgpt.com 标签页本身
读回复，来源绑定到页面 origin（见 `transport/extension/README.md`）。

## 1. 按参与方发令牌

Relay 必须给每个参与方发**不同的 Bearer 令牌**，并在服务器端记录
令牌与参与方的绑定关系：

| 令牌 | 只能以哪个 sender 写消息 | 用途 |
|---|---|---|
| ChatGPT 的令牌 | `chatgpt` | ChatGPT 会话向 Relay 写消息 |
| Muse 的令牌 | `muse` | Muse 侧客户端向 Relay 写消息 |
| Codex 的令牌（如果有） | `codex` | Codex 只能以 `codex` 身份写，绝不能写 `chatgpt` |

令牌的发放与轮换由 Relay 的运营者（用户自己）负责；本包不提供
Relay 服务器实现，只规定它必须满足的接口行为。

## 2. 服务器端强制规则（必须实现）

1. **写消息时核对 sender**：`POST /v1/messages/reply`（以及任何写
   消息的接口）必须检查请求里 `sender` 字段与 Bearer 令牌绑定的
   参与方是否一致。不一致 → 返回 **403**，不写库，并记一条审计日志
   （时间、令牌标识、声称的 sender、拒绝原因；**不记令牌明文**）。
2. **读消息时不改 sender**：`GET /v1/messages/next` 返回的消息，
   sender 字段必须是写入时服务器核对过的那个值；服务器绝不能按
   请求方的要求改写 sender。
3. **令牌泄露处理**：任一令牌泄露 → 运营者立即吊销并重发；旧令牌
   的写请求一律 401。
4. **审计日志**：所有写请求记一条审计记录（时间、参与方、message_id、
   结果）；拒绝的写请求也要记。
5. **传输**：只接受 HTTPS（或 Tailscale 私有地址）；明文 HTTP 的
   Relay 地址一律不接受。

## 3. 客户端的责任（不变）

- `relay_client.py` 继续核对 `sender == "chatgpt"` 才当作 ChatGPT
  的发言；其他 sender 一律拒绝（`untrusted_sender`，退出码 1），
  讨论停止。
- 客户端检查 + 服务器端强制，两层都要有；缺任何一层，都不能宣称
  “来源已验证”。

## 4. 仍未验证的事项

- Relay 服务器本身尚未实现（本包没有 Relay 服务器代码）；上述
  强制规则尚未在真实 Relay 上验证。
- Tailscale 尚未加入（状态 Not connected，2026-11-19 复查）；
  Relay 地址与令牌尚未提供。
- 见 `docs/KNOWN-LIMITATIONS.md`。
