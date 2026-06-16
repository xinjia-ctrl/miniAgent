from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from miniagent.app import MiniAgentApplication
from miniagent.bootstrap import build_agent_config
from miniagent.engine import QueryEngine
from miniagent.events import ASSISTANT_DELTA, DONE, ERROR, TOOL_ERROR, TOOL_RESULT
from miniagent.repl import run_repl_sync

app = typer.Typer(add_completion=False, invoke_without_command=True)
context_app = typer.Typer(help="查看上下文预算和 compact 状态。")
app.add_typer(context_app, name="context")


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    print_text: Optional[str] = typer.Option(None, "--print", help="非交互执行一次请求。"),
    continue_session: bool = typer.Option(False, "--continue", help="继续最近一次会话。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
    permission_mode: str = typer.Option("default", "--permission-mode", help="权限模式。"),
    model: str = typer.Option("fake", "--model", help="模型名称。fake 表示使用 FakeModelClient。"),
    provider: str = typer.Option(
        "fake",
        "--provider",
        help="模型 provider：fake、openai-compatible 或 anthropic-compatible。",
    ),
    base_url: str = typer.Option(
        "https://api.openai.com/v1/chat/completions",
        "--base-url",
        help="OpenAI-compatible chat completions URL。",
    ),
    debug: bool = typer.Option(False, "--debug", help="输出调试信息。"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    config = build_agent_config(
        cwd=cwd,
        provider=provider,
        model=model,
        base_url=base_url,
        permission_mode=permission_mode,
        non_interactive=print_text is not None,
        debug=debug,
    )
    application = MiniAgentApplication.from_config(config)
    engine = application.create_engine(continue_session=continue_session)
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
    config = build_agent_config(cwd=cwd, provider=provider, model=model)
    application = MiniAgentApplication.from_config(config)
    for key, value in application.diagnostics().items():
        typer.echo(f"{key}: {value}")


@context_app.command("inspect")
def inspect_context(
    last: bool = typer.Option(False, "--last", help="查看最近一次会话的上下文状态。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    if not last:
        typer.echo("请使用 --last 查看最近一次会话的上下文状态。")
        raise typer.Exit(code=1)
    config = build_agent_config(cwd=cwd)
    application = MiniAgentApplication.from_config(config)
    snapshot = application.inspect_latest_context()
    if snapshot is None:
        typer.echo("没有找到最近会话。")
        raise typer.Exit(code=1)

    typer.echo(f"session_id: {snapshot['session_id']}")
    last_context = snapshot.get("last_context")
    if isinstance(last_context, dict):
        typer.echo(f"selected_message_count: {last_context.get('selected_message_count', 0)}")
        typer.echo(f"total_message_count: {last_context.get('total_message_count', 0)}")
        typer.echo(f"compacted_message_count: {last_context.get('compacted_message_count', 0)}")
        typer.echo(f"budget: {last_context.get('budget', {})}")
        typer.echo(f"usage: {last_context.get('usage', {})}")

    summary = snapshot.get("compact_summary")
    if isinstance(summary, dict) and summary.get("text"):
        typer.echo("compact_summary:")
        typer.echo(summary["text"])
    elif isinstance(summary, str) and summary:
        typer.echo("compact_summary:")
        typer.echo(summary)
    else:
        typer.echo("compact_summary: <empty>")


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
