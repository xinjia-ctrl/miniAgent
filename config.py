"""配置：从 local_config.py 读取敏感信息（不上传 GitHub）"""
try:
    from local_config import DEEPSEEK_API_KEY
except ImportError:
    raise RuntimeError("缺少 local_config.py，请复制 local_config.example.py 并填入 API key")
