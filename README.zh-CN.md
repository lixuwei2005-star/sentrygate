# SentryGate

SentryGate 是一个本地 MCP 安全网关原型，用来保护一部分经过它 MCP Server
路由的工具调用。它展示了确定性风险评分、隐私脱敏、审批拦截、硬阻断，以及
带脱敏摘要的本地审计事件。

<p align="center">
  <a href="README.md">
    <img src="https://img.shields.io/badge/English-README-blue" alt="English README">
  </a>
</p>

## 项目简介

SentryGate 位于 MCP 兼容的编码 Agent 与一组本地工具之间。它的目标不是替代
操作系统沙箱，也不是完整的企业治理平台，而是作为一个本地安全网关原型，演示
如何在工具调用进入文件系统或命令执行逻辑之前进行风险判断、输出脱敏和审计记录。

这个项目适合作为实习作品集或本地实验项目来展示安全边界设计、MCP 工具封装、
规则引擎、隐私保护和审计思路。它不是生产级安全产品。

## 快速演示

在 `backend` 目录运行本地 demo：

```powershell
cd backend
uv run python scripts/demo_sentrygate.py
```

这个 demo 会创建一个临时工作区，只使用假的 secret，并直接调用
`SafeToolService`。它不需要 Codex，也不需要正在运行的 MCP client。

它会演示：

- 读取安全文件，并在输出中脱敏检测到的 secret。
- 阻断敏感 `.env` 文件读取。
- 将写入操作标记为 `require_approval`，不会直接执行。
- 允许列出 demo 工作区内的目录。
- 将普通命令标记为 `require_approval`。
- 阻断危险命令模式。
- 在最后打印经过脱敏的审计事件。

示例输出和场景说明见 [docs/demo-output.md](docs/demo-output.md)。

## 我构建了什么

我构建了一个本地 MCP 安全网关原型，它可以放在 MCP 兼容的编码 Agent 和选定
本地工具之间。

当前已经实现的部分包括：

- 一个 MCP Server，暴露 SentryGate 文件读取、文件写入、目录列出和命令请求工具。
- `SafeToolService`，作为中心封装层，负责工作区检查、风险判断、执行决策、
  隐私脱敏和审计记录。
- 基于规则的风险评分，支持 `allow`、`block` 和 `require_approval` 三类决策。
- 在工具输出返回前进行隐私脱敏。
- 内存中的审计事件，并保存脱敏后的摘要。
- 可选的本地 LM Studio 语义复核层，仅在配置后用于符合条件的中风险调用；
  它不能覆盖确定性的硬阻断规则。

## 它保护什么

SentryGate 只保护经过 SentryGate MCP Server 路由的工具调用。

受保护的工作流应使用：

- `sentry_read_file`
- `sentry_write_file`
- `sentry_list_directory`
- `sentry_run_command`

对于这些经过 SentryGate 路由的调用，配置的 workspace root 是文件系统边界。
SentryGate 可以对请求进行评分，阻断敏感操作，将需要审批的操作挂起且不执行，
在返回输出前脱敏检测到的 secret，并记录可在本地查看的脱敏审计事件。

## 它不保护什么

SentryGate 不能拦截或控制 Codex 内置工具。

它也不保护：

- 绕过 SentryGate 工具的直接 shell 访问。
- 绕过 SentryGate 工具的直接文件系统访问。
- 通过其他 MCP Server 路由的操作。
- 作为完整沙箱的操作系统边界。
- 容器、虚拟机、内核、EDR、杀毒软件或云安全边界。
- 生产级审批工作流。
- 持久化的企业级审计治理。
- 所有可能的 secret 格式或危险命令形式。

workspace root 越宽，访问边界就越宽。用于受保护 demo 或实验时，应使用尽可能窄
且实际可用的 workspace root。

## 当前架构

```text
Codex / MCP Agent -> SentryGate MCP Server -> SafeToolService -> RiskScorer + PrivacyMasker + AuditStore
```

SentryGate MCP Server 是 `SafeToolService` 上的一层轻量适配器。
`SafeToolService` 负责 SentryGate 工具的工作区检查、风险判断、执行决策、
隐私脱敏和审计记录。

`RiskScorer` 会将每个请求分类为 `allow`、`block` 或 `require_approval`。
`PrivacyMasker` 会在输出返回前，把检测到的 secret 替换为稳定的 mask token。
`AuditStore` 记录经过脱敏的审计事件，供本地查看。

启用 LM Studio review 后，它会作为一个可选的本地语义复核层，用于符合条件的
中风险调用：

```text
RiskScorer -> optional LM Studio review for medium-risk calls -> conservative merge
```

确定性规则会先运行。LM Studio 不能降低风险，不能把 `require_approval` 变成
`allow`，也不能覆盖确定性的硬阻断。

## 当前功能

当前原型支持：

- 对 SentryGate MCP 工具调用进行 workspace root 边界检查。
- 文件读取、文件写入、目录列出和命令请求的安全封装。
- 基于规则的 allow / block / require_approval 决策。
- 对敏感文件读取和危险命令模式进行硬阻断。
- 对写入和命令执行等高风险操作进行审批拦截。
- 在返回工具输出前进行 secret 脱敏。
- 记录脱敏后的本地内存审计事件。
- 可选接入本地 LM Studio，对符合条件的中风险请求做保守语义复核。

这些功能用于本地原型和演示，不代表生产级隔离能力。

## 运行后端检查

