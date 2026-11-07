# Wetlab：湿实验暂停与恢复

`wetlab` 在 Harbor 0.25.0 外增加一个本地 Docker 控制器。Agent 提交实验后，框架保存容器文件、挂载数据和原生会话，移除任务容器，在容器外等待结果；结果到达后重建环境，沿用原会话继续下一轮。

支持范围是持久化文件和原生上下文。运行中的进程、GPU 内存、未落盘的训练状态和网络连接不在快照范围内；后台训练需要先保存可重启的检查点。当前执行后端为本地 Docker。

## 0. 选择执行模式

同一个 `wait_for_result` 工具通过任务的 `[wetlab].execution_mode` 或启动参数 `--execution-mode` 切换。CLI 参数优先；默认 `suspend`，旧 run 的行为不变。

| 模式 | 工具返回 | 等待期间 | 继续方式 |
| --- | --- | --- | --- |
| `suspend` | 受理回执 | 签名归档并移除容器 | 重建容器、恢复原生会话、注入结果消息 |
| `blocking` | 实验结果 | 容器与 harness 会话保持运行，网关在容器外等待 | 同一个工具调用返回结果，Agent 在同一会话内继续 |

常驻模式配置例子（当前适配 **OpenClaw、Terminus-2**）：

```toml
[wetlab]
execution_mode = "blocking"
budget = 3
max_rounds = 3
active_budget_sec = 28800
wait_timeout_sec = 90000  # 单次外部等待上限，25 小时
blocking_agent_timeout_sec = 298860  # 活跃预算 + 3 * 等待上限 + 60 秒余量
```

也可在下面的启动命令后加 `--execution-mode blocking`，使用默认 25 小时等待上限。`blocking_agent_timeout_sec` 不能小于上述计算值，省略时自动计算；它同时写入 Harbor Agent 总超时和控制器监控时限。常驻模式的总时限包含等待；`round_timeout_sec` 和提交后的暂停宽限期不会提前终止等待。

网关由受信 worker 绑定完整 Docker 容器 ID，实验受理记录同时保存工单编号、容器身份和预算。容器内可以一次提交并等结果：

```bash
wait_for_result --expr "1+1" --request-id measurement-001
# 命令在外部网关等结果；返回后才继续分析。
wetlab finish --answer 2
```

也可以显式分两步，先确认受理，再用回执中的 `seq` 等待：

```bash
wetlab submit --expr "1+1" --request-id measurement-001
wait_for_result --ticket-id 1
```

`wetlab submit` 在两种模式下都只返回回执；`wetlab wait_for_result` 与独立命令相同。常驻模式下不要在提交后结束 turn，也不要后台执行工具或由模型轮询。框架会追加该模式的指令。

网关采用可重连的短周期 HTTP 长轮询；一个连接最长等待 20 秒，线程在网关内睡眠并接收回填通知，客户端只做传输重试。没有模型轮询，也不把 24 小时绑定在同一个 TCP 连接上。网关重启、断网或等待进程被杀后，用同一 `--ticket-id` 重新等待；不创建新工单、不再次扣费。`--wait-timeout` 仅结束本次客户端等待，不取消实验。重复结果与重复等待只记一次交付。

OpenClaw 配置延长原生会话和 exec 时限，并禁用 `process` 工具以强制 exec 同步返回；Terminus-2 在宿主机阻塞终端采样循环，覆盖其原生 60 秒采样窗口。其他 harness 的常驻模式在提交实验前拒绝，原有 `suspend` 适配继续可用。**配置为 ≥24h 不等于完成 ≥24h 实测**，44 个 harness 的状态见 [TIMEOUTS.md](TIMEOUTS.md)。

控制器被打断后，`continue` 可接管仍在运行的同一 worker，不轮换 token、不暂停或重建容器。若 harness 本身已经退出，框架保留容器与工单并标记可核对故障，不自动重启 harness；按实验编号重新等待只恢复工具等待，不承诺复活已退出的模型进程。完成任务后才按既有流程做最终归档、密封记录和独立离线评分。

## 1. 安装与凭据

在仓库根目录操作，需要 Python 3.12、运行中的 Docker，以及模型供应商凭据：

```bash
# 已有 .venv 时直接使用它。
uv venv --python 3.12
uv pip install --python .venv/bin/python -r wetlab/requirements-dev.txt
cp wetlab/.env.example wetlab/.env
chmod 600 wetlab/.env
```

在本机编辑 `wetlab/.env`：

