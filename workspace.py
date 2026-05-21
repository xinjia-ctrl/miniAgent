"""工作区管理：工作区切换、配置加载、信息查询"""

import json
from pathlib import Path

# 工作区根目录（首次导入时确定）
ROOT = Path.cwd().resolve()

# 工作区配置文件
CONFIG_FILE = ROOT / ".workspace.json"

# 默认配置模板
DEFAULT_CONFIG = {
    "name": ROOT.name,
    "root": str(ROOT),
    "description": "",
    "ignore_patterns": [".git", "__pycache__", ".venv", "venv", "node_modules"],
}


def init(name=None, description=""):
    """初始化当前目录为工作区，生成 .workspace.json"""
    if CONFIG_FILE.exists():
        return load_config()
    config = dict(DEFAULT_CONFIG)
    if name:
        config["name"] = name
    if description:
        config["description"] = description
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return config


def load_config():
    """加载工作区配置"""
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **data}
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(**kwargs):
    """更新工作区配置"""
    config = load_config()
    config.update(kwargs)
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return config


def tree(directory=None, max_depth=2, prefix=""):
    """生成目录树文本（打印用）"""
    directory = Path(directory or ROOT)
    if not directory.is_dir():
        return f"(不是目录: {directory})"

    config = load_config()
    ignores = config.get("ignore_patterns", [])

    lines = []
    items = sorted(
        p for p in directory.iterdir()
        if p.name not in ignores
    )

    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        line = prefix + connector + item.name
        if item.is_dir():
            line += "/"
        lines.append(line)

        if item.is_dir() and max_depth > 0:
            extension = "    " if is_last else "│   "
            sub = tree(item, max_depth - 1, prefix + extension)
            if sub:
                lines.append(sub)

    return "\n".join(lines)


def info():
    """返回工作区信息摘要"""
    config = load_config()
    root = Path(config["root"])
    py_files = list(root.rglob("*.py"))
    total_lines = 0
    for f in py_files:
        try:
            total_lines += len(f.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            continue

    return {
        "name": config["name"],
        "root": config["root"],
        "description": config["description"],
        "python_files": len(py_files),
        "total_lines": total_lines,
        "config_exists": CONFIG_FILE.exists(),
    }


def ensure_root():
    """确保 ROOT 存在，供外部导入"""
    global ROOT
    if not ROOT.exists():
        ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT
