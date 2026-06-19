# 最终交付状态

`miniAgent` 当前达到 `AGENT_FINAL_PORTFOLIO_PLAN.md` 中阶段 17-30 的本地最终版要求。

## 已完成能力

| 能力 | 状态 | 入口文件 |
|---|---|---|
| 应用容器和模块边界 | 完成 | `miniagent/app.py`, `miniagent/bootstrap.py` |
| 模型路由和 Provider Adapter | 完成 | `miniagent/model_router.py`, `miniagent/model_adapters.py` |
| 上下文预算和 compact | 完成 | `miniagent/context.py`, `miniagent/context_budget.py` |
| 事件溯源存储 | 完成 | `miniagent/storage.py`, `miniagent/event_log.py` |
| 权限沙箱 | 完成 | `miniagent/permissions.py`, `miniagent/security/` |
| 文件快照和回滚 | 完成 | `miniagent/changes.py` |
| 长期记忆 | 完成 | `miniagent/memory.py`, `miniagent/tools/memory.py` |
| 插件和简化 MCP | 完成 | `miniagent/plugin_loader.py`, `miniagent/mcp_client.py` |
| 评测系统 | 完成 | `evals/runner.py`, `evals/cases/` |
| 审计和可观测性 | 完成 | `miniagent/audit.py`, `miniagent/audit_report.py` |
| 高级代码理解工具 | 完成 | `miniagent/code_index.py`, `miniagent/tools/code_understanding.py` |
| 真实项目 Demo | 完成 | `scripts/make_demo.py`, `demos/real_project_demo/` |
| 文档、CI、发布准备 | 完成 | `docs/`, `.github/workflows/ci.yml`, `LICENSE` |

## 最终验收命令

```powershell
python -m pip install -e ".[dev]"
python -m ruff check . --no-cache
python -m pytest
python -m miniagent doctor
.\scripts\make_demo.ps1
```

## 运行数据位置

默认运行数据写入当前工作区：

```text
.miniagent/
```

常见子目录：

```text
.miniagent/sessions/
.miniagent/events/
.miniagent/changes/
.miniagent/evals/
.miniagent/plugins/
.miniagent/memory.json
.miniagent/audit.jsonl
```

Demo 生成产物写入：

```text
demos/generated/
```

这些运行产物均已加入 `.gitignore`。

## 发布状态

- 当前包版本：`0.1.0`
- 许可证：MIT
- 推荐本地 tag：`v0.1.0`
- CI：Windows + Python 3.11/3.13

正式发布到 GitHub 前，建议先推送当前分支并确认 GitHub Actions 通过。
