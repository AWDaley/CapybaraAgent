from abc import ABC, abstractmethod
from collections.abc import Callable
import inspect


class LLMError(Exception):
    """Base exception for LLM errors."""

class LLMConnectionError(LLMError):
    """Raised when the LLM provider is unreachable."""

class LLMAPIError(LLMError):
    """Raised when the LLM API returns an error."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

class LLMClient(ABC):
    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.api_key = api_key

    @abstractmethod
    def generate(self, messages: list[dict[str, str]], json_mode: bool = False, timeout_seconds: float | None = None, response_schema: dict | None = None) -> str:
        """
        Send messages to the LLM, returning its raw text response.
        """
        
    def generate_with_retry(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        max_retries: int = 3,
        callback: Callable | None = None,
        deadline=None,
        response_schema: dict | None = None,
    ) -> str:
        """Wraps generate() with exponential backoff retry logic."""
        import time
        for attempt in range(max_retries):
            try:
                timeout_seconds = deadline.require_remaining("LLM request") if deadline else None
                params = inspect.signature(self.generate).parameters
                kwargs = {"json_mode": json_mode}
                if "timeout_seconds" in params:
                    kwargs["timeout_seconds"] = timeout_seconds
                if response_schema is not None and "response_schema" in params:
                    kwargs["response_schema"] = response_schema
                return self.generate(messages, **kwargs)
            except (LLMError, TimeoutError, OSError, ConnectionError) as e:
                if attempt == max_retries - 1:
                    raise  # Give up after final attempt
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                if deadline:
                    if deadline.remaining_seconds <= wait_time:
                        raise TimeoutError("Pipeline deadline exhausted before LLM retry.")
                if callback:
                    callback(f"LLM error: {e}. Retrying in {wait_time}s (Attempt {attempt+1}/{max_retries})...")
                else:
                    print(f"⚠️ LLM Error: {e}. Retrying in {wait_time}s (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)

    @staticmethod
    @abstractmethod
    def list_models() -> list[str]:
        """
        Return a list of available models.
        """


def get_provider_class(provider_name: str) -> type[LLMClient]:
    provider_name = provider_name.lower().strip()
    if provider_name == "ollama":
        from providers.ollama_provider import OllamaProvider
        return OllamaProvider
    elif provider_name == "openai":
        from providers.openai_provider import OpenAIProvider
        return OpenAIProvider
    elif provider_name == "gemini":
        from providers.gemini_provider import GeminiProvider
        return GeminiProvider
    else:
        raise ValueError(f"Unknown provider: {provider_name}")


def list_available_models(provider_name: str) -> list[str]:
    """Helper to get available models for a given provider without instantiating."""
    provider_cls = get_provider_class(provider_name)
    return provider_cls.list_models()


def create_llm_client(provider_name: str, model: str, api_key: str | None = None) -> LLMClient:
    """Factory function to create an LLM client."""
    provider_cls = get_provider_class(provider_name)
    return provider_cls(model=model, api_key=api_key)
