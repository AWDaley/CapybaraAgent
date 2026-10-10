from tal.context_packer import ContextPacker


class ContextManager:
    def __init__(self, max_tokens=4000, summary_threshold=3000, tal_mode: bool = False):
        self.max_tokens = max_tokens
        self.summary_threshold = summary_threshold
        self.tal_mode = tal_mode
        self.packer = ContextPacker()
    
    def trim(self, messages: list[dict], llm_client) -> list[dict]:
        """If messages exceed the threshold, summarize old ones."""
        estimated_tokens = self._estimate_tokens(messages)
        
        if estimated_tokens < self.summary_threshold:
            return messages  # No trimming needed
        
        # Always keep at least 1 recent message to ensure we trim *something* if over threshold
        keep_count = 6
        if len(messages) <= keep_count + 1:
            keep_count = max(1, len(messages) - 2)
            
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        
        if not non_system:
            return system
            
        recent = non_system[-keep_count:]
        middle = non_system[:-keep_count]
        
        if not middle:
            return system + recent
        
        # Ask the LLM to summarize the middle section
        summary = self._summarize(middle, llm_client)
        
        return system + [{"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}] + recent
    
    def _estimate_tokens(self, messages: list[dict]) -> int:
        """Rough estimate: ~4 chars per token."""
        return sum(len(str(m.get("content") or "")) for m in messages) // 4
        
    def _summarize(self, messages: list[dict], llm_client) -> str:
        text_to_summarize = ""
        for m in messages:
            text_to_summarize += f"{m.get('role', 'user').upper()}: {m.get('content', '')!s}\n\n"
            
        prompt = [
            {"role": "system", "content": "You are a helpful assistant. Summarize the following conversation history concisely, retaining all factual information, tool results, and key decisions."},
            {"role": "user", "content": text_to_summarize}
        ]
        
        try:
            return llm_client.generate(prompt)
        except Exception as e:
            print(f"⚠️ Warning: Context summarization failed: {e}")
            truncated = messages[-3:] if len(messages) > 3 else messages
            return "\n".join(f"{m.get('role', 'user').upper()}: {str(m.get('content', ''))[:200]}" for m in truncated)
