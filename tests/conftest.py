import os
import shutil
import tempfile

import pytest

from llm_client import LLMClient
from memory.knowledge_store import KnowledgeStore


class MockLLMClient(LLMClient):
    def __init__(self, responses: list[str] = None):
        super().__init__(model="mock-model")
        self.responses = responses or []
        self.call_count = 0
        self.messages_received = []

    def generate(self, messages: list[dict], json_mode: bool = False) -> str:
        self.messages_received.append(messages)
        if hasattr(self, 'canned_response'):
            return self.canned_response
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return "Mock response"
        
    @staticmethod
    def list_models() -> list[str]:
        return ["mock-model"]

@pytest.fixture
def mock_llm():
    return MockLLMClient()

@pytest.fixture
def temp_workspace(monkeypatch):
    """Provides a temporary directory and patches WORKSPACE_DIR."""
    temp_dir = tempfile.mkdtemp()
    
    import tools.file_tools
    monkeypatch.setattr(tools.file_tools, "WORKSPACE_DIR", temp_dir)
    
    yield temp_dir
    
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture
def isolated_knowledge_store(monkeypatch):
    """Provides an isolated knowledge store."""
    temp_dir = tempfile.mkdtemp()
    
    original_init = KnowledgeStore.__init__
    
    def mock_init(self):
        self.data_dir = temp_dir
        self.filepath = os.path.join(self.data_dir, "knowledge.json")
        import threading
        self.lock = threading.Lock()
        self.facts = {}
        
    monkeypatch.setattr(KnowledgeStore, "__init__", mock_init)
    
    store = KnowledgeStore()
    yield store
    
    shutil.rmtree(temp_dir, ignore_errors=True)
