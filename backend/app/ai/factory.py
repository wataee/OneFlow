import logging
from app.ai.demo_provider import DemoAIProvider
from app.ai.llm_provider import LLMProvider
from app.ai.provider import AIProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_ai_provider() -> AIProvider:
    """
    Factory function to retrieve the configured AI provider.
    No service or API code needs modification when switching providers.
    """
    if settings.DEMO_MODE or settings.AI_PROVIDER == "demo" or not settings.OPENAI_API_KEY:
        if not settings.DEMO_MODE and not settings.OPENAI_API_KEY:
            logger.warning(
                "OPENAI_API_KEY is not set while AI_PROVIDER is configured for LLM. "
                "Automatically falling back to DemoAIProvider."
            )
        return DemoAIProvider()

    return LLMProvider()
