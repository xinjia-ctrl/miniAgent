# Release Notes

## v0.1.0

这是 `miniAgent` 的第一个完整本地最终版。

### Highlights

- ReAct agent loop：支持模型消息、工具调用、工具结果回灌和 max turns。
- Tool runtime：统一 `BaseTool` / `ToolRegistry` / `ToolRunner` 协议。
- Safety sandbox：路径边界、敏感文件、危险 shell、权限模式和读后写保护。
- File checkpoints：文件变更记录、diff、checkpoint 和 rollback。
- Context engineering：上下文预算、历史裁剪、compact summary、代码符号上下文。
- Memory system：user/project/session 三层记忆、时间衰减和可解释召回。
- Storage：session snapshot、JSONL event log、SQLite session index。
- Observability：audit log、session summary、失败原因统计和 timeline。
- Code understanding：repo map、symbol search、结构化代码索引。
- Plugins：本地 Python 插件和简化 MCP stdio 工具。
- Evals：36 个 deterministic benchmark、Markdown/JSON 报告和 baseline compare。
- Demo：真实小项目端到端演示，包含读项目、修 bug、跑测试和生成报告。
- Delivery：README、docs、MIT LICENSE、GitHub Actions CI 和发布清单。

### Verification

```powershell
python -m ruff check . --no-cache
python -m pytest
python -m miniagent doctor
.\scripts\make_demo.ps1
```

### Notes

该版本默认使用 `FakeModelClient`，适合教学、演示和 runtime 回归测试。真实模型可通过 OpenAI-compatible 或 Anthropic-compatible provider 接入。
