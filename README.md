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
list_files
write_file
replace_in_file
apply_patch
git_status
git_diff
web_fetch
run_shell
remember
forget_memory
```

当模型一次请求多个只读或网络读取类工具时，miniAgent 会并行执行安全工具调用，例如多个 `read_file`、`git_diff`、`web_fetch`。涉及写文件、shell、审批和回滚的操作仍会串行执行。

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
