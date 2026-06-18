from __future__ import annotations

SYSTEM_PROMPT = """你是 miniAgent，一个用于学习 coding agent 架构的命令行助手。

核心安全边界：
- 模型只能提出工具调用请求，runtime 决定是否执行。
- 修改文件前要先读取文件，并尊重权限模式。
- 默认避免危险 shell 命令，优先使用只读工具理解项目。
- 工具结果可能被截断，必要时继续读取更小范围。
"""


def build_system_prompt(
    *,
    cwd: str,
    platform: str,
    permission_mode: str,
    git_status: str,
    todos: str = "",
    memories: str = "",
    code_context: str = "",
) -> str:
    parts = [
        SYSTEM_PROMPT.strip(),
        f"当前工作区：{cwd}",
        f"平台：{platform}",
        f"权限模式：{permission_mode}",
    ]
    if git_status:
        parts.append("Git 状态：\n" + git_status)
    if todos:
        parts.append("当前 Todo：\n" + todos)
    if memories:
        parts.append("相关记忆：\n" + memories)
    if code_context:
        parts.append("相关代码符号：\n" + code_context)
    return "\n\n".join(parts)
