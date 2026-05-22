"""配置：读取 API key 和后端配置"""

import os

try:
    from local_config import DEEPSEEK_API_KEY
except ImportError:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

try:
    from local_config import ANTHROPIC_API_KEY  # 可选
except ImportError:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ======== 后端选择 ========
# provider: openai / anthropic / ollama
# 切换后 main.py 无需任何改动
BACKEND = {
    "provider": "openai",
    "model": "deepseek-v4-flash",
    "api_key": DEEPSEEK_API_KEY,
    "base_url": "https://api.deepseek.com",
}

# Anthropic 备用配置（provider 切到 anthropic 时使用）
ANTHROPIC_CONFIG = {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "api_key": ANTHROPIC_API_KEY,
    "max_tokens": 4096,
}

# Ollama 备用配置（provider 切到 ollama 时使用）
OLLAMA_CONFIG = {
    "provider": "ollama",
    "model": "llama3.2",
    "base_url": "http://localhost:11434",
}
