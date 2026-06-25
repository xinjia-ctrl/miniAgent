from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

import typer

from evals.runner import (
    DEFAULT_CASES_DIR,
    DEFAULT_OUTPUT_DIR,
    compare_runs,
    format_summary_text,
    read_report,
    render_compare_markdown,
    run_eval_suite,
)
from miniagent.audit_report import render_audit_report
from miniagent.app import MiniAgentApplication
from miniagent.bootstrap import build_agent_config
from miniagent.config import (
    PersistedSettings,
    delete_persisted_settings,
    load_persisted_settings,
    project_config_path,
    save_persisted_settings,
    user_config_path,
)
from miniagent.engine import QueryEngine
from miniagent.events import ASSISTANT_DELTA, DONE, ERROR, TOOL_ERROR, TOOL_RESULT
from miniagent.memory import MemoryItem, MemoryRecallHit, MemoryScope, normalize_scope
from miniagent.repl import run_repl_sync

app = typer.Typer(add_completion=False, invoke_without_command=True)
context_app = typer.Typer(help="查看上下文预算和 compact 状态。")
sessions_app = typer.Typer(help="查看和导出会话。")
changes_app = typer.Typer(help="查看和回滚文件变更。")
memory_app = typer.Typer(help="管理长期记忆。")
tools_app = typer.Typer(help="查看已注册工具。")
plugins_app = typer.Typer(help="管理本地插件。")
evals_app = typer.Typer(help="运行和查看评测。")
audit_app = typer.Typer(help="查看审计报告。")
config_app = typer.Typer(help="管理持久化模型配置。")
app.add_typer(context_app, name="context")
app.add_typer(sessions_app, name="sessions")
app.add_typer(changes_app, name="changes")
app.add_typer(memory_app, name="memory")
app.add_typer(tools_app, name="tools")
app.add_typer(plugins_app, name="plugins")
app.add_typer(evals_app, name="evals")
app.add_typer(audit_app, name="audit")
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    print_text: Optional[str] = typer.Option(None, "--print", help="非交互执行一次请求。"),
    continue_session: bool = typer.Option(False, "--continue", help="继续最近一次会话。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
    permission_mode: Optional[str] = typer.Option(None, "--permission-mode", help="权限模式。"),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="模型名称；省略时读取项目或用户配置。",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="模型 provider：fake、openai-compatible 或 anthropic-compatible。",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="完整模型接口 URL；省略时读取项目或用户配置。",
    ),
    api_key_env: Optional[str] = typer.Option(
        None,
        "--api-key-env",
        help="保存 API Key 的环境变量名。",
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
        api_key_env=api_key_env,
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
    model: Optional[str] = typer.Option(None, "--model", help="模型名称。"),
    provider: Optional[str] = typer.Option(None, "--provider", help="模型 provider。"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="完整模型接口 URL。"),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="API Key 环境变量名。"),
) -> None:
    config = build_agent_config(
        cwd=cwd,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    application = MiniAgentApplication.from_config(config)
    for key, value in application.diagnostics().items():
        typer.echo(f"{key}: {value}")


@config_app.command("set")
def set_config(
    provider: str = typer.Option(..., "--provider", help="模型 provider。"),
    model: str = typer.Option(..., "--model", help="模型名称。"),
    base_url: str = typer.Option(..., "--base-url", help="完整模型接口 URL。"),
    api_key_env: str = typer.Option(
        "OPENAI_API_KEY",
        "--api-key-env",
        help="保存 API Key 的环境变量名，不会保存密钥值。",
    ),
    permission_mode: str = typer.Option(
        "accept_edits",
        "--permission-mode",
        help="默认权限模式。",
    ),
    project: bool = typer.Option(False, "--project", help="保存为当前项目配置。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="项目目录。"),
) -> None:
    target = project_config_path(cwd) if project else user_config_path()
    existing = load_persisted_settings(target) or PersistedSettings()
    settings = PersistedSettings.model_validate(
        {
            **existing.model_dump(exclude_none=True),
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "permission_mode": permission_mode,
        }
    )
    save_persisted_settings(target, settings)
    scope = "项目" if project else "用户"
    typer.echo(f"已保存{scope}配置：{target}")
    typer.echo(f"API Key 请设置在环境变量：{api_key_env}")


@config_app.command("show")
def show_config(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="项目目录。"),
) -> None:
    config = build_agent_config(cwd=cwd)
    key_name = config.model.api_key_env
    typer.echo(f"provider: {config.model.provider}")
    typer.echo(f"model: {config.model.model}")
    typer.echo(f"base_url: {config.model.base_url}")
    typer.echo(f"api_key_env: {key_name}")
    typer.echo(f"api_key_configured: {str(bool(os.environ.get(key_name))).lower()}")
    typer.echo(f"permission_mode: {config.permission_mode}")
    typer.echo(f"user_config: {user_config_path()}")
    typer.echo(f"project_config: {project_config_path(cwd)}")


@config_app.command("reset")
def reset_config(
    project: bool = typer.Option(False, "--project", help="删除当前项目配置。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="项目目录。"),
) -> None:
    target = project_config_path(cwd) if project else user_config_path()
    scope = "项目" if project else "用户"
    if delete_persisted_settings(target):
        typer.echo(f"已删除{scope}配置：{target}")
        return
    typer.echo(f"{scope}配置不存在：{target}")


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


@sessions_app.command("list")
def list_sessions(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    config = build_agent_config(cwd=cwd)
    application = MiniAgentApplication.from_config(config)
    sessions = application.list_sessions()
    if not sessions:
        typer.echo("没有找到会话。")
        return
    for session in sessions:
        typer.echo(
            f"{session.id}\tmessages={session.message_count}\t"
            f"updated_at={session.updated_at:.3f}\tcwd={session.cwd}"
        )


@sessions_app.command("export")
def export_session(
    session_id: Optional[str] = typer.Argument(None, help="会话 ID；省略时配合 --last 导出最近会话。"),
    last: bool = typer.Option(False, "--last", help="导出最近一次会话。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    if session_id is None and not last:
        typer.echo("请提供 session_id，或使用 --last。")
        raise typer.Exit(code=1)
    config = build_agent_config(cwd=cwd)
    application = MiniAgentApplication.from_config(config)
    exported = application.export_session(None if last else session_id)
    if exported is None:
        typer.echo("没有找到会话。")
        raise typer.Exit(code=1)
    typer.echo(json.dumps(exported, ensure_ascii=False, indent=2))


@changes_app.command("show")
def show_changes(
    change_id: Optional[str] = typer.Argument(None, help="变更 ID；省略时列出最近变更。"),
    limit: int = typer.Option(20, "--limit", min=1, max=100, help="列出最近变更数量。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    config = build_agent_config(cwd=cwd)
    application = MiniAgentApplication.from_config(config)
    try:
        typer.echo(application.describe_changes(change_id, limit=limit))
    except KeyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)


@changes_app.command("revert")
def revert_change(
    change_id: str = typer.Argument(..., help="要回滚的变更 ID。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    config = build_agent_config(cwd=cwd)
    application = MiniAgentApplication.from_config(config)
    try:
        result = application.revert_change(change_id)
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
    typer.echo(result.message)


@memory_app.command("list")
def list_memories(
    query: str = typer.Option("", "--query", "-q", help="按关键词搜索记忆。"),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="记忆层级：user、project、session 或 all。",
    ),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="按标签过滤，可重复。"),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="最多显示数量。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    parsed_scope = _parse_memory_scope(scope)
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    if query or tag:
        hits = application.search_memories(
            query,
            scope=parsed_scope,
            limit=limit,
            tags=tag or [],
        )
        if not hits:
            typer.echo("没有找到记忆。")
            return
        for hit in hits:
            typer.echo(_format_memory_hit(hit))
        return

    memories = application.list_memories(scope=parsed_scope)[:limit]
    if not memories:
        typer.echo("没有找到记忆。")
        return
    for item in memories:
        typer.echo(_format_memory_item(item))


@memory_app.command("search")
def search_memories(
    query: str = typer.Argument(..., help="搜索关键词。"),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="记忆层级：user、project、session 或 all。",
    ),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="按标签过滤，可重复。"),
    limit: int = typer.Option(20, "--limit", min=1, max=100, help="最多显示数量。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    parsed_scope = _parse_memory_scope(scope)
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    hits = application.search_memories(query, scope=parsed_scope, limit=limit, tags=tag or [])
    if not hits:
        typer.echo("没有找到记忆。")
        return
    for hit in hits:
        typer.echo(_format_memory_hit(hit))


@memory_app.command("remember")
def remember_memory(
    content: str = typer.Argument(..., help="要保存的记忆内容。"),
    scope: str = typer.Option("project", "--scope", help="记忆层级：user、project 或 session。"),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="标签，可重复。"),
    importance: float = typer.Option(1, "--importance", min=1, max=10, help="重要性 1-10。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    parsed_scope = _parse_memory_scope(scope)
    if parsed_scope is None:
        typer.echo("新增记忆时 scope 不能为 all。")
        raise typer.Exit(code=1)
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    item = application.remember_memory(
        content,
        tags=tag or [],
        importance=importance,
        scope=parsed_scope,
    )
    typer.echo(f"已记住：{item.id}")


@memory_app.command("update")
def update_memory(
    memory_id: str = typer.Argument(..., help="记忆 ID。"),
    content: Optional[str] = typer.Option(None, "--content", help="新的记忆内容。"),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="新的记忆层级：user、project 或 session。",
    ),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="新的标签列表，可重复。"),
    importance: Optional[float] = typer.Option(
        None,
        "--importance",
        min=1,
        max=10,
        help="新的重要性。",
    ),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    parsed_scope = _parse_memory_scope(scope)
    if scope is not None and parsed_scope is None:
        typer.echo("更新记忆时 scope 不能为 all。")
        raise typer.Exit(code=1)
    if content is None and tag is None and importance is None and scope is None:
        typer.echo("没有提供要更新的字段。")
        raise typer.Exit(code=1)

    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    item = application.update_memory(
        memory_id,
        content=content,
        tags=tag,
        importance=importance,
        scope=parsed_scope,
    )
    if item is None:
        typer.echo("没有找到记忆。")
        raise typer.Exit(code=1)
    typer.echo(f"已更新：{item.id}")


@memory_app.command("delete")
def delete_memory(
    memory_id: str = typer.Argument(..., help="记忆 ID。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    if not application.delete_memory(memory_id):
        typer.echo("没有找到记忆。")
        raise typer.Exit(code=1)
    typer.echo("已删除")


@tools_app.command("list")
def list_tools(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    for tool in application.list_tools():
        plugin = f"\tplugin={tool['plugin']}" if tool.get("plugin") else ""
        typer.echo(
            f"{tool['name']}\tsource={tool['source']}\tkind={tool['kind']}{plugin}\t"
            f"{tool['description']}"
        )


@tools_app.command("inspect")
def inspect_tool(
    name: str = typer.Argument(..., help="工具名称。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    try:
        typer.echo(json.dumps(application.inspect_tool(name), ensure_ascii=False, indent=2))
    except KeyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc


@plugins_app.command("list")
def list_plugins(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    plugins = application.list_plugins()
    if not plugins:
        typer.echo("没有找到插件。")
        return
    for plugin in plugins:
        state = "loaded" if plugin.loaded else "error"
        tools = ",".join(plugin.tools) if plugin.tools else "-"
        line = f"{plugin.name}\t{state}\tversion={plugin.version}\ttools={tools}\tpath={plugin.path}"
        if plugin.error:
            line += f"\terror={plugin.error}"
        typer.echo(line)


@plugins_app.command("install")
def install_plugin(
    source: Path = typer.Argument(..., help="插件目录，必须包含 plugin.json。"),
    force: bool = typer.Option(False, "--force", help="覆盖已安装的同名插件。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
) -> None:
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    try:
        status = application.install_plugin(source, force=force)
    except (FileExistsError, ValueError, OSError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"已安装插件：{status.name}")


@evals_app.command("run")
def run_evals(
    model: str = typer.Option("fake", "--model", help="评测模型，目前支持 fake。"),
    case: Optional[str] = typer.Option(None, "--case", help="只运行指定 case id。"),
    name: Optional[str] = typer.Option(None, "--name", help="指定 run id，便于 baseline compare。"),
    cases_dir: Path = typer.Option(DEFAULT_CASES_DIR, "--cases-dir", help="评测用例目录。"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir", help="报告输出目录。"),
) -> None:
    try:
        run = asyncio.run(
            run_eval_suite(
                model=model,
                case_id=case,
                cases_dir=cases_dir,
                output_dir=output_dir,
                run_id=name,
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(format_summary_text(run))
    typer.echo(f"report: {output_dir / 'latest.md'}")


@evals_app.command("report")
def report_evals(
    run: str = typer.Option("latest", "--run", help="run id、报告路径或 latest。"),
    format: str = typer.Option("markdown", "--format", help="输出格式：markdown 或 json。"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir", help="报告输出目录。"),
) -> None:
    if format not in {"markdown", "json"}:
        typer.echo("format 必须是 markdown 或 json。")
        raise typer.Exit(code=1)
    try:
        typer.echo(read_report(run, output_dir=output_dir, format=format))
    except FileNotFoundError as exc:
        typer.echo(f"没有找到评测报告：{exc.filename}")
        raise typer.Exit(code=1) from exc


@evals_app.command("compare")
def compare_evals(
    baseline: str = typer.Argument(..., help="baseline run id、JSON 路径或 latest。"),
    current: str = typer.Argument(..., help="current run id、JSON 路径或 latest。"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir", help="报告输出目录。"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON。"),
) -> None:
    try:
        result = compare_runs(baseline, current, output_dir=output_dir)
    except FileNotFoundError as exc:
        typer.echo(f"没有找到评测结果：{exc.filename}")
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        typer.echo(render_compare_markdown(result))


@audit_app.command("show")
def show_audit(
    session_id: str = typer.Argument(..., help="会话 ID。"),
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="工作区目录。"),
    timeline_limit: int = typer.Option(
        80,
        "--timeline-limit",
        min=0,
        max=500,
        help="时间线条数。",
    ),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON。"),
) -> None:
    application = MiniAgentApplication.from_config(build_agent_config(cwd=cwd))
    try:
        report = application.audit_report(session_id, timeline_limit=timeline_limit)
    except FileNotFoundError as exc:
        typer.echo(f"没有找到会话或审计数据：{exc.filename}")
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        typer.echo(render_audit_report(report))


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


def _parse_memory_scope(scope: str | None) -> MemoryScope | None:
    try:
        return normalize_scope(scope)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc


def _format_memory_item(item: MemoryItem) -> str:
    tags = ",".join(item.tags) if item.tags else "-"
    return (
        f"{item.id}\tscope={item.scope}\timportance={item.importance:g}\t"
        f"tags={tags}\tupdated_at={item.updated_at:.3f}\t{item.content}"
    )


def _format_memory_hit(hit: MemoryRecallHit) -> str:
    return f"{_format_memory_item(hit.item)}\tscore={hit.score:.2f}\treason={hit.reason}"
