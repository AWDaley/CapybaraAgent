import http.server
import json
import logging
import os
import socketserver
import threading
import urllib.parse
import uuid

from agent import BasicAgent
from agents.orchestrator import OrchestratorAgent
from llm_client import create_llm_client, list_available_models
from memory import SessionManager
from memory.knowledge_store import KnowledgeStore
from planning_agent import PlanningAgent
from tools import TOOL_REGISTRY
from tools.external_tools import create_repl_scope

logger = logging.getLogger("capybara.web")
_auth_token = os.environ.get("CAPYBARA_AUTH_TOKEN")

# Defaults are copied into each browser session.  Do not put mutable state here.
_DEFAULT_AGENT_CONFIG = {
    "provider": "ollama",
    "model": "qwen3.5:4b",
    "api_key": None,
    "mode": "1", # 1: ReAct, 2: Plan, 3: Multi-Agent
    "reflection": False,
    "guardrails": True,
    "tal_mode": True,
}

_state_lock = threading.Lock()
_web_sessions = {}
MAX_REQUEST_BYTES = 256 * 1024
_CONFIG_FIELDS = {"provider", "model", "api_key", "mode", "reflection", "guardrails", "tal_mode"}

def _new_web_session(session_id=None):
    """Return isolated server-side state for one browser session."""
    return {
        "config": dict(_DEFAULT_AGENT_CONFIG),
        "knowledge_store": KnowledgeStore(
            filepath=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sessions", f"knowledge_{session_id or uuid.uuid4().hex}.json")
        ),
        "agent": None,
        "session_manager": SessionManager(session_namespace=session_id or str(uuid.uuid4())),
        "pending_approvals": {},
        "run_lock": threading.Lock(),
        "repl_scope": create_repl_scope(),
    }


def _get_web_session(session_id):
    with _state_lock:
        if session_id not in _web_sessions:
            # "legacy" exists for old API clients which omit the header, but
            # receives a random private namespace rather than shared history.
            _web_sessions[session_id] = _new_web_session(None if session_id == "legacy" else session_id)
        return _web_sessions[session_id]


def _shutdown_agent(agent):
    """Release an agent's executor when a session changes configuration."""
    basic = getattr(agent, "basic_agent", agent)
    executor = getattr(basic, "_executor", None)
    if executor:
        executor.shutdown(wait=False, cancel_futures=True)


def get_agent(session_id="legacy"):
    """Lazily instantiate an agent using only the requesting session's config."""
    state = _get_web_session(session_id)
    with _state_lock:
        if state["agent"]:
            return state["agent"]
            
        config = state["config"]
        if not config["provider"] or not config["model"]:
            return None
            
        llm = create_llm_client(
            config["provider"], 
            config["model"], 
            config["api_key"]
        )
        
        guardrails_flag = config.get("guardrails", True)
        
        scoped_tools = dict(TOOL_REGISTRY)
        scoped_tools["python_repl"] = state["repl_scope"].run
        basic = BasicAgent(
            llm_client=llm,
            system_prompt="You are a helpful AI assistant. You have access to tools. If the user asks you to do something that requires a tool, use it! Otherwise, just chat with them normally.",
            verbose=False, # We capture traces via run_turn_with_trace now
            knowledge_store=state["knowledge_store"],
            guardrails_enabled=guardrails_flag,
            reflection_enabled=config["reflection"],
            tool_registry=scoped_tools,
            tal_mode=config.get("tal_mode", True),
        )
        
        mode = config["mode"]
        if mode == "2":
            state["agent"] = PlanningAgent(basic, llm, tal_mode=config.get("tal_mode", True))
        elif mode == "3":
            state["agent"] = OrchestratorAgent(
                llm_client=llm,
                verbose=False,
                knowledge_store=state["knowledge_store"],
                guardrails_enabled=guardrails_flag,
                reflection_enabled=config["reflection"],
                tool_registry=scoped_tools,
                tal_mode=config.get("tal_mode", True),
            )
        else:
            state["agent"] = basic
            
        # Start fresh session file for the web UI by default if none loaded
        if not state["session_manager"].current_session_file:
             state["session_manager"].start_new_session()
             
        return state["agent"]


class CapybaraHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        super().__init__(*args, directory=web_dir, **kwargs)
        
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _session_id(self):
        """Read the opaque client ID without accepting arbitrary server keys."""
        value = self.headers.get("X-Capybara-Session", "legacy")
        if value == "legacy":
            return value
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError):
            return "legacy"

    def _public_config(self, config):
        config = dict(config)
        config["api_key"] = None
        return config

    def _check_auth(self) -> bool:
        """Returns True if request is authorized. Sends 401 and returns False otherwise."""
        if not _auth_token:
            return True  # No auth configured
        auth_header = self.headers.get("Authorization", "")
        if auth_header == f"Bearer {_auth_token}":
            return True
        self._send_json({"error": "Unauthorized"}, status=401)
        return False

    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header('Location', '/index.html')
            self.end_headers()
            return
            
        if self.path.startswith("/api/"):
            self.handle_api_get()
            return
            
        # Let SimpleHTTPRequestHandler serve files in /web/
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self.handle_api_post()
            return
        self.send_response(404)
        self.end_headers()

    def handle_api_get(self):
        if not self._check_auth():
            return
        session_id = self._session_id()
        state = _get_web_session(session_id)
        if self.path == "/api/providers":
            providers = ["ollama", "openai", "gemini"]
            data = {}
            for p in providers:
                try:
                    data[p] = list_available_models(p)
                except Exception:
                    data[p] = []
            self._send_json(data)
            
        elif self.path == "/api/sessions":
            with _state_lock:
                sessions = state["session_manager"].list_sessions()
            self._send_json(sessions)
            
        elif self.path == "/api/workspace":
            workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "workspace"))
            os.makedirs(workspace_dir, exist_ok=True)
            files = []
            for f in os.listdir(workspace_dir):
                path = os.path.join(workspace_dir, f)
                if os.path.isfile(path):
                    files.append({"name": f, "size": os.path.getsize(path)})
            self._send_json({"files": files})
            
        elif self.path.startswith("/api/workspace/file"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            filename = query.get("name", [""])[0]
            if not filename:
                self._send_json({"error": "Filename required"}, status=400)
                return
                
            workspace_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "workspace"))
            safe_path = os.path.realpath(os.path.join(workspace_dir, filename))
            
            if os.path.commonpath([workspace_dir, safe_path]) != workspace_dir:
                self._send_json({"error": "Access denied: path traversal detected"}, status=403)
                return
                
            if not os.path.exists(safe_path):
                self._send_json({"error": "File not found"}, status=404)
                return
                
            try:
                with open(safe_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self._send_json({"name": filename, "content": content})
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
                
        else:
            self._send_json({"error": "Endpoint not found"}, status=404)

    def handle_api_post(self):
        if not self._check_auth():
            return
        session_id = self._session_id()
        state = _get_web_session(session_id)
        # CSRF check
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if origin:
            parsed_origin = urllib.parse.urlparse(origin)
            if parsed_origin.scheme not in {"http", "https"} or parsed_origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
                self._send_json({"error": "Forbidden: cross-origin request"}, status=403)
                return
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length"}, status=400)
            return
        if content_length > MAX_REQUEST_BYTES:
            self._send_json({"error": "Request body too large"}, status=413)
            return
        post_data = self.rfile.read(content_length)
        
        try:
            body = json.loads(post_data.decode('utf-8')) if post_data else {}
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, status=400)
            return
        if not isinstance(body, dict):
            self._send_json({"error": "JSON request body must be an object"}, status=400)
            return

        if self.path == "/api/config":
            unexpected = set(body) - _CONFIG_FIELDS
            if unexpected:
                self._send_json({"error": f"Unsupported configuration fields: {', '.join(sorted(unexpected))}"}, status=400)
                return
            if "provider" in body and body["provider"] not in {"ollama", "openai", "gemini"}:
                self._send_json({"error": "Unsupported provider"}, status=400)
                return
            if body.get("tal_mode") is False or body.get("guardrails") is False:
                self._send_json({"error": "TAL and approval enforcement cannot be disabled through the web API"}, status=403)
                return
            if "mode" in body and body["mode"] not in {"1", "2", "3"}:
                self._send_json({"error": "Unsupported mode"}, status=400)
                return
            if any(field in body and not isinstance(body[field], bool) for field in ("reflection", "guardrails", "tal_mode")):
                self._send_json({"error": "Boolean configuration fields must be true or false"}, status=400)
                return
            if "api_key" in body and (not isinstance(body["api_key"], str) or len(body["api_key"]) > 4096):
                self._send_json({"error": "Invalid API key value"}, status=400)
                return
            with _state_lock:
                old_agent = state["agent"]
                state["config"].update(body)
                state["agent"] = None # Force recreation only for this browser session.
            if old_agent:
                _shutdown_agent(old_agent)
            self._send_json({"status": "ok", "config": self._public_config(state["config"])})
            
        elif self.path == "/api/sessions/new":
            with _state_lock:
                state["session_manager"].start_new_session()
                agent = state["agent"]
                state["repl_scope"].reset()
            if agent and hasattr(agent, 'memory'):
                agent.reset_memory()
            elif agent and hasattr(agent, 'basic_agent'):
                agent.basic_agent.reset_memory()
            self._send_json({"status": "ok"})
            
        elif self.path == "/api/sessions/load":
            filepath = body.get("filepath")
            if filepath:
                with _state_lock:
                    mem = state["session_manager"].load_session(filepath)
                # Ensure agent exists before setting memory
                agent = get_agent(session_id)
                if agent:
                    if hasattr(agent, 'memory'):
                        agent.memory = mem
                    elif hasattr(agent, 'basic_agent'):
                        agent.basic_agent.memory = mem
                self._send_json({"status": "ok", "memory": mem})
            else:
                self._send_json({"error": "No filepath provided"}, status=400)
                
        elif self.path == "/api/chat/approve":
            approval_id = body.get("approval_id")
            approved = body.get("approved")
            
            if not approval_id or not isinstance(approved, bool):
                self._send_json({"error": "Missing approval_id or approved boolean"}, status=400)
                return
                
            with _state_lock:
                approvals = state["pending_approvals"]
                if approval_id in approvals:
                    approvals[approval_id]["approved"] = approved
                    approvals[approval_id]["event"].set()
                    found = True
                else:
                    found = False
            
            if found:
                self._send_json({"status": "ok"})
            else:
                self._send_json({"error": "Approval ID not found or already processed"}, status=404)
                
        elif self.path == "/api/chat":
            message = body.get("message")
            if not message:
                self._send_json({"error": "No message provided"}, status=400)
                return
                
            agent = get_agent(session_id)
            if not agent:
                self._send_json({"error": "Agent not configured. Please set provider and model in settings."}, status=400)
                return
                
            def _default_deny_callback(tool_name, tool_args):
                """Auto-deny dangerous tools in non-streaming sync calls."""
                return False

            try:
                with _state_lock:
                    mode = state["config"]["mode"]
                    model = state["config"]["model"]
                    provider = state["config"]["provider"]

                with state["run_lock"]:
                    if mode in ("2", "3"):
                         trace = agent.run_with_trace(message, approval_callback=_default_deny_callback)
                    else:
                         trace = agent.run_turn_with_trace(message, approval_callback=_default_deny_callback)
                     
                # Auto-save
                mem = []
                if hasattr(agent, 'memory'): mem = agent.memory
                elif hasattr(agent, 'basic_agent'): mem = agent.basic_agent.memory
                with _state_lock:
                    state["session_manager"].auto_save(mem, metadata={"model": model, "provider": provider})
                
                self._send_json(trace)
            except Exception as e:
                import traceback
                logger.error("Error in /api/chat: %s", traceback.format_exc())
                self._send_json({"error": str(e)}, status=500)
                
        elif self.path == "/api/chat/stream":
            message = body.get("message")
            if not message:
                self._send_json({"error": "No message provided"}, status=400)
                return
                
            agent = get_agent(session_id)
            if not agent:
                self._send_json({"error": "Agent not configured."}, status=400)
                return
                
            # Setup SSE headers
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            def emit(event_type, data):
                payload = json.dumps({"type": event_type, **data})
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
                
            def request_approval(tool_name, args):
                approval_id = str(uuid.uuid4())
                event = threading.Event()
                with _state_lock:
                    state["pending_approvals"][approval_id] = {"event": event, "approved": False}
                
                # Tell the UI we need approval
                emit("approval_needed", {"tool": tool_name, "args": args, "id": approval_id})
                
                # Pause this thread until the event is set by /api/chat/approve
                event.wait(timeout=60)  # Expire unattended approval prompts
                
                with _state_lock:
                    approval = state["pending_approvals"].pop(approval_id, None)
                    approved = bool(approval and approval["approved"])
                return approved
                
            try:
                with _state_lock:
                    mode = state["config"]["mode"]
                    model = state["config"]["model"]
                    provider = state["config"]["provider"]

                with state["run_lock"]:
                    if mode in ("2", "3"):
                        agent.run_streaming(message, callback=emit, approval_callback=request_approval)
                    else:
                        agent.run_turn_streaming(message, callback=emit, approval_callback=request_approval)
                    
                # Get token count from basic agent
                tokens = 0
                if hasattr(agent, 'token_counter'): tokens = agent.token_counter.total
                elif hasattr(agent, 'basic_agent') and hasattr(agent.basic_agent, 'token_counter'): tokens = agent.basic_agent.token_counter.total
                
                emit("done", {"tokens_used": tokens})
                
                # Auto-save
                mem = []
                if hasattr(agent, 'memory'): mem = agent.memory
                elif hasattr(agent, 'basic_agent'): mem = agent.basic_agent.memory
                with _state_lock:
                    state["session_manager"].auto_save(mem, metadata={"model": model, "provider": provider})
                
            except Exception as e:
                import traceback
                logger.error("Error in /api/chat/stream: %s", traceback.format_exc())
                emit("error", {"content": str(e)})
                
        else:
            self._send_json({"error": "Endpoint not found"}, status=404)

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def start_server(host="localhost", port=8000):
    if host not in {"localhost", "127.0.0.1", "::1"} and os.environ.get("CAPYBARA_UNSAFE_LOCAL_EXEC") == "1":
        raise RuntimeError("Unsafe local development execution cannot be exposed over a network.")
    if host not in {"localhost", "127.0.0.1", "::1"} and not _auth_token:
        raise RuntimeError("CAPYBARA_AUTH_TOKEN is required when binding beyond loopback.")
    with ThreadingHTTPServer((host, port), CapybaraHandler) as httpd:
        logger.info(f"Capybara Web UI running at http://{host}:{port}")
        if _auth_token:
            logger.info("🔒 Bearer token authentication is ENABLED.")
        else:
            logger.info("⚠️  No CAPYBARA_AUTH_TOKEN set — running without authentication.")
        logger.info("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("\nShutting down server...")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    start_server()
