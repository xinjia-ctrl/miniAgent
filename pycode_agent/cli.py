from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from pycode_agent.config import ModelSettings, default_config
from pycode_agent.engine import QueryEngine
from pycode_agent.events import ASSISTANT_DELTA, DONE, ERROR, TOOL_ERROR, TOOL_RESULT
from pycode_agent.repl import run_repl_sync
from pycode_agent.storage import SessionStorage

app = typer.Typer(add_completion=False, invoke_without_command=True)


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    print_text: Optional[str] = typer.Option(None, "--print", help="非交互执行一次请求。"),
    continue_session: bool = typer.Option(False, "--continue", help="继续最近一次会话。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
    permission_mode: str = typer.Option("default", "--permission-mode", help="权限模式。"),
    model: str = typer.Option("fake", "--model", help="模型名称。fake 表示使用 FakeModelClient。"),
    provider: str = typer.Option("fake", "--provider", help="模型 provider：fake 或 openai-compatible。"),
    base_url: str = typer.Option(
        "https://api.openai.com/v1/chat/completions",
        "--base-url",
        help="OpenAI-compatible chat completions URL。",
    ),
    debug: bool = typer.Option(False, "--debug", help="输出调试信息。"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    config = default_config(
        cwd=cwd,
        model=ModelSettings(provider=provider, model=model, base_url=base_url),
        permission_mode=permission_mode,
        non_interactive=print_text is not None,
        debug=debug,
    )
    storage = SessionStorage(config.resolved_data_dir)
    session = storage.load_latest() if continue_session else None
    engine = QueryEngine(config=config, storage=storage, session=session)
    if print_text is not None:
        asyncio.run(_run_print(engine, print_text))
        return
    run_repl_sync(engine)


@app.command()
def doctor(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
    model: str = typer.Option("fake", "--model", help="模型名称。"),
    provider: str = typer.Option("fake", "--provider", help="模型 provider。"),
) -> None:
    config = default_config(cwd=cwd, model=ModelSettings(provider=provider, model=model))
    typer.echo(f"cwd: {config.cwd}")
    typer.echo(f"data_dir: {config.resolved_data_dir}")
    typer.echo(f"audit_path: {config.audit_path}")
    typer.echo(f"provider: {config.model.provider}")
    typer.echo(f"model: {config.model.model}")


async def _run_print(engine: QueryEngine, prompt: str) -> None:
    async for event in engine.submit(prompt):
        if event.type == ASSISTANT_DELTA:
            typer.echo(event.data.get("text", ""), nl=False)
        elif event.type == TOOL_RESULT:
            typer.echo(f"\n[tool ok]\n{event.data['result']['display']}")
        elif event.type == TOOL_ERROR:
            typer.echo(f"\n[tool error]\n{event.data['result']['display']}")
        elif event.type == ERROR:
            typer.echo(f"\n[error] {event.data.get('message')}")
        elif event.type == DONE:
            typer.echo("")


def main() -> None:
    app()