- `WETLAB_ADMIN_TOKEN`：实验网关管理凭据。
- `WETLAB_SIGNING_KEY`：检查点和账本的签名密钥。
- `OPENAI_API_KEY`、`OPENAI_API_BASE`：示例使用的模型凭据与 OpenAI 兼容接口地址。
- `WETLAB_ARCHIVE_DIR`：可选的大容量磁盘目录。

管理凭据和签名密钥应分别使用独立随机值，可用 `secrets.token_hex(32)` 生成。网关与控制器必须加载同一份配置；一个 run 的签名密钥应保持不变。`.env`、`.wetlab.env` 和 `state/` 均不提交 Git。

以下两个终端都先加载配置：

```bash
set -a
. wetlab/.env
set +a
export HARBOR="$PWD/.venv/bin/harbor"
export HARBOR_PYTHON="$PWD/.venv/bin/python"
```

其他供应商可通过 `--model`、`--base-url`、`--api-key-name` 和 harness 参数配置；它们须支持该 harness 使用的协议。CLI 参数见 `wetlab_run.py start --help`。

## 2. 先运行模拟实验示例

终端 A 启动长期运行的网关：

```bash
.venv/bin/python wetlab/gateway.py \
  --port 18765 --db wetlab/state/gateway.db --lab-delay 10 15
```

默认实验端是算术模拟器；它会在 10–15 秒后返回结果。这个例子用于验证暂停与恢复流程，不代表真实湿实验。

终端 B 启动 agent（会实际调用模型供应商）：

```bash
.venv/bin/python wetlab/wetlab_run.py start wetlab/tasks/wetlab-add \
  --run-dir wetlab/state/example-001 \
  --agent openclaw --model openai/deepseek/deepseek-flash \
  --base-url "$OPENAI_API_BASE" --api-key-name OPENAI_API_KEY \
  --allow-agent-host tokenhub.tencentmaas.com \
  --gateway-url http://127.0.0.1:18765 \
  --gateway-url-container http://host.docker.internal:18765 \
  --setup-timeout 900 \
  --archive-dir "${WETLAB_ARCHIVE_DIR:-$PWD/wetlab/state/archives}"
```

此例使用腾讯 TokenHub；`openai/` 是 Harbor 的协议前缀，实际模型 ID 为 `deepseek/deepseek-flash`。更换服务地址时同步修改 `--allow-agent-host`。容器必须能访问 `--gateway-url-container`：Docker Desktop 可用 `host.docker.internal`；其他 Docker 环境需要配置可达的宿主机地址或 host-gateway 映射。

`example-001` 是一次运行的唯一目录。另开新实验使用新目录；恢复已有实验使用 `continue` 或 `retry`。检查点较大时，将 `WETLAB_ARCHIVE_DIR` 指向容量充足的磁盘。

## 3. Agent 如何提交与读取结果

容器内的规范工具是：

```bash
wait_for_result --expr "1+1" --reasoning "measurement" --request-id experiment-001
wetlab status
wetlab history
wetlab finish --answer 2
```

默认 `suspend` 模式下，`wait_for_result` 立即返回工单回执，并要求 agent 结束当前轮次。它不在容器中阻塞等待或循环轮询。接下来由框架：

1. 校验原生会话已到可恢复边界，冻结全部任务服务，保存文件系统、挂载数据和会话并签名。
2. 移除任务容器，在外部网关等待本批工单完成。提前返回的结果也会缓冲到检查点提交之后。
3. 校验检查点、交付结果、重建容器和原生会话，将实验结果作为下一条用户消息追加给模型。
4. 检查会话 ID、全部原有消息及新增事件，确认继续的是原任务。

结果消息包含工单编号、原表达式、完成状态、结果、错误（如有）及剩余额度。恢复后的 agent 也可通过 `wetlab history` 查询已交付结果；尚未交付的结果对 agent 隐藏。

`wetlab wait_for_result` 等价；`wetlab submit` 只返回受理回执，保留原有暂停模式的兼容行为。示例镜像安装两个命令入口；框架也会在旧镜像缺少新入口时补装 `wait_for_result`，保留原 `wetlab` 文件。

### 将自己的任务接入控制器

从 `wetlab/tasks/wetlab-add` 复制一个任务目录，保留 Harbor 的 `instruction.md`、`task.toml` 和 `environment/`，再修改指令、依赖与验证器。示例 Dockerfile 安装 `wetlab` 和 `wait_for_result`；自定义镜像也应安装两个入口，且容器内需要 Python 3。

