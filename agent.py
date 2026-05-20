import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "sk-2a1248ad8a664821a2bd7d050de50bf1"),
    base_url="https://api.deepseek.com"
)


def chat():
    messages = [
        {"role": "system", "content": "你是一个智能 AI 助手，请用中文回答问题。"}
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

            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                stream=True
            )

            print("AI: ", end="", flush=True)
            full_reply = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    print(content, end="", flush=True)
                    full_reply += content
            print("\n")

            messages.append({"role": "assistant", "content": full_reply})

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"\n错误: {e}\n")


if __name__ == "__main__":
    chat()
