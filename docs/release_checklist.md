# 发布检查清单

这个项目当前定位是学习型 runtime。发布前按下面步骤检查，避免把动态产物、缓存或本地配置带入仓库。

## 本地质量门禁

```powershell
python -m pip install -e ".[dev]"
ruff check . --no-cache
pytest
python -m miniagent doctor
.\scripts\make_demo.ps1
```

## 提交前检查

```powershell
git status --short
git diff --check
```

确认：

- 没有 `.miniagent/`、`demos/generated/`、`test_workspaces/` 等动态产物。
- 暂存区只包含当前发布相关文件。
- README 和 docs 中的命令与实际 CLI 一致。
- `pyproject.toml` 中版本号符合发布计划。

## GitHub Actions

CI 位于 `.github/workflows/ci.yml`，会执行：

1. 安装 `.[dev]`。
2. `ruff check . --no-cache`。
3. `pytest`。
4. `python -m miniagent doctor`。
5. `python scripts/make_demo.py --output-dir demos/generated/ci_demo`。

## 打 tag

确认 CI 通过后再打 tag：

```powershell
git tag v0.1.0
git push origin v0.1.0
```

如果暂时不发布远程 release，也可以只保留本地 tag 作为阶段里程碑。

## Release Note 模板

```markdown
## miniAgent v0.1.0

### Highlights

- ReAct agent loop with deterministic fake model harness.
- Tool runtime with permissions, sandbox checks, file checkpoints and rollback.
- Context budget, compact summary, memory recall, event storage and audit report.
- Plugin/MCP-style extension, eval benchmark suite and real-project demo.

### Verification

- ruff check . --no-cache
- pytest
- python -m miniagent doctor
- .\scripts\make_demo.ps1
```