在 `task.toml` 中配置：

```toml
[wetlab]
max_rounds = 3
budget = 3
round_timeout_sec = 900
active_budget_sec = 28800
suspend_grace_sec = 25
pending_policy_on_seal = "cancel"
```

`budget` 是实验提交上限，最多为 `max_rounds`；拿到最后一份结果后仍会给 agent 完成任务的轮次。`active_budget_sec` 限制累计活跃运行时间；实验等待阶段不计入。指令应要求 agent 先保存文件，再调用 `wait_for_result` 并结束本轮；最后用 `wetlab finish` 完成任务。启动后的任务目录不能修改，控制器会检查其校验和。

当前工单格式是演示用 `expr` 字符串和 `reasoning`，不是通用实验方案 schema。真实工作流可以由受信实验端解释约定的文本格式；增加结构化方案或附件，需要同步扩展客户端和网关，并保留幂等身份。

当前最终评分使用任务的 `tests/Dockerfile` 构建独立验证镜像，在无网络环境运行 `/tests/test.sh`；签名账本只读挂载到 `/ledger/ledger.json`，输出写入 `/logs/verifier/reward.txt`。示例验证器检查实验账本；若要对 agent 文件或模型评分，需要另外实现只读制品输入，不能直接照搬普通 Harbor verifier 的文件访问假设。

## 4. 接入人工或外部实验端

在启动一轮新的真实实验流程之前，网关使用 `--manual-lab` 禁用算术模拟器：

```bash
.venv/bin/python wetlab/gateway.py \
  --port 18765 --db wetlab/state/manual-gateway.db --manual-lab
```

实验端使用管理凭据查询和领取工单。下面假设编号为 1：

```bash
curl --fail-with-body -sS \
  -H "Authorization: Bearer $WETLAB_ADMIN_TOKEN" \
  http://127.0.0.1:18765/admin/pending

curl --fail-with-body -sS \
  -H "Authorization: Bearer $WETLAB_ADMIN_TOKEN" \
  --json '{"claim_id":"lab-worker-attempt-001"}' \
  http://127.0.0.1:18765/admin/tickets/1/claim
```

**只有领取响应的 `execute` 为 `true` 时才开工。** 将返回的 `execution_id` 作为外部仪器/LIMS 的幂等键。完成后回填：

```bash
curl --fail-with-body -sS \
  -H "Authorization: Bearer $WETLAB_ADMIN_TOKEN" \
  --json '{"result":"2"}' \
  http://127.0.0.1:18765/admin/tickets/1/complete
```

失败使用 `{"failed":true,"result":null,"error":"failure description"}`。当前结果载荷是文本，尚无原始实验文件的自动上传、下载或挂载；LIMS/UI 接入需要自行实现。网关的管理接口适用于本地或受信网络；部署层负责网络访问控制。

## 5. 重复通知与执行状态

- 同一操作跨轮重试时，复用 `--request-id` 和原参数。省略时，客户端每个 run/轮次使用一个默认身份；有意在后续轮次复现实验应使用新 ID。
- 客户端用文件锁串行处理并发调用，在 POST 前落盘并 fsync 请求记录。响应丢失时仍复用原键。
- 网关在一个事务内受理、扣实验额度并关闭提交；同键返回原工单，同键不同内容返回 409。
- 实验端领取时先持久化 `accepted -> running`，每张工单最多发一个执行许可。重复通知与竞争执行者得到 `execute: false`。
- 重复相同结果回填返回原结果；冲突结果被拒绝。重复交付不会重新开放一个已有待执行实验的轮次。
- 领取响应丢失或执行进程崩溃后，状态可能停在 `running`。查询 `/admin/running` 后人工核对，不自动重跑。

这是执行许可最多一次的协议；真实设备和人工操作者必须遵守领取结果与工单身份。框架无法去重绕过协议执行的物理工作。旧实验系统仍可直接回填结果，但接入执行流程应使用上述领取协议。

## 6. 中断、恢复与归档

```bash
.venv/bin/python wetlab/wetlab_run.py status wetlab/state/example-001
.venv/bin/python wetlab/wetlab_run.py continue wetlab/state/example-001
.venv/bin/python wetlab/wetlab_run.py retry wetlab/state/example-001
.venv/bin/python wetlab/wetlab_run.py abort wetlab/state/example-001
```

