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

当前默认从 `local_config.py` 读取 API Key。后续建议迁移到环境变量和用户级配置文件。
