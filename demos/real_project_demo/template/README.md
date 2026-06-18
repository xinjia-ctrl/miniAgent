# ShopCart Discount Demo

一个故意带有小 bug 的示例项目，用来展示 miniAgent 如何阅读项目、定位问题、修改代码并运行测试。

## 问题

`apply_discount(100, 20)` 应该返回 `80.0`，但当前实现把百分比数值当成金额直接相减。

## 验证

```powershell
python -m pytest tests/test_pricing.py
```
