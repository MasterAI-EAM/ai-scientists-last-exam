# 文档与验证证据

任务专属说明随 [tasks/<task_id>/](../tasks/README.md) 保存；本目录保存跨任务说明及脱敏工程证据。

| 记录 | 内容 |
|---|---|
| [environment-live.json](validation/environment-live.json) | 实际模型服务与 Docker 隔离检查 |
| [harbor-local.json](validation/harbor-local.json) | Oracle、nop、故障注入及并发回归 |
| [tencent-live.json](validation/tencent-live.json) | 腾讯云 Qwen Code 完整闭环及早期调试记录 |
| [package-checks.json](validation/package-checks.json) | 代码检查、测试结果及对应源码哈希 |
| [tasks-layout.json](validation/tasks-layout.json) | 迁移到 `tasks/` 后的测试、Docker oracle 与历史摘要兼容检查 |

原始云端日志和凭据位于不提交的 `private/`，普通 Harbor 产物位于不提交的 `jobs/`。
工程记录不等同于 sim 科学验收或真实湿实验结果。

## 目录迁移与历史记录

任务从仓库根目录 `color_001/` 迁移至 `tasks/color_001/`，任务 ID 仍为 `color_001`。
已有报告中的旧路径、源码哈希、任务 checksum 和运行时间保留原样，它们描述当时的运行快照；不能通过替换路径或哈希把历史运行改写成新版本实测。

查阅旧报告时，将 `color_001/<文件>` 映射到当前的 `tasks/color_001/<文件>` 定位，并结合报告哈希核对内容。后续实际运行使用新路径生成新证据；仅移动目录不代表重新执行了云端模型。
