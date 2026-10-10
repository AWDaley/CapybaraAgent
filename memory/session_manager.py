import datetime
import glob
import json
import os
import uuid

from tal.event_store import EventLog


class SessionManager:
    def __init__(self, session_namespace: str | None = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root_sessions_dir = os.path.join(base_dir, "data", "sessions")
        # The desktop/CLI default retains the historic shared location. Web
        # callers supply an opaque UUID so one browser cannot enumerate or
        # load another browser's saved conversations.
        if session_namespace is not None:
            try:
                safe_namespace = uuid.UUID(str(session_namespace)).hex
            except ValueError as exc:
                raise ValueError("session_namespace must be a UUID") from exc
            self.sessions_dir = os.path.join(root_sessions_dir, "clients", safe_namespace)
        else:
            self.sessions_dir = root_sessions_dir
        os.makedirs(self.sessions_dir, exist_ok=True)
        self.current_session_file = None
        self.current_event_file = None

    def start_new_session(self):
        """Initializes a new session file path."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_id = f"{timestamp}_{uuid.uuid4().hex[:8]}"
        self.current_session_file = os.path.join(self.sessions_dir, f"session_{session_id}.json")
        self.current_event_file = os.path.join(self.sessions_dir, f"events_{session_id}.jsonl")

    def list_sessions(self) -> list[dict]:
        """Returns a list of available sessions sorted by newest first."""
        sessions = []
        pattern = os.path.join(self.sessions_dir, "session_*.json")
        for filepath in glob.glob(pattern):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                # Extract a preview (first user message)
                preview = "Empty session"
                memory = data.get("memory", [])
                for msg in memory:
                    if msg.get("role") == "user":
                        preview = str(msg.get("content", ""))[:50]
                        if len(str(msg.get("content", ""))) > 50:
                             preview += "..."
                        break
                        
                sessions.append({
                    "id": os.path.basename(filepath),
                    "filepath": filepath,
                    "metadata": data.get("metadata", {}),
                    "turn_count": len(memory),
                    "preview": preview,
                    "mtime": os.path.getmtime(filepath)
                })
            except (OSError, json.JSONDecodeError) as e:
                print(f"⚠️ Warning: Could not read session file {filepath}: {e}")
                continue
                
        # Sort newest first
        sessions.sort(key=lambda x: x["mtime"], reverse=True)
        return sessions

    def load_session(self, filepath: str) -> list[dict]:
        """Loads a session's memory and sets it as the current session."""
        from pathlib import Path
        
        try:
            resolved = Path(filepath).resolve()
            sessions_dir = Path(self.sessions_dir).resolve()
            
            if os.path.commonpath([str(sessions_dir), str(resolved)]) != str(sessions_dir):
                print(f"Error: Access denied - path '{filepath}' is outside sessions directory")
                return []
                
            self.current_session_file = str(resolved)
            stem = os.path.basename(str(resolved)).replace("session_", "events_").replace(".json", ".jsonl")
            self.current_event_file = os.path.join(self.sessions_dir, stem)
            
            with open(resolved, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("memory", [])
        except Exception as e:
            print(f"Error loading session: {e}")
            return []

    def load_event_log(self, filepath: str | None = None) -> EventLog | None:
        """Loads the event log for the current or specified session."""
        target_file = filepath or self.current_event_file
        if target_file and os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    return EventLog.from_jsonl(f.read())
            except Exception as e:
                print(f"Error loading event log: {e}")
        return None

    def auto_save(self, memory: list[dict], metadata: dict = None, event_log: EventLog | None = None):
        """Overwrites the current session file with the updated memory and event log."""
        if not self.current_session_file:
            self.start_new_session()
            
        data = {
            "metadata": metadata or {},
            "memory": memory
        }
        
        try:
            tmp_file = self.current_session_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_file, self.current_session_file)

            if event_log and self.current_event_file:
                tmp_evt = self.current_event_file + ".tmp"
                with open(tmp_evt, "w", encoding="utf-8") as f:
                    f.write(event_log.to_jsonl())
                os.replace(tmp_evt, self.current_event_file)
        except Exception as e:
            print(f"Error auto-saving session: {e}")
