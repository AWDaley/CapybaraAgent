class TokenCounter:
    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
    
    def count(self, messages: list[dict], response: str):
        """Estimate tokens for a single LLM call."""
        input_tokens = sum(len(str(m.get("content") or "")) for m in messages) // 4
        output_tokens = len(str(response or "")) // 4
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        return input_tokens + output_tokens
    
    @property
    def total(self):
        return self.total_input_tokens + self.total_output_tokens