在 `backend` 目录运行：

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run mypy app
```

## 启动 MCP Server

MCP Server 必须显式指定 workspace root。它不会默认使用当前工作目录、仓库根目录
或用户 home 目录。

使用 CLI 参数：

```powershell
cd backend
uv run python -m app.mcp.server --workspace-root C:\path\to\workspace
```

使用环境变量：

```powershell
cd backend
$env:SENTRYGATE_WORKSPACE_ROOT = "C:\path\to\workspace"
uv run python -m app.mcp.server
```

## Codex MCP 配置示例

可以配置 Codex 或其他 MCP 兼容 Agent，让它从 `backend` 目录启动本地
SentryGate MCP Server。workspace path 应使用绝对路径，并通过
`--workspace-root` 或 `SENTRYGATE_WORKSPACE_ROOT` 传入。

示例配置形态：

```json
{
  "mcpServers": {
    "sentrygate": {
      "command": "uv",
      "args": [
        "run",
        "python",
        "-m",
        "app.mcp.server",
        "--workspace-root",
        "C:\\path\\to\\workspace"
      ],
      "cwd": "C:\\path\\to\\sentrygate\\backend"
    }
  }
}
```

请根据你本地的 Codex MCP 配置方式调整这段配置。SentryGate 的保护只在 Agent
把受保护操作路由到 SentryGate MCP tools 时生效。

### 自动配置 Codex MCP

如果要自动配置 Codex Desktop 或 Codex CLI，请在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_codex_mcp.ps1 -WorkspaceRoot "C:\Users\LIXUWEI\Desktop\sentrygate-workspace"
```

这个脚本会编辑 `~/.codex/config.toml`，在写入前备份已有配置，并使用显式的
workspace root 和 JSONL 审计日志路径配置 SentryGate。运行后请重启 Codex
Desktop。

## AgentOps Dashboard

SentryGate 自带一个本地只读的 Streamlit dashboard，用于可视化 SentryGate
JSONL 审计日志。它是一个本地原型，用来查看由 MCP 路由的工具调用产生的脱敏审计
事件。它不是生产级监控，也不是完整沙箱。

### 1. 启动 MCP Server 并开启持久化 JSONL 审计日志

传入绝对的 workspace root 和审计日志路径，让 SentryGate 把脱敏审计事件写入
`.sentrygate/` 目录下的 JSONL 文件：

```powershell
cd backend
uv run python -m app.mcp.server --workspace-root C:/Users/LIXUWEI/Desktop/sentrygate-workspace --audit-log-path .sentrygate/audit_events.jsonl
```

审计日志路径相对于 `backend` 目录解析。每一次被处理的 MCP 工具调用都会向该
文件追加一行 JSON。

### 2. 通过 Codex 触发 MCP 调用

SentryGate MCP Server 启动后，让 Codex（或其他 MCP 兼容的 Agent）调用
SentryGate MCP tools，让审计事件不断累积。例如：

- `sentry_list_directory(".")`
- `sentry_read_file("README.md")`
- `sentry_read_file(".env")`
- `sentry_write_file("test.txt", "hello")`
- `sentry_run_command("rm -rf tmp")`

这些调用会覆盖 allow、block 和 `require_approval` 路径，并触发隐私脱敏和风险
评分。只有经过 MCP 路由的工具调用才会出现在审计日志中。

### 3. 启动 Dashboard

在另一个终端，从 `backend` 目录运行：

```powershell
cd backend
uv run streamlit run dashboard/agentops_dashboard.py
```

Streamlit 会在本地浏览器中打开 dashboard。默认读取
`backend/.sentrygate/audit_events.jsonl`。你可以在侧边栏中修改路径。

### Dashboard 展示的内容

- 总工具调用数。
- allow / block / require_approval 各自的计数。
- 已执行调用数。
- 平均延迟。
- 高风险事件数。
- 脱敏命中数（masked findings）。
- 各个 SentryGate 工具的调用次数。
- 决策分布。
- 风险评分分布。
- 主要风险原因（top risk reasons）。
- 最近事件列表。
- 事件详情视图，包含 `trace_id`、`span_id`、`latency_ms`、
  `arguments_summary` 和 `output_summary`。

### 安全边界

- Dashboard 是只读的。
- 它只读取 `.sentrygate/*.jsonl` 路径下的 SentryGate JSONL 审计日志。
- 它不会直接读取受保护的 workspace。
- 它不会执行命令。
- 它不会调用 MCP tools。
- 它不会暴露原始 secret，因为 SentryGate 的审计事件只保存脱敏后的摘要。

这是一个本地原型，只可视化经过 MCP 路由的工具调用。它不是生产级监控，也不是
完整沙箱。

## 本地 Demo

本地 demo 的入口是：

```powershell
cd backend
uv run python scripts/demo_sentrygate.py
```

demo 只用于展示 SentryGate 当前的本地行为。它使用临时 workspace 和假数据，
不会证明生产级隔离，也不能说明 SentryGate 可以控制 Codex 的内置工具。

## 安全限制

SentryGate 是一个本地 MCP 安全网关原型，不是生产级安全产品，也不是完整沙箱。

- 它只保护经过 SentryGate MCP Server 路由的 MCP 调用。
- 它不能拦截或控制 Codex 内置工具。
- 它不是 VM、容器、内核沙箱、EDR 或杀毒工具。
- 内存审计日志不是持久化数据，进程退出后会丢失。
- 当前审批行为只会返回 `require_approval`；还没有人工审批 UI 或延迟执行流程。
- 基于规则的检测可能漏掉新的命令形式或 secret 格式。
- 使用假数据的 demo 不能证明生产级隔离能力。
- 它不是企业级完整治理平台，也不能防止所有攻击。

## Roadmap

可能的后续工作：

- 持久化审计存储。
- 人工审批 UI 或审批 API。
- 更丰富的策略配置。
- 更稳健的命令解析覆盖。
- 前端审计 dashboard。
- 更完整的 MCP client 集成示例。
- 可选的部署加固实验。

这些是 roadmap 想法，不是当前原型能力的声明。
