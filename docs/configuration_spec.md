# Spec：miniAgent 持久化模型配置

## Objective

让用户只配置一次模型信息，之后在任意项目目录直接执行 `miniagent` 即可启动真实模型。

配置分为三层，优先级从高到低：

1. 命令行显式参数。
2. 当前项目 `.miniagent/config.json`。
3. 用户全局 `~/.miniagent/config.json`。
4. 环境变量。
5. 程序默认值。

API Key 不写入配置文件，继续通过配置项指定的环境变量名称读取。

## Tech Stack

- Python 3.11+
- Pydantic v2：配置校验
- Typer：配置管理命令
- JSON：用户和项目配置文件

## Commands

配置 DeepSeek：

```powershell
miniagent config set `
  --provider openai-compatible `
  --model deepseek-v4-flash `
  --base-url https://api.deepseek.com/chat/completions `
  --api-key-env OPENAI_API_KEY `
  --permission-mode accept_edits
```

查看生效配置：

```powershell
miniagent config show
```

删除用户级配置：

```powershell
miniagent config reset
```

在任意项目中启动：

```powershell
cd D:\ragent
miniagent
```

质量检查：

```powershell
python -m ruff check . --no-cache
python -m pytest
```

## Project Structure

```text
miniagent/config.py          配置模型、文件路径、合并优先级和 JSON 读写
miniagent/bootstrap.py       根据最终配置装配运行时
miniagent/cli.py             config set/show/reset 命令和可选运行参数
tests/test_config.py         配置文件和优先级测试
tests/test_cli.py            配置命令及无参数启动测试
README.md                    用户配置说明
```

## Code Style

配置加载函数保持纯函数式输入输出，路径允许测试注入：

```python
def load_file_settings(path: Path) -> FileSettings | None:
    if not path.exists():
        return None
    return FileSettings.model_validate_json(path.read_text(encoding="utf-8"))
```

- 使用清晰的 `user_config_path`、`project_config_path` 命名。
- 所有 JSON 文件使用 UTF-8 和格式化输出。
- 配置错误给出文件路径和可操作的中文错误信息。

## Testing Strategy

- 单元测试验证全局、项目、环境变量和命令行的优先级。
- CLI 测试验证 `config set/show/reset`。
- 验证配置文件中不会保存 API Key 值。
- 保留现有 FakeModel 测试，通过显式传入 `--model fake` 避免用户机器配置影响测试。
- 运行完整 pytest、Ruff、doctor 和 Demo。

## Boundaries

- Always：配置文件写入用户目录或当前项目 `.miniagent/`；读取后使用 Pydantic 校验。
- Ask first：改变 API Key 存储方式、引入系统凭据管理器、增加新依赖。
- Never：把 API Key 明文写进 JSON、源码、日志或 Git 仓库。

## Success Criteria

- 设置一次用户配置后，在任意目录执行 `miniagent doctor` 能显示 DeepSeek provider、model 和 base URL。
- 在任意目录执行 `miniagent` 不再默认回退到 FakeModel。
- 命令行参数可以临时覆盖持久化配置。
- 项目配置可以覆盖用户配置，但不会影响其他项目。
- 没有配置时保持现有 FakeModel 默认行为。
- 全部测试和 Ruff 检查通过。

## Open Questions

- 当前版本使用 JSON，不接入 Windows Credential Manager。
- 当前版本不保存 API Key，只保存环境变量名，例如 `OPENAI_API_KEY`。
