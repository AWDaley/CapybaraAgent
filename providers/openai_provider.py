import json
import urllib.error
import urllib.request

from llm_client import LLMAPIError, LLMClient, LLMConnectionError, LLMError


class OpenAIProvider(LLMClient):
    def __init__(self, model: str, api_key: str = None, temperature: float = 0.0):
        super().__init__(model, api_key)
        self.provider = "openai"
        self.temperature = temperature

    @staticmethod
    def list_models() -> list[str]:
        return ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]

    def generate(self, messages: list[dict], json_mode: bool = False, timeout_seconds: float | None = None) -> str:
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set.")
            
        url = "https://api.openai.com/v1/chat/completions"
        
        # Map internal roles to OpenAI API roles
        mapped_messages = [
            {
                "role": "assistant" if msg["role"] in ("agent", "assistant")
                       else "user" if msg["role"] == "tool"
                       else msg["role"],
                "content": str(msg.get("content", ""))
            }
            for msg in messages
        ]

        payload = {
            "model": self.model,
            "messages": mapped_messages,
            "temperature": self.temperature
        }
        
        if json_mode:
            payload["response_format"] = { "type": "json_object" }

        data = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        
        req = urllib.request.Request(url, data=data, headers=headers)
        
        try:
            timeout = min(30, timeout_seconds) if timeout_seconds is not None else 30
            with urllib.request.urlopen(req, timeout=max(0.1, timeout)) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['choices'][0]['message'].get('content', '')
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise LLMAPIError(f"OpenAI API Error ({e.code}): {error_body}", status_code=e.code)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Error connecting to OpenAI: {e}")
