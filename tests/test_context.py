import unittest

from context_manager import ContextManager
from llm_client import LLMClient


class MockLLM(LLMClient):
    def __init__(self):
        super().__init__("mock")
    def generate(self, messages, json_mode: bool = False):
        return "Summary of the past."
    @staticmethod
    def list_models(): return ["mock"]

class TestContextManager(unittest.TestCase):
    def test_trimming(self):
        cm = ContextManager(max_tokens=4000, summary_threshold=0) # 0 to force trimming
        memory = [
            {"role": "system", "content": "0"},
            {"role": "user", "content": "1"},
            {"role": "agent", "content": "2"},
            {"role": "user", "content": "3"},
            {"role": "agent", "content": "4"},
            {"role": "user", "content": "5"},
            {"role": "agent", "content": "6"},
            {"role": "user", "content": "7"}
        ]
        llm = MockLLM()
        trimmed = cm.trim(memory, llm)
        
        # system (1) + summary (1) + last 6 (6) = 8
        self.assertEqual(len(trimmed), 8)
        self.assertEqual(trimmed[0]["role"], "system")
        self.assertEqual(trimmed[1]["role"], "system")
        self.assertIn("Summary of the past.", trimmed[1]["content"])

if __name__ == '__main__':
    unittest.main()
