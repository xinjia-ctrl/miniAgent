import json
from openai import OpenAI
from config import DEEPSEEK_API_KEY
from tools import read_file, list_files, run_shell

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 工具定义（DeepSeek function calling 格式）
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
            "description": "执行 shell 命令（危险操作）",
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

# 函数名 -> 实际函数的映射
FUNC_MAP = {
    "read_file": read_file,
    "list_files": list_files,
    "run_shell": run_shell,
}


def chat():
    messages = [
        {"role": "system", "content": "你是一个智能 AI 助手，可以调用工具来操作电脑。请用中文回答问题。"}
    ]
    print("DeepSeek Agent 已启动（输入 exit 退出）\n")

    while True:
        try:
            user_input = input("你: ")
            if user_input.lower() in ("exit", "quit"):
                print("再见！")
                break
            if not user_input.strip():
                continue

            messages.append({"role": "user", "content": user_input})

            # 请求 AI 回复（允许调用工具）
            response = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=messages,
                tools=TOOLS,
                stream=False
            )

            msg = response.choices[0].message

            # 如果 AI 想调用工具
            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    func_name = tc.function.name
                    func_args = json.loads(tc.function.arguments)
                    print(f"  -> 调用工具: {func_name}({json.dumps(func_args, ensure_ascii=False)})")

                    func = FUNC_MAP.get(func_name)
                    if func:
                        result = func(**func_args)
                    else:
                        result = f"未知工具: {func_name}"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })

                # 把工具结果发给 AI，拿最终回复
                final = client.chat.completions.create(
                    model="deepseek-v4-flash",
                    messages=messages,
                    stream=True
                )
                print("AI: ", end="", flush=True)
                full_reply = ""
                for chunk in final:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        print(content, end="", flush=True)
                        full_reply += content
                print("\n")
                messages.append({"role": "assistant", "content": full_reply})
            else:
                # 直接文本回复
                print("AI: ", end="", flush=True)
                full_reply = msg.content or ""
                print(full_reply)
                print()
                messages.append({"role": "assistant", "content": full_reply})

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"\n错误: {e}\n")


if __name__ == "__main__":
    chat()
