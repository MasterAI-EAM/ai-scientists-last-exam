# AISLE MVP 验证与验收记录

核验日期：2026-11-02（Asia/Shanghai）。本报告记录软件 MVP 与真实云端/API 调用的证据；任务的科学验收、实验室就绪和正式湿实验成绩保持 pending。

## 实际交付

- 私有仓库：[nlz25/ai-scientists-last-exam](https://github.com/nlz25/ai-scientists-last-exam)。
- [贡献标准与数学契约](task-contribution-standard.zh-CN.md)、[可复制贡献模板](../templates/task/README.md)、[MVP 方案](mvp-implementation.zh-CN.md)。
- [三页可编辑框架](diagrams/aisle_framework.drawio)：中文主架构、贡献审核、真实实验闭环；参照用户 v19 样式，保留原始实验照片。
- 两个迁移案例：颜色优化、颜色禁区约束。权重与原始数据均作为受控外部资产。

## 版本与工程验证

运行代码指纹为 `dbb1382e8d9729ed92a2b9a77bde9dddd646296a24314c9e06c332bf95336c23`，覆盖 `src/aisle/**/*.py`。实际模型运行后重新计算一致。每个 run 另存任务包、Agent、worker 和 SDK 指纹；完整记录见 [local-verification.json](validation/local-verification.json)。Git 版本以本文件所在提交为准。

| 检查 | 实际结果 |
|---|---|
| Python / 依赖 | 本机 macOS 与腾讯云 Ubuntu 均为 uv managed Python 3.12.11，使用同一 uv.lock |
| 本机测试 | 63 passed，外部真实 LightGBM 资产测试未跳过 |
| 腾讯云服务器测试 | 63 passed，12.33 秒，外部模型资产测试未跳过 |
| Lint / 格式 | `uv run ruff check .` 与 `uv run ruff format --check .` 通过 |
| 贡献格式 | 两个案例和 `templates/task/task.yaml` 均通过 `aisle validate-task` |
| 指标 | CIEDE2000 标准参考对、SAFE/UNSAFE/UNKNOWN、禁区两端点、恢复/违规终止、QC 和缺测测试通过 |
| 账本与网关 | 并发重复提交、预算、结果重送、跨 run token、私有反馈隔离、工单不确定状态、样品不重复计数、campaign/Top-K 版本门槛测试通过 |
| Gateway 进程 | 腾讯云服务器 loopback health check 通过；测试进程随后停止 |
| CI | GitHub Actions `verify` 在每次 push / PR 检查安装、lint、格式、测试和两个案例的格式；状态见对应提交的检查 |

测试中的两个依赖警告涉及可选绘图库与 TestClient 接口弃用，未影响验证。任务迁移的较早专项结果单独保存在 [engineering-validation.json](../examples/tasks/engineering-validation.json)，不与最终 63 项检查混用。

## 模型 × harness × task 云端实测

[完整摘要](validation/live-smoke.json)与[逐 run 导出](validation/runs/)记录：2 个实际模型 × 2 种自建 harness × 2 个任务，共 8 个组合。模型为 `qwen3.6-plus` 与 `gpt-5.4`，后者 API 返回 `gpt-5.4-2026-03-05`；harness 为严格 JSON 和原生 function calling。每个组合的预算为 3 次实验。

8 个组合均正常完成，均在获得实验反馈后作出了后续决定；总计 23 次模型调用、22 次模拟实验。7 个组合执行 3 次实验，GPT tools 的安全任务在首轮反馈后主动结束。这是被测 Agent 的真实终止选择，记录为 `agent_finished`，没有强迫补做或筛掉该结果。最初检查脚本要求所有组合至少两次动作，因此报告过一次失败；随后以实际反馈是否被消费来核对闭环，使用原记录重生成报告，没有重跑挑选结果。

每个 run 使用真实的外部 LightGBM bundle：

`a52a7bb3c6af4f1807a285ef891ff7aff8021f1dd4df56af35fe9fc16ce24819`

该 bundle 在新适配器中的预测与原 PSI-Bench 实现逐值一致。8 份导出均从已保存的测量重新评分，`score_matches=true`。两个任务分别保存 [K=2 的工程选择记录](validation/engineering-selections.json)；其 `engineering_only=true`，不能授予正式真实实验资格。

这里的少量试运行验证工程闭环，不能支持模型优劣、harness 优劣或正式安全水平的统计结论。未达目标阈值或出现约束违规是任务结果，不是运行框架故障。

## 腾讯云网络与 ModelProxy

实测模板 `sdt-275tcueb`、域名 `ap-guangzhou.tencentags.com`、SDK `e2b-code-interpreter==2.11.6`。create、set_timeout、commands、files、kill 均已实际调用。

本次模板 DNS 正常，但外部 HTTPS 请求阻塞，直接模型请求超时，记录保存在 [direct-egress-failure.json](validation/direct-egress-failure.json)。采用两阶段 ModelProxy 后重新冻结运行：Sandbox 内 harness 构造请求；controller 原样转发模型 HTTP；响应先在平台持久化，再返回 Sandbox 解析、决定下一步。模型密钥留在 controller，私有 simulator/verifier 也不进入 Sandbox。

响应已收到而后续 RPC 中断时可以复用保存的响应；请求状态不明时记录 `usage_unknown_calls`，不声称零成本。服务器的依赖下载与模型出网使用用户已有 SSH 转发代理 `127.0.0.1:17897`；服务器复用该网络条件运行，不能把无代理的网络路径视为已验证。

## 人工实验等待／恢复演练

实际在腾讯云服务器运行 controller，在腾讯云 Sandbox 运行 Qwen tools harness，分开调用 start → return → resume → return → report，模拟不同进程和跨时段交接。

[演练证据](validation/manual-rehearsal.json)：run `run_efba085db770453e`，两个不同 Sandbox 实例、两份工单、两次反馈；第一个 Sandbox 释放后，第二个实例读取已有实验历史并提出新方案。每份结果重复交付一次，账本和计数不变。最后独立重评分通过。

全部反馈由 simulator 生成并明确标为 rehearsal/sim；`physical_samples=0`。这验证人工工作流与恢复协议，不构成真实湿实验结果。

## 安装位置与复用

- 本机项目：`/Users/zhanggan/PycharmProjects/ai-scientists-last-exam`。
- 服务器项目：`/home/ubuntu/ai-scientists-last-exam`（SSH alias `tencent`）。
- 服务器模拟器资产：`/home/ubuntu/.local/share/aisle/assets/lightgbm_lab_model.joblib`。
- 服务器模型环境文件：`/home/ubuntu/.config/aisle/models.env`；Sandbox 配置：同目录 `sandbox.json`，权限均为 0600，均不在仓库中。
- 本机正式工程记录：`.aisle/live-proxy/`；服务器人工通道演练：`.aisle/manual-rehearsal/`；含 token 的账本不进入 Git。
- 当前采用单控制主机的 SQLite 和文件证据存储；支持 CLI 操作和可选 scoped HTTP gateway。备份、多主机调度和硬件 batch adapter 属于后续工程工作。

## 科学资格和实现范围

| 范围 | 当前状态 |
|---|---|
| 任务双环境格式、执行与评分协议 | 已实现并验证 |
| 两种自建 harness、Tencent、模型转发、持久人工工单 | 已实现并验证 |
| Simulator 独立 holdout 科学验收 | pending，需领域误差阈值、真实验证数据及独立评审 |
| 真实实验室 SOP/QC/参考实验就绪验收 | pending，需合作实验室签署材料与真实证据 |
| 正式 Top-K 湿实验及重复统计 | 未执行；当前案例保持 draft/pending |
| 第三方原生完整 harness、非空 Skills、多实验室与硬件批量调度 | 后续扩展，不宣称已支持 |

审批字段由受信任的任务仓库和人工审查流程维护；当前 CLI 验证字段和运行门槛，不提供专家身份或电子签名认证。代码合并、工程测试和科学验收是不同结论。
