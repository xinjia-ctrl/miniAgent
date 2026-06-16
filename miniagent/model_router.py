from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from miniagent.config import ModelSettings
from miniagent.model_adapters import (
    AnthropicCompatibleModelClient,
    FakeModelClient,
    OpenAICompatibleModelClient,
)
from miniagent.model_base import (
    ModelClient,
    ModelEvent,
    ModelProviderError,
    ModelRequest,
    ModelUsage,
    normalize_model_error,
)


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"

ProviderFactory = Callable[[ModelSettings], ModelClient]


class ModelRouter:
    """根据运行配置选择 provider，并统一处理重试、错误和 usage 事件。"""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        factories: dict[str, ProviderFactory] | None = None,
    ):
        self.settings = normalize_provider_settings(settings)
        self.factories = default_provider_factories() | (factories or {})
        self.client = self._create_client(self.settings)
        self.usage_events: list[ModelUsage] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        attempts = self.settings.max_retries + 1
        last_error: ModelProviderError | None = None
        for attempt in range(attempts):
            try:
                async for event in self.client.stream(request):
                    if event.type == "usage":
                        self.usage_events.append(ModelUsage.model_validate(event.data))
                    yield event
                return
            except Exception as exc:
                error = normalize_model_error(self.settings.provider, exc)
                last_error = error
                if not error.retryable or attempt >= attempts - 1:
                    raise error from exc
        if last_error:
            raise last_error

    def _create_client(self, settings: ModelSettings) -> ModelClient:
        factory = self.factories.get(settings.provider)
        if factory is None:
            raise ValueError(f"未知模型 provider：{settings.provider}")
        return factory(settings)


def default_provider_factories() -> dict[str, ProviderFactory]:
    return {
        "fake": lambda settings: FakeModelClient(),
        "openai-compatible": OpenAICompatibleModelClient,
        "anthropic-compatible": AnthropicCompatibleModelClient,
    }


def normalize_provider_settings(settings: ModelSettings) -> ModelSettings:
    updates: dict[str, object] = {}
    if settings.provider == "anthropic-compatible":
        if settings.base_url == OPENAI_CHAT_COMPLETIONS_URL:
            updates["base_url"] = ANTHROPIC_MESSAGES_URL
        if settings.api_key_env == "OPENAI_API_KEY":
            updates["api_key_env"] = "ANTHROPIC_API_KEY"
    return settings.model_copy(update=updates) if updates else settings


def create_model_router(settings: ModelSettings) -> ModelRouter:
    return ModelRouter(settings)


def create_model_client(settings: ModelSettings) -> ModelClient:
    settings = normalize_provider_settings(settings)
    factory = default_provider_factories().get(settings.provider)
    if factory is None:
        raise ValueError(f"未知模型 provider：{settings.provider}")
    return factory(settings)
