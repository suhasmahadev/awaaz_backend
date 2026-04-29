import logging
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from pydantic import Field

logger = logging.getLogger(__name__)


class FallbackGemini(BaseLlm):
    """Gemini model wrapper that retries transient capacity errors on backups."""

    fallback_models: list[str] = Field(default_factory=list)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        model_names = [self.model, *self.fallback_models]
        last_error: Exception | None = None

        for index, model_name in enumerate(model_names):
            request = llm_request.model_copy(deep=True)
            request.model = model_name
            yielded = False

            try:
                async for response in Gemini(model=model_name).generate_content_async(
                    request, stream=stream
                ):
                    yielded = True
                    yield response
                return
            except Exception as exc:
                if yielded or not _is_retryable_capacity_error(exc):
                    raise

                last_error = exc
                if index < len(model_names) - 1:
                    logger.warning(
                        "Gemini model %s failed with a transient capacity error; "
                        "falling back to %s.",
                        model_name,
                        model_names[index + 1],
                    )

        if last_error:
            raise last_error


def _is_retryable_capacity_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code in (429, 500, 502, 503, 504):
        return True

    text = str(exc).lower()
    return any(
        signal in text
        for signal in (
            "high demand",
            "server error",
            "service unavailable",
            "unavailable",
            "resource exhausted",
        )
    )
