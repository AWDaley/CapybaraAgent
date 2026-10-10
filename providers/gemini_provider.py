import json
import urllib.error
import urllib.request

from llm_client import LLMAPIError, LLMClient, LLMConnectionError, LLMError


class GeminiProvider(LLMClient):
    def __init__(self, model: str, api_key: str = None):
        super().__init__(model, api_key)
        self.provider = "gemini"

    @staticmethod
    def list_models() -> list[str]:
        return ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]

    def generate(self, messages: list[dict], json_mode: bool = False, timeout_seconds: float | None = None) -> str:
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set.")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        
        # Extract system instruction messages vs chat contents
        system_msgs = [msg["content"] for msg in messages if msg.get("role") == "system"]
        chat_msgs = [msg for msg in messages if msg.get("role") != "system"]

        gemini_contents = []
        for msg in chat_msgs:
            role = "model" if msg.get("role") in ("agent", "assistant") else "user"
            gemini_contents.append({
                "role": role,
                "parts": [{"text": str(msg.get("content", ""))}]
            })
            
        payload = {
            "contents": gemini_contents
        }
        
        if system_msgs:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n".join(system_msgs)}]
            }
        
        if json_mode:
            payload["generationConfig"] = {
                "responseMimeType": "application/json"
            }

        data = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'x-goog-api-key': self.api_key
        }
        
        req = urllib.request.Request(url, data=data, headers=headers)
        
        try:
            timeout = min(30, timeout_seconds) if timeout_seconds is not None else 30
            with urllib.request.urlopen(req, timeout=max(0.1, timeout)) as response:
                result = json.loads(response.read().decode('utf-8'))
                # Extract text from Gemini response structure
                try:
                     return result['candidates'][0]['content']['parts'][0]['text']
                except (KeyError, IndexError):
                     raise LLMError(
                         f"Gemini returned an unexpected response structure "
                         f"(possibly blocked by safety filters): {json.dumps(result)[:500]}"
                     )
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise LLMAPIError(f"Gemini API Error ({e.code}): {error_body}", status_code=e.code)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Error connecting to Gemini: {e}")
