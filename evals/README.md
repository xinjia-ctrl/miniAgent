# evals

这里放第一轮可复现评测雏形。当前 runner 默认使用 `FakeModelClient`，目标是验证 agent runtime 的流程、安全边界和工具调用统计，而不是评估真实模型质量。

运行：

```powershell
python .\evals\runner.py --fake
```
