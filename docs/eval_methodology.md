# 评测方法

`miniAgent` 的评测目标是验证 runtime 行为，而不是比较模型智能。所有 benchmark 默认使用 `FakeModelClient`，因此结果可复现、可回归、适合 CI。

## 评测入口

```powershell
miniagent evals run --model fake
miniagent evals report
miniagent evals compare baseline current
```

兼容旧入口：

```powershell
python .\evals\runner.py --fake
```

## 用例格式

评测用例位于 `evals/cases/*.json`。一个用例通常包含：

| 字段 | 作用 |
|---|---|
| `id` | 稳定用例 ID |
| `description` | 用例说明 |
| `tags` | 分类，例如 safety、context、memory |
| `prompt` | 用户任务 |
| `permission_mode` | 运行权限模式 |
| `fake_script` | 确定性模型脚本 |
| `workspace_files` | 初始隔离工作区文件 |
| `expected_files` | 期望文件内容、存在性或禁止内容 |
| `max_tool_calls` | 工具调用上限 |
| `max_errors` | 可接受错误数 |
| `forbidden_tools` | 不允许调用的工具 |
| `safety.must_not_touch` | 禁止触碰的路径 |

## 当前覆盖面

当前 benchmark 覆盖：

- 文件读取、offset/limit 和二进制拒绝。
- glob/grep 搜索。
- 写入、编辑、读后写保护和 diff。
- shell 测试命令、危险命令拦截。
- 权限模式 default、plan、accept_edits、bypass。
- todo 和 plan 工具。
- 记忆写入、召回和 session memory candidate。
- 上下文预算和 compact。
- 审计完整性。
- 工具失败恢复和未知工具处理。

## 报告

每次运行会写入：

- `.miniagent/evals/latest.json`
- `.miniagent/evals/latest.md`
- `.miniagent/evals/runs/<run_id>.json`
- `.miniagent/evals/runs/<run_id>.md`

Markdown 报告适合人工阅读，JSON 报告适合 CI 或 baseline compare。

## Baseline Compare

`miniagent evals compare baseline current` 会比较两个 run 的 pass/fail 和指标差异。推荐在重要重构前保存 baseline：

```powershell
miniagent evals run --model fake --name before-refactor
miniagent evals run --model fake --name after-refactor
miniagent evals compare before-refactor after-refactor
```

## CI 策略

CI 运行：

```powershell
python -m pip install -e ".[dev]"
ruff check . --no-cache
pytest
python -m miniagent doctor
```

这样同时验证安装、静态检查、完整测试和 CLI 基础诊断。

## 评测设计取舍

- 使用 deterministic fake model，牺牲模型自然性，换取稳定回归。
- 每个用例使用隔离工作区，避免互相污染。
- 用例断言 runtime 结果，包括文件内容、安全边界、工具调用数量和错误数。
- 对真实模型效果的评估不放在 CI 中，避免网络、密钥和随机性影响基础质量门禁。
