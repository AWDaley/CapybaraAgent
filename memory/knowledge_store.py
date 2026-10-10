import json
import os
import threading
from typing import Any


class KnowledgeStore:
    def __init__(self, filepath: str | None = None):
        # Base directory for the agent (parent of memory/)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(base_dir, "data")
        self.filepath = filepath or os.path.join(self.data_dir, "knowledge.json")
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load facts on startup
        self.lock = threading.Lock()
        self.facts = self._load_facts()

    def _load_facts(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Knowledge store corrupted. Backing up and starting fresh.")
                import time
                os.replace(self.filepath, f"{self.filepath}.corrupted.{int(time.time())}")
                return {}
        return {}

    def _save_facts(self):
        tmp_file = self.filepath + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.facts, f, indent=4)
        os.replace(tmp_file, self.filepath)

    def save_fact(self, key: str, value: str, state: str = "reported", source: str = "user", confidence: float = 1.0) -> str:
        with self.lock:
            # If value is simple string, keep clean backward compatible dictionary or string
            self.facts[key] = {
                "value": value,
                "state": state,
                "source": source,
                "confidence": confidence
            }
            self._save_facts()
        return f"Fact saved: {key} = {value}"

    def save_epistemic_fact(self, key: str, value: str, state: str = "observed", source: str = "tool", confidence: float = 1.0) -> str:
        return self.save_fact(key=key, value=value, state=state, source=source, confidence=confidence)

    def get_fact(self, key: str) -> str:
        with self.lock:
            val = self.facts.get(key)
            if val is None:
                return f"Fact not found: {key}"
            if isinstance(val, dict):
                return val.get("value", str(val))
            return str(val)

    def get_fact_entry(self, key: str) -> dict[str, Any] | None:
        with self.lock:
            val = self.facts.get(key)
            if val is None:
                return None
            if isinstance(val, dict):
                return dict(val)
            return {"value": str(val), "state": "reported", "source": "legacy", "confidence": 1.0}

    def get_all_facts(self) -> dict:
        with self.lock:
            result = {}
            for k, v in self.facts.items():
                if isinstance(v, dict):
                    result[k] = v.get("value", str(v))
                else:
                    result[k] = str(v)
            return result

    def get_all_epistemic_facts(self) -> dict:
        with self.lock:
            return dict(self.facts)

    def delete_fact(self, key: str) -> str:
        with self.lock:
            if key in self.facts:
                del self.facts[key]
                self._save_facts()
                return f"Fact deleted: {key}"
            return f"Fact not found: {key}"
