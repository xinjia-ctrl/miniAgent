# evals

这里是 miniAgent 的 deterministic benchmark。默认使用 `FakeModelClient`，目标是可复现地验证 runtime 行为、安全边界、工具调用过程和上下文指标。

常用命令：

```powershell
miniagent evals run --model fake
miniagent evals run --model fake --case edit_file
miniagent evals report
miniagent evals compare baseline current
```

兼容旧入口：

```powershell
python .\evals\runner.py --fake
```

报告默认输出到 `.miniagent/evals/latest.json` 和 `.miniagent/evals/latest.md`，历史 run 保存在 `.miniagent/evals/runs/`。

当前 `evals/cases/` 包含 36 个 benchmark，覆盖读取、搜索、编辑、读后写保护、权限拒绝、危险 shell 拦截、上下文预算、记忆、todo/plan、工具失败恢复和审计完整性。
