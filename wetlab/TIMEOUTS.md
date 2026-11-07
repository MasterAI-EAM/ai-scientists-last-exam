# 常驻等待模式：Harness 超时验证

环境：Harbor 0.25.0；记录日期：2026-11-07。Harbor 注册 46 个 agent，排除 oracle/nop 后共 44 个模型 harness。原生恢复验证与同步工具等待验证是两件事。

## 三层时限

1. 网关/传输：网关每次长轮询最多 20 秒，可按原实验编号重新连接；整个工具默认等待 90000 秒。断线不会提交或执行实验。
2. Harness 工具/turn：原生 CLI 可能有独立工具时限和自动后台返回。仅放宽 Harbor 时限不足以保证 Agent 保持等待。
3. Harbor/控制器：`blocking_agent_timeout_sec >= active_budget_sec + budget * wait_timeout_sec + 60`。等待计入总时限；不再沿用暂停模式的活跃预算截止和提交宽限期。

Harbor 0.25.0 的 `harbor/trial/trial.py` 在 `_run_agent_phase` 中使用 `asyncio.wait_for(..., timeout=timeout_sec)`；因此实验等待明确占用 Agent 总时限。框架为常驻模式生成扩展后的任务配置，超时后保留容器供核对。

## 当前策略与证据

- OpenClaw：已测版本固定 `2026.11.1 (4ffdd20)`。设置 `agents.defaults.timeoutSeconds`、`tools.exec.timeoutSeconds` 和 CLI `timeout`，在 `tools.deny` 中加入 `process`，让 exec 同步等待。该版本安装包的 `lazy-exec-tool-*.mjs` 根据可用 `process` 工具控制后台能力；`bash-tools-*.mjs` 默认会把前台采样限制在 120000 ms，故只增大 yield 参数无法解决。
- Terminus-2：Harbor 原生终端命令 duration 被限制为 60 秒（`harbor/agents/terminus_2/terminus_2.py`）。本地进程内适配在 `_execute_commands` 之后等待外部实验交付，再采样结果和继续推理；不靠模型反复发空命令等待。
- 其他 42 个：本版本没有常驻等待策略，启动常驻模式会拒绝；其暂停模式状态仍以 [VALIDATION.md](VALIDATION.md) 为准。下表不把总时限选项误当成单个工具支持 24h 的证据。