`continue` 恢复中断的控制器；`retry` 重试 `FAILED_RECOVERABLE` 阶段；`abort` 密封账本并按配置处理未完成工单。`status` 可与运行中的控制器配合使用；同一个运行目录只允许一个控制器写入。

签名检查点包含所有任务服务的不可变镜像、bind/volume/tmpfs 归档、原生会话和伴随文件、精确 harness 版本及 SHA-256。挂载恢复会核对内容、权限、所有权与链接；共享卷关系也会重建。tmpfs 使用仅加入目标 PID 命名空间的只读 helper 采集。

`--archive-dir` 将大归档放入指定位置的独立 run-ID 目录；运行状态、日志、账本仍在 `--run-dir`。两个位置和签名密钥都必须保留。删除本机镜像缓存后可从 `images.tar` 重新加载。最终一轮的文件和训练模型也保留在最终环境归档中。

快照写入跨进程串行化，并在归档磁盘或本地运行磁盘低于 3 GiB 保留空间时停止，等待释放空间后 `retry`。已知凭证出现在配置、会话、挂载或镜像压缩层时，框架拒绝提交快照。无签名的旧版 v1 检查点不自动升级。

设备/socket 挂载、复制扩容的 Compose 服务及非 Docker 后端不做近似恢复。`/wetlab-restore`、`/run/wetlab-internal` 为框架保留路径。

## 7. Harness 与验证范围

原生导入、原生文件系统恢复及协议桥接由 `sessions.py`、`advanced.py` 和各适配模块处理；安装在容器内的 harness 与恢复前版本必须一致。工作进程只做进程内集成，不修改已安装的 Harbor 源文件。

以下历史验证对应暂停模式。历史实际验证的 29 个 harness、模式限制及尚未完成的适配见 [VALIDATION.md](VALIDATION.md)。适配器已注册不等于完成真实验证。OpenClaw 的已测原生版本为 `2026.11.1 (4ffdd20)`。Gemini/Antigravity 使用协议桥仍调用指定 DeepSeek；ACP 选择 OpenCode ACP 后端；Strands、LangGraph 等项目型框架带有示例 factory。

## 8. 测试

```bash
# 无模型请求；默认跳过需要 Docker 的检查。
.venv/bin/python -m pytest wetlab/tests -q

# 包含实际 Docker、挂载恢复、硬崩溃恢复、CLI/HTTP 并发和重复通知测试。
WETLAB_DOCKER_TEST=1 .venv/bin/python -m pytest wetlab/tests -q
```

Docker 测试会从示例环境构建自己的基础镜像；不依赖某台机器预先存在的测试 tag。需要构建时访问依赖源；`WETLAB_TEST_IMAGE` 可显式指定已准备的兼容基础镜像。

需要真实模型的三轮实测须显式执行，会产生供应商请求；反馈仍为模拟实验：

```bash
.venv/bin/python wetlab/tests/run_live.py --env-file wetlab/.env \
  --harbor "$PWD/.venv/bin/harbor" --out wetlab/state/live-test-001 \
  --archive-dir "${WETLAB_ARCHIVE_DIR:-$PWD/wetlab/state/archives}" \
  --agents openclaw --workers 1 --setup-timeout 900 --active-budget 1800 --timeout 2400

.venv/bin/python wetlab/tests/verify_live.py \
  wetlab/state/live-test-001/openclaw/run --out wetlab/state/openclaw-verification.json
```

测试私有签名元数据保存在本机 `/tmp` 的 0600 文件中；独立核验需保留它。故障注入仅用于测试：`WETLAB_CRASH_AT=after_checkpoint_rename`、`before_deliver`、`after_deliver`，网关 `--fault-drop-submit-response N`。

常驻模式真实模型验证入口（需要供应商凭据；反馈由测试程序模拟）：

```bash
.venv/bin/python wetlab/tests/run_blocking_live.py \
  --env-file wetlab/.env --out wetlab/state/blocking-live-001 \
  --harbor "$PWD/.venv/bin/harbor" --archive-dir "$WETLAB_ARCHIVE_DIR" \
  --agents openclaw terminus-2 --wait-seconds 70
```

用 `--wait-seconds 86410` 才会进行超过 24 小时的实际等待，需要保持宿主机、Docker、网关和供电稳定；不要把短时通过记录改写为一天验证。运行目录包含逐次容器状态采样和 `verification.json`。供应商凭据不写入记录，签名私有元数据单独保存在本机 `/tmp`。
