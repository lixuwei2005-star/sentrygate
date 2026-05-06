# SentryGate Resume Bullets

Use these as starting points for resumes, LinkedIn, GitHub profiles, or
internship applications. Keep the wording honest: SentryGate is a local MCP
security gateway prototype for selected MCP-routed tool calls.

## Chinese Resume Version

- 开发 SentryGate，本地 MCP 安全网关原型，用于将选定的 coding-agent 工具调用路由到统一的安全检查层。
- 实现基于规则的风险评分，将文件和命令请求分类为 `allow`、`require_approval` 或 `block`。
- 实现隐私脱敏逻辑，在工具输出和审计摘要返回前遮蔽常见密钥、数据库 URL、邮箱等敏感模式。
- 构建安全工具封装和内存审计日志，记录 MCP 工具调用的决策、风险分数、原因和脱敏摘要。
- 明确设计 MCP-only 保护边界：原型只保护通过 SentryGate MCP 服务路由的工具调用，不声称控制 Codex 内置工具或提供生产级沙箱。

## English Resume Version

- Built SentryGate, a local MCP security gateway prototype for routing selected coding-agent tool calls through a policy and masking layer.
- Implemented deterministic risk scoring that classifies file and command requests as `allow`, `require_approval`, or `block`.
- Added privacy masking for common sensitive patterns before returning tool output or audit summaries.
- Built safe tool wrappers and in-memory audit events that record decisions, risk scores, reasons, and masked summaries for SentryGate-routed calls.
- Documented a clear MCP-only enforcement boundary: the prototype protects SentryGate MCP tool calls and does not claim control over Codex built-in internal tools or production-grade sandboxing.

## 3-Bullet Concise Version

- Built SentryGate, a local MCP security gateway prototype for routing selected coding-agent tool calls through deterministic policy checks.
- Implemented secret masking, risk scoring, approval gating, hard blocking, and masked audit events for SentryGate-routed file and command operations.
- Preserved a clear MCP-only boundary, avoiding claims of production-grade sandboxing or control over Codex built-in internal tools.

## 5-Bullet Detailed Version

- Built a local MCP server that exposes protected tools for file reads, file writes, directory listings, and command requests.
- Implemented `SafeToolService` as the enforcement layer for workspace checks, execution decisions, risk scoring, privacy masking, and audit logging.
- Added deterministic risk decisions using `allow`, `require_approval`, and `block`, with approval-required operations held without execution in the current prototype.
- Masked common sensitive patterns before returning output and stored masked audit summaries instead of raw secret values.
- Added optional local LM Studio semantic review for eligible medium-risk calls, while preserving deterministic hard blocks and preventing model output from lowering risk.

## Wording To Avoid

Avoid these claims in resumes or interviews:

- Production-grade security.
- Enterprise-ready governance.
- Complete sandboxing.
- Full control over Codex built-in internal tools.
- Guaranteed attack prevention.
- Guaranteed detection of every secret or risky command.

Safer wording:

- Local prototype.
- MCP-routed tool calls.
- Selected tool calls.
- Demonstrates a gateway pattern.
- Common-pattern privacy masking.
- Rule-based risk scoring.