OpenClaw 的官方说明确认禁用 `process` 会使 exec 同步执行，并区分 exec 生命期与 yield 时间：[Exec tool](https://docs.openclaw.ai/tools/exec)、[Background exec](https://docs.openclaw.ai/background-process)。这些在线文档会变化，最终须以实际安装版本和实测为准。

| Harness | 常驻等待策略 | >=24h 配置能力 | >=24h 真实连续等待 |
| --- | --- | --- | --- |
| acp | 未适配；提交前拒绝 | 未确认 | 未运行 |
| terminus-2 | 已实现；短时真实模型验证见下文 | 原生采样上限 60s，由宿主循环延长等待 | 未运行 |
| claude-code | 未适配；提交前拒绝 | 未确认 | 未运行 |
| copilot-cli | 未适配；提交前拒绝 | 未确认 | 未运行 |
| code-puppy | 未适配；提交前拒绝 | 未确认 | 未运行 |
| aider | 未适配；提交前拒绝 | 未确认 | 未运行 |
| cline-cli | 未适配；提交前拒绝 | 未确认 | 未运行 |
| codex | 未适配；提交前拒绝 | 未确认 | 未运行 |
| cortex-code | 未适配；提交前拒绝 | 未确认 | 未运行 |
| cursor-cli | 未适配；提交前拒绝 | 未确认 | 未运行 |
| gemini-cli | 未适配；提交前拒绝 | 未确认 | 未运行 |
| antigravity-cli | 未适配；提交前拒绝 | 未确认 | 未运行 |
| antigravity-sdk | 未适配；提交前拒绝 | 未确认 | 未运行 |
| rovodev-cli | 未适配；提交前拒绝 | 未确认 | 未运行 |
| goose | 未适配；提交前拒绝 | 未确认 | 未运行 |
| grok-build | 未适配；提交前拒绝 | 未确认 | 未运行 |
| hermes | 未适配；提交前拒绝 | 未确认 | 未运行 |
| junie | 未适配；提交前拒绝 | 未确认 | 未运行 |
| kimi-code | 未适配；提交前拒绝 | 未确认 | 未运行 |
| kimi-cli | 未适配；提交前拒绝 | 未确认 | 未运行 |
| langgraph | 未适配；提交前拒绝 | 未确认 | 未运行 |
| deerflow | 未适配；提交前拒绝 | 未确认 | 未运行 |
| mini-swe-agent | 未适配；提交前拒绝 | 未确认 | 未运行 |
| nemo-agent | 未适配；提交前拒绝 | 未确认 | 未运行 |
| swe-agent | 未适配；提交前拒绝 | 未确认 | 未运行 |
| opencode | 未适配；提交前拒绝 | 未确认 | 未运行 |
| mimo | 未适配；提交前拒绝 | 未确认 | 未运行 |
| mcode | 未适配；提交前拒绝 | 未确认 | 未运行 |
| openclaw | 已实现；短时真实模型验证见下文 | 原生工具/turn 配置可设置，前台策略已接入 | 未运行 |
| openhands | 未适配；提交前拒绝 | 未确认 | 未运行 |
| openhands-sdk | 未适配；提交前拒绝 | 未确认 | 未运行 |
| pi | 未适配；提交前拒绝 | 未确认 | 未运行 |
| qwen-coder | 未适配；提交前拒绝 | 未确认 | 未运行 |
| devin | 未适配；提交前拒绝 | 未确认 | 未运行 |
| trae-agent | 未适配；提交前拒绝 | 未确认 | 未运行 |
| computer-1 | 未适配；提交前拒绝 | 未确认 | 未运行 |
| eve | 未适配；提交前拒绝 | 未确认 | 未运行 |
| fx | 未适配；提交前拒绝 | 未确认 | 未运行 |
| fx-dev | 未适配；提交前拒绝 | 未确认 | 未运行 |
| dspy-rlm | 未适配；提交前拒绝 | 未确认 | 未运行 |
| vibe | 未适配；提交前拒绝 | 未确认 | 未运行 |
| muse-code | 未适配；提交前拒绝 | 未确认 | 未运行 |
| strands | 未适配；提交前拒绝 | 未确认 | 未运行 |
| fabric | 未适配；提交前拒绝 | 未确认 | 未运行 |

## 可重跑的验证

- HTTP/CLI 回归：真实网关进程重启、等待进程被杀、结果响应丢失、重复等待、越权编号及等待截止。必须保持实验计数不变，交付事件只产生一次。
- Docker 回归：等待时容器 ID/StartedAt 不变、Running=true、Paused=false，独立心跳继续写入。
- 真实模型入口 `tests/run_blocking_live.py`：OpenClaw/Terminus-2 可以同时运行。使用指定 DeepSeek 模型、模拟人工回填、记录容器采样，最终由独立离线 verifier 校验签名实验账本并评分。原始记录保留在本机，不提交凭据或轨迹。
- 用 `--wait-seconds 86410` 才是 >=24h 实际等待。短时探针不验证宿主机休眠、一天的连接稳定性或供应商会话寿命；目前该项保持未验证。

## 本次短时真实复测结果

完整回归 `113 passed in 71.45s`，含 7 项实际 Docker 集成检查。最终同一版实现的真实模型复测：OpenClaw 等待 70.103 秒、Terminus-2 等待 70.221 秒；两者 Harbor 均无 harness 异常、容器身份与启动时间不变、无暂停/中间检查点、独立 verifier 的 reward=1。实际 Harbor 配置总时限为 90660 秒，未设置较小的 agent override/max。详情见 [VALIDATION.md](VALIDATION.md)。

验收同时检查模型 harness 的异常记录，不能仅凭 `wetlab finish` 和 reward 判定框架完整成功。>=24h 实测仍为未运行。
