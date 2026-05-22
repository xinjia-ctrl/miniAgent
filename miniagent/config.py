"""配置管理：默认值、用户配置文件、环境变量和 CLI 参数合并。"""

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".miniagent"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_BACKEND = {
    "provider": "openai",
    "model": "deepseek-v4-flash",
    "api_key": None,
    "base_url": "https://api.deepseek.com",
}

BACKEND_ALIASES = {
    "deepseek": {
        "provider": "openai",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "provider": "openai",
        "model": "gpt-4.1",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "ollama": {
        "provider": "ollama",
        "model": "llama3.2",
        "base_url": "http://localhost:11434",
    },
}


def _load_local_config():
    """兼容旧版 local_config.py"""
    result = {}
    try:
        from local_config import DEEPSEEK_API_KEY
        if DEEPSEEK_API_KEY:
            result["deepseek_api_key"] = DEEPSEEK_API_KEY
    except ImportError:
        pass

    try:
        from local_config import ANTHROPIC_API_KEY
        if ANTHROPIC_API_KEY:
            result["anthropic_api_key"] = ANTHROPIC_API_KEY
    except ImportError:
        pass

    return result


def load_user_config():
    """读取用户级配置文件"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_user_config(config):
    """保存用户级配置文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_config_value(key, default=None):
    return load_user_config().get(key, default)


def set_config_value(key, value):
    config = load_user_config()
    config[key] = value
    save_user_config(config)


def unset_config_value(key):
    config = load_user_config()
    existed = key in config
    config.pop(key, None)
    save_user_config(config)
    return existed


def config_path():
    return CONFIG_FILE


def _apply_alias(config):
    alias = config.get("backend") or config.get("provider")
    if alias not in BACKEND_ALIASES:
        return config

    merged = dict(BACKEND_ALIASES[alias])
    merged.update({k: v for k, v in config.items() if v is not None})
    if "backend" in merged:
        merged.pop("backend", None)
    return merged


def build_backend_config(overrides=None):
    """按 默认值 < 用户配置 < 环境变量 < CLI 参数 生成后端配置"""
    config = dict(DEFAULT_BACKEND)
    user_config = load_user_config()
    config.update({k: v for k, v in user_config.items() if v is not None})
    config = _apply_alias(config)

    local = _load_local_config()
    env_name = config.get("api_key_env")
    env_key = os.getenv(env_name) if env_name else None

    if config.get("provider") == "anthropic":
        api_key = (
            os.getenv("ANTHROPIC_API_KEY")
            or local.get("anthropic_api_key")
            or config.get("api_key")
        )
    else:
        api_key = (
            env_key
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or local.get("deepseek_api_key")
            or config.get("api_key")
        )
    config["api_key"] = api_key

    if overrides:
        config.update({k: v for k, v in overrides.items() if v is not None})

    config.pop("api_key_env", None)
    config.pop("backend", None)
    return config


BACKEND = build_backend_config()
