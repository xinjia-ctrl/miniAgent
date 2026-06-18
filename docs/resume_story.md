# 简历叙事

这一页用于把 `miniAgent` 讲成一个完整工程项目，而不是“调用模型 API 的脚本”。

## 一句话项目介绍

从零实现了一个 Claude Code 风格的命令行 coding agent runtime，覆盖 ReAct 主循环、工具系统、权限沙箱、上下文预算、事件溯源、长期记忆、插件、评测、审计和可重放 Demo。

## 可以放在简历上的描述

- 独立设计并实现 coding agent runtime：模型只提出工具调用，runtime 负责权限、安全、执行和结果回灌。
- 实现 `read_file`、`grep`、`repo_map`、`edit_file`、`shell`、`memory`、`plan` 等工具，并通过统一 `ToolRegistry` 暴露 schema。
- 设计权限沙箱：路径边界检查、敏感文件拒绝、读后写保护、危险 shell 拦截、非交互默认拒绝。
- 实现高级上下文预算：按 system/project/tools/history/tool/protected 分区，并保证 tool_use/tool_result 原子性。
- 实现事件溯源存储和审计报告：session snapshot、JSONL event log、audit log、session summary 和失败原因统计。
- 实现三层长期记忆和可解释召回：user/project/session scope、重要性、时间衰减、标签过滤和 recall reason。
- 实现 deterministic eval harness：36 个 benchmark、JSON/Markdown 报告、baseline compare、CI 可复现。
- 实现插件系统和简化 MCP：插件可注册本地 Python 工具或 MCP 风格工具。
- 准备真实项目 Demo：agent 读取小项目、修复 bug、运行测试并生成 session/audit/report。

## 面试讲解主线

### 1. 为什么不是直接让模型执行命令

模型输出不可信，必须把“意图”和“执行”分开。因此 `QueryEngine` 只接收模型提出的工具调用，真正执行由 `ToolRunner` 完成，且每次执行前都经过 `PermissionManager` 和安全分类。

### 2. 如何保证工具调用可控

所有工具实现统一协议：

- `input_model` 用 Pydantic 校验参数。
- `is_read_only()` 告诉权限层和并发调度器工具风险。
- `ToolContext` 携带 cwd、session_id、权限模式、读缓存和 state。
- 工具结果统一包装为 `ToolResult`，再变成 `tool_result` 消息回灌。

### 3. 如何避免误改用户文件

`read_file` 完整读取文件时记录 `mtime_ns` 和 `size`。`write_file` / `edit_file` 覆盖前会检查文件是否在读取后漂移。每次文件变更都会记录 checkpoint，可通过 `changes show/revert` 查看和回滚。

### 4. 如何处理上下文变长

`ContextBuilder` 把上下文分成系统提示、项目状态、工具 schema、记忆、历史、工具结果和 protected 最近消息。历史裁剪时把 tool_use 和对应 tool_result 作为原子单元，避免模型看到半截工具调用。

### 5. 如何做可观测性

项目同时记录：

- session snapshot：便于恢复。
- storage events：便于重建和排查。
- audit log：便于复盘请求、工具、权限、错误和保存事件。

`miniagent audit show` 会聚合这些数据，输出 session summary、工具失败、权限拒绝、失败原因和 timeline。

## Demo 叙事

运行：

```powershell
.\scripts\make_demo.ps1
```

它会生成一个小型购物车折扣项目，驱动 agent 完成：

1. `repo_map` 理解项目结构。
2. `read_file` 读取 README、源码和测试。
3. `edit_file` 修复百分比折扣 bug。
4. `shell` 运行 `python -m pytest tests/test_pricing.py`。
5. 生成 session export、audit report 和 demo README。

这个 Demo 展示的是端到端 runtime 能力：不是只展示一次模型回答，而是展示 agent 如何在安全边界内操作真实项目。

## 可以继续扩展的方向

- 接入 tree-sitter，提高多语言符号索引准确度。
- 增加真实 provider 的录制回放机制，把真实模型 session 固化为 regression case。
- 加 Web UI 展示 session timeline、diff、audit report 和 memory recall。
- 把插件协议扩展为更完整的 MCP client。
