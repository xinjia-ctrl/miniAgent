"""ReAct 智能体主循环

模式: Thought → Action → Observation → Thought → ... → Final Answer
"""

import json
from openai import OpenAI
from config import DEEPSEEK_API_KEY
from tools import read_file, list_files, run_shell

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容（按行号范围）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "start": {"type": "integer", "description": "起始行号", "default": 1},
                    "end": {"type": "integer", "description": "结束行号", "default": 200},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出目录内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径", "default": "."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "执行 shell 命令",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "integer", "description": "超时秒数", "default": 20},
                },
                "required": ["command"],
            },
        },
    },
]

FUNC_MAP = {
    "read_file": read_file,
    "list_files": list_files,
    "run_shell": run_shell,
}

SYSTEM_PROMPT = """你是一个可以操作电脑的 AI 智能体。你有以下能力：
- read_file: 读取文件
- list_files: 列出目录
- run_shell: 执行 shell 命令

请按 ReAct 模式工作：
1. 思考当前任务需要做什么（Thought）
2. 调用合适的工具（Action）
3. 观察工具返回的结果（Observation）
4. 重复直到任务完成，然后给出最终答案

注意：你可以连续多次调用工具，不需要一次只调一个。"""


def run(max_steps=20):
    print("=" * 50)
    print("ReAct Agent 启动")
    print("输入任务后，AI 会自动循环思考→行动→观察直到完成")
    print("=" * 50)

    task = input("\n任务: ").strip()
    if not task:
        return

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    step = 0
    while step < max_steps:
        step += 1
        print(f"\n--- Step {step} ---")

        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            tools=TOOLS,
            stream=False,
        )

        msg = response.choices[0].message

        # 没有工具调用 → 认为任务完成
        if not msg.tool_calls:
            print(f"\n[最终回答]\n{msg.content}")
            return

        # 处理工具调用
        messages.append(msg)
        for tc in msg.tool_calls:
            func_name = tc.function.name
            func_args = json.loads(tc.function.arguments)
            print(f"  → {func_name}({json.dumps(func_args, ensure_ascii=False)})")

            func = FUNC_MAP.get(func_name)
            result = func(**func_args) if func else f"未知工具: {func_name}"
            print(f"    结果: {result[:200]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

    print(f"\n达到最大步骤数 ({max_steps})，强制停止")


if __name__ == "__main__":
    run()
