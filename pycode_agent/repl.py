from __future__ import annotations

import asyncio

from pycode_agent.engine import QueryEngine
from pycode_agent.events import ASSISTANT_DELTA, ERROR, TOOL_ERROR, TOOL_RESULT


async def run_repl(engine: QueryEngine) -> None:
    print("pyagent REPL，输入 /exit 退出，/help 查看命令。")
    while True:
        try:
            prompt = input("pyagent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not prompt:
            continue
        if prompt in {"/exit", "/quit"}:
            return
        if prompt == "/help":
            print("/exit 退出，直接输入问题即可提交给 agent。")
            continue
        await print_events(engine, prompt)


async def print_events(engine: QueryEngine, prompt: str) -> None:
    async for event in engine.submit(prompt):
        if event.type == ASSISTANT_DELTA:
            print(event.data.get("text", ""), end="", flush=True)
        elif event.type == TOOL_RESULT:
            print(f"\n[tool ok]\n{event.data['result']['display']}")
        elif event.type == TOOL_ERROR:
            print(f"\n[tool error]\n{event.data['result']['display']}")
        elif event.type == ERROR:
            print(f"\n[error] {event.data.get('message')}")
    print()


def run_repl_sync(engine: QueryEngine) -> None:
    asyncio.run(run_repl(engine))
