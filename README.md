# miniAgent

miniAgent 是一个面向代码仓库的轻量本地 CLI 代码助手。它支持会话续接、工具调用、文件编辑、diff 审批、审计日志、slash 命令和多模型后端。

## 安装

建议在虚拟环境中安装：

```powershell
pip install -e .
```

安装后可以直接运行：

```powershell
mini
```

也可以继续使用兼容入口：

```powershell
python main.py
```

## 常用命令

```powershell
mini --help
mini -c
mini sessions
mini resume <session_id>
mini --model deepseek-v4-flash
```

进入会话后，输入 `/` 可以查看 slash 命令列表。

## 权限模式

miniAgent 支持工具权限分级：

```text
read-only
workspace-write
shell-write
network
git-write
destructive
```

会话中可以用 slash 命令切换策略：

```text
/permission
/permission ask
/permission auto-read
/permission trusted
```

默认是 `auto-read`：只读工具自动执行，写文件、shell、网络和 Git 写操作会询问确认。

## 工具能力

内置工具包括：

```text
read_file
read_many_files
list_files
find_files
search_text
write_file
replace_in_file
apply_patch
git_status
git_diff
web_fetch
run_shell
remember
forget_memory
delegate
```

当模型一次请求多个只读或网络读取类工具时，miniAgent 会并行执行安全工具调用，例如多个 `read_file`、`git_diff`、`web_fetch`。涉及写文件、shell、审批和回滚的操作仍会串行执行。

`delegate` 会启动一个只读子 agent 处理调查型子任务。子 agent 只能读取、搜索、查看 Git 只读信息和抓取网页，不能写文件或执行 shell。

Runtime 会跳过同一轮中的重复工具调用，并自动截断超长工具结果，避免模型陷入重复动作或上下文被单次输出挤满。

测试与质量底座包括：

- `FakeModelClient`：不调用真实 API 的确定性模型客户端。
- 结构化记忆召回：结合 tag、关键词、重要性和时效衰减排序。
- 工作区漂移检测：通过 SHA-256 指纹判断项目文档、指令和 Git 状态是否变化。
- 上下文压缩指标：可对裁剪前后字符数和消息数量做实验记录。
- 基准测试框架：`python scripts/run_benchmarks.py` 可运行确定性 Runtime 回归场景，覆盖安全、上下文压缩、记忆召回、工作区漂移等维度。
- 安全脱敏：审计日志、run trace 和工具结果会自动隐藏环境变量中的 key/token/secret。
- Shell 环境白名单：子进程只继承必要系统变量，避免把敏感配置透传给命令。
- Shell 权限细化：命令会被分为只读、工作区写入、网络、Git 写入和破坏性操作。
- Shell 执行收敛：`run_shell` 只执行单条简单命令，不支持管道、重定向、命令串联或嵌套 shell；需要读写文件时优先使用专用工具。

## 运行时结构

核心控制循环已经从 CLI 中拆出：

```text
miniagent/runtime.py    AgentRuntime，负责模型调用、工具调度、权限门禁和会话写入
miniagent/run_store.py  RunStore，记录每次请求的 trace、状态和摘要
miniagent/cli.py        终端交互、slash 命令和参数解析
tests/test_runtime.py   FakeModelClient 驱动的 Runtime 测试
```

每次直接工具执行或模型工具循环都会写入：

```text
.mini/runs/<run_id>/trace.jsonl
.mini/runs/<run_id>/task_status.json
.mini/runs/<run_id>/report.json
```

## 配置

配置优先级为：

```text
默认值 < 用户级配置 < 环境变量 < CLI 参数
```

用户级配置文件位于：

```powershell
mini config path
```

常用配置命令：

```powershell
mini config set backend deepseek
mini config set model deepseek-v4-flash
mini config set api_key sk-xxx
mini config list
```

也可以使用环境变量：

```powershell
$env:DEEPSEEK_API_KEY="sk-xxx"
mini
```

旧版 `local_config.py` 仍然兼容，但不再推荐作为长期配置方式。
如确实需要旧版文件配置，可以参考 `local_config.example.py`；不要把真实密钥提交到仓库。

## 开发与测试

安装开发依赖：

```powershell
pip install -e ".[dev]"
```

运行测试：

```powershell
pytest
```

运行静态检查：

```powershell
ruff check .
```
