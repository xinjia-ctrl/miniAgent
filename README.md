# miniAgent

`miniAgent` 是一个从零实现的命令行 coding agent 学习项目。它复刻的是 Claude Code 类 coding agent 的核心架构思想：模型负责提出行动，runtime 负责上下文、工具执行、权限、安全、会话、审计和评测。

当前版本：`0.1.0`。本地最终版状态见 [最终交付状态](docs/final_status.md)。

## 功能特性

- CLI：支持 `miniagent --help`、`miniagent --print "问题"`、`miniagent doctor`
- REPL：直接运行 `miniagent` 可以进入多轮交互
- Agent loop：`QueryEngine` 统一处理用户输入、模型输出、工具调用和工具结果回灌
- Harness：默认使用 `FakeModelClient`，测试不依赖真实模型
- 模型适配：支持最小 OpenAI-compatible chat completions 适配器
- 工具协议：`BaseTool`、`ToolContext`、`ToolResult`、`ToolRegistry`
- 内置工具：`read_file`、`glob`、`grep`、`repo_map`、`symbol_search`、`code_index`、`write_file`、`edit_file`、`shell`、`todo`、`memory`、`plan`
- 权限模式：`default`、`accept_edits`、`plan`、`bypass`
- 文件安全：路径边界检查、敏感文件拒绝、读后写保护、mtime/size 漂移检测、diff 预览
- Shell 安全：危险命令拦截、超时、stdout/stderr 捕获、输出截断
- 上下文工程：系统提示、工作区状态、Git 状态、工具 schema、todo、记忆和历史裁剪
- 代码理解：基于 AST/轻量文本扫描生成 repo map、symbol search 和结构化代码索引
- 会话恢复：保存 messages、tool calls、tool results、permission decisions、todos、file reads
- 记忆：支持 `remember`、`forget_memory`、`recall_memory`
- 审计：记录请求、模型响应、工具调用、权限决策、工具结果、错误和会话保存，并可生成 session 复盘报告
- 评测：36 个 deterministic benchmark，支持 JSON/Markdown 报告和 baseline compare
- Demo：提供可重放真实项目案例，展示读项目、修 bug、跑测试和生成报告的完整 session

## 技术栈

- Python `>=3.11`
- Pydantic v2
- Typer
- pytest / pytest-asyncio
- Ruff

## 安装与启动

```powershell
python -m pip install -e ".[dev]"
miniagent --help
miniagent --print "你好"
python -m miniagent --print "读取 README.md 并总结"
```

## 配置说明

默认模型是 `fake`，不需要 API key。

使用 OpenAI-compatible 接口时：

```powershell
$env:OPENAI_API_KEY="你的密钥"
miniagent --provider openai-compatible --model gpt-4.1-mini --print "读取 README.md 并总结"
```

可选环境变量：

- `MINIAGENT_PROVIDER`：默认 provider
- `MINIAGENT_MODEL`：默认模型名
- `OPENAI_BASE_URL`：OpenAI-compatible chat completions URL
- `OPENAI_API_KEY`：API key

运行数据默认写入工作区内 `.miniagent/`，包括会话和审计日志。该目录已加入 `.gitignore`。

## 常用命令

```powershell
pytest
ruff check . --no-cache
pytest tests/test_engine.py
miniagent doctor
miniagent audit show <session_id>
python .\evals\runner.py --fake
.\scripts\smoke.ps1
.\scripts\make_demo.ps1
```

## 项目结构

```text
miniagent/
  cli.py            # 命令行入口
  repl.py           # 交互循环
  engine.py         # ReAct 主循环和事件流
  model.py          # FakeModel 与 OpenAI-compatible 适配器
  messages.py       # 结构化消息
  events.py         # EngineEvent
  context.py        # 上下文构建
  code_index.py     # 结构化代码索引和符号检索
  permissions.py    # 权限决策
  tool_base.py      # 工具协议和注册表
  tool_runner.py    # 工具执行编排
  storage.py        # 会话保存与恢复
  memory.py         # 持久记忆
  audit.py          # 审计日志
  audit_report.py   # 审计报告与 session 可观测性汇总
  tools/            # 内置工具
  utils/            # 路径、文本、diff、subprocess、JSONL 等辅助
tests/              # 单元和主循环测试
evals/              # 可复现评测雏形
demos/              # 可重放真实项目 Demo
docs/               # 架构、评测、发布和简历叙事文档
scripts/smoke.ps1   # 冒烟脚本
```

## 使用说明

非交互执行一次请求：

```powershell
miniagent --print "读取 README.md 并总结"
```

继续最近会话：

```powershell
miniagent --continue --print "继续刚才的任务"
```

查看诊断信息：

```powershell
miniagent doctor
```

## 开发说明

项目核心原则：

```text
模型只能提议行动，runtime 才能决定是否行动。
```

因此模型输出的工具调用必须经过 `ToolRunner` 和 `PermissionManager`，工具结果再以 `tool_result` 消息回灌给模型。测试优先使用 `FakeModelClient`，确保 agent loop 是确定性的。

更多文档：

- [架构说明](docs/architecture.md)
- [评测方法](docs/eval_methodology.md)
- [简历叙事](docs/resume_story.md)
- [发布检查清单](docs/release_checklist.md)
- [最终交付状态](docs/final_status.md)
- [Release Notes](docs/release_notes.md)

## 测试说明

```powershell
pytest
ruff check . --no-cache
```

当前测试覆盖消息序列化、FakeModel、工具注册、ToolRunner、文件读取、glob/grep、代码索引、写入/编辑保护、shell 安全、权限模式、上下文、存储、记忆、审计、engine loop 和 CLI。

## 评测说明

```powershell
miniagent evals run --model fake
miniagent evals report
miniagent evals compare baseline current
```

旧入口仍可用：

```powershell
python .\evals\runner.py --fake
```

评测用例位于 `evals/cases/`，当前包含 36 个可复现 benchmark。每个用例可以声明：

- `id` / `description` / `tags`：用例元信息
- `prompt`：用户任务
- `permission_mode`：权限模式
- `fake_script`：FakeModel 的固定响应和工具调用
- `workspace_files`：隔离评测工作区初始文件
- `expected_files`：期望文件内容、存在性和禁止内容
- `max_tool_calls` / `max_errors`：过程约束
- `forbidden_tools` / `safety.must_not_touch`：安全约束

报告默认写入 `.miniagent/evals/latest.json` 和 `.miniagent/evals/latest.md`。

## 常见问题

### 为什么默认不用真实模型？

真实模型输出不稳定，第一轮重点是把 runtime 写清楚、测稳定。真实模型适配器已经提供，但回归测试仍依赖 `FakeModelClient`。

### 为什么写文件前必须读取？

这是为了避免覆盖用户改动。`read_file` 会记录文件的 `mtime_ns` 和 `size`，`write_file` / `edit_file` 会在写入前检查文件是否漂移。

### 为什么 shell 在 default 模式下经常被拒绝？

Shell 是最高风险工具。非交互 `--print` 下需要确认的命令会直接拒绝；可以用 `bypass` 做本地实验，但不建议默认使用。

## 许可证

本项目使用 [MIT License](LICENSE)。
