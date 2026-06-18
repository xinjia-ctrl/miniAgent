# 真实项目 Demo

这个目录保存阶段 29 的可展示案例：一个小型购物车折扣项目模板，以及可一键重放的 agent session 生成脚本。

运行方式：

```powershell
.\scripts\make_demo.ps1
```

脚本会把 `template/` 复制到 `demos/generated/real_project_demo/workspace/`，然后使用确定性的 `FakeModelClient` 驱动 miniAgent 完成一次真实工具链路：

1. 生成 repo map 理解项目结构。
2. 读取 README、源码和测试。
3. 修复折扣计算 bug。
4. 运行 `python -m pytest tests/test_pricing.py`。
5. 导出 session、audit report 和 demo 文档。

生成产物默认位于 `demos/generated/real_project_demo/`，该目录可重建，不进入 Git。
