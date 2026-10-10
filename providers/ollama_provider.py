import json
import os
import urllib.error
import urllib.request

from llm_client import LLMClient, LLMConnectionError

OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# A local model request must be bounded independently from an entire pipeline.
# ``OLLAMA_TIMEOUT`` remains the explicit provider override.
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", os.environ.get("CAPYBARA_LLM_CALL_TIMEOUT", "600")))
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0"))

class OllamaProvider(LLMClient):
    def __init__(self, model: str, api_key: str = None):
        super().__init__(model, api_key)
        self.provider = "ollama"

    @staticmethod
    def list_models() -> list[str]:
        """Fetch available models from the local Ollama instance."""
        try:
            req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                models = [model['name'] for model in data.get('models', [])]
                return models
        except urllib.error.URLError:
            return []

    def generate(self, messages: list[dict], json_mode: bool = False, timeout_seconds: float | None = None, response_schema: dict | None = None) -> str:
        url = f"{OLLAMA_BASE_URL}/api/chat"
        
        # Format messages for Ollama (it expects role and content)
        ollama_messages = [
            {
                "role": "assistant" if m["role"] in ("agent", "assistant")
                       else "user" if m["role"] == "tool"
                       else m["role"],
                "content": str(m.get("content", ""))
            }
            for m in messages
        ]
        
        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {"temperature": OLLAMA_TEMPERATURE},
        }
        
        if response_schema is not None:
            payload["format"] = response_schema
        elif json_mode:
            payload["format"] = "json"

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        
        try:
            timeout = min(OLLAMA_TIMEOUT, timeout_seconds) if timeout_seconds is not None else OLLAMA_TIMEOUT
            with urllib.request.urlopen(req, timeout=max(0.1, timeout)) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get("message", {}).get("content", "")
        except urllib.error.HTTPError as e:
            # Older Ollama servers accept ``format: json`` but not a JSON
            # schema object. Fall back without weakening strict local parsing.
            if response_schema is not None and e.code in {400, 404}:
                payload["format"] = "json"
                fallback_data = json.dumps(payload).encode('utf-8')
                fallback_req = urllib.request.Request(url, data=fallback_data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(fallback_req, timeout=max(0.1, timeout)) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    return result.get("message", {}).get("content", "")
            raise LLMConnectionError(f"Error connecting to Ollama: {e}") from e
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Error connecting to Ollama: {e}")
