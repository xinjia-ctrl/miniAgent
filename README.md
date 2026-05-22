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
