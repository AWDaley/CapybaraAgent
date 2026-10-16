import json
import threading
import urllib.error
import urllib.request

import pytest

from web import CapybaraHandler, ThreadingHTTPServer


def test_server_side_browser_state_is_isolated():
    import web
    one = web._get_web_session("00000000-0000-0000-0000-000000000001")
    two = web._get_web_session("00000000-0000-0000-0000-000000000002")
    one["config"]["model"] = "session-one-only"
    assert two["config"]["model"] != "session-one-only"
    assert one["pending_approvals"] is not two["pending_approvals"]
    assert one["repl_scope"] is not two["repl_scope"]

@pytest.fixture(scope="module")
def web_server():
    """Starts the Capybara web server on a random free port for testing."""
    # Use port 0 to bind to an available OS port
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), CapybaraHandler)
    host, port = httpd.server_address
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://{host}:{port}"
    
    yield {"url": base_url, "httpd": httpd}
    
    httpd.shutdown()

def test_static_file_serving(web_server):
    """Root redirect and index.html static serving should return HTTP 200."""
    url = web_server["url"] + "/index.html"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content = resp.read().decode('utf-8')
        assert "Capybara" in content

def test_api_providers(web_server):
    """GET /api/providers should return valid JSON with provider keys."""
    url = web_server["url"] + "/api/providers"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
        assert "ollama" in data
        assert "openai" in data
        assert "gemini" in data

def test_api_workspace(web_server):
    """GET /api/workspace should return a files array."""
    url = web_server["url"] + "/api/workspace"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
        assert "files" in data
        assert isinstance(data["files"], list)

def test_api_workspace_path_traversal(web_server):
    """GET /api/workspace/file with path traversal should return HTTP 403."""
    url = web_server["url"] + "/api/workspace/file?name=../../etc/passwd"
    req = urllib.request.Request(url)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 403

def test_api_config(web_server):
    """POST /api/config with valid config payload should return HTTP 200."""
    url = web_server["url"] + "/api/config"
    payload = json.dumps({"mode": "1", "provider": "ollama", "model": "test"}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
        assert data.get("status") == "ok"

def test_api_sessions_new(web_server):
    """POST /api/sessions/new should return HTTP 200."""
    url = web_server["url"] + "/api/sessions/new"
    req = urllib.request.Request(url, data=b'{}', headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
        assert data.get("status") == "ok"

def test_csrf_rejects_foreign_origin(web_server):
    """POST from a foreign Origin header should return HTTP 403."""
    url = web_server["url"] + "/api/sessions/new"
    req = urllib.request.Request(url, data=b'{}', headers={
        "Content-Type": "application/json",
        "Origin": "http://evil-attacker-site.com"
    })
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 403

def test_csrf_rejects_localhost_prefix_attack(web_server):
    url = web_server["url"] + "/api/sessions/new"
    req = urllib.request.Request(url, data=b'{}', headers={
        "Content-Type": "application/json",
        "Origin": "http://localhost.evil.example"
    })
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 403

def test_config_rejects_unknown_fields(web_server):
    url = web_server["url"] + "/api/config"
    payload = json.dumps({"mode": "1", "unexpected": True}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400

def test_auth_token_protection(monkeypatch):
    """When CAPYBARA_AUTH_TOKEN is set, unauthorized requests get 401 and authorized ones get 200."""
    import web
    monkeypatch.setattr(web, "_auth_token", "secret-test-token")
    
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), CapybaraHandler)
    host, port = httpd.server_address
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://{host}:{port}"
    
    try:
        # Request without token -> 401
        req_unauth = urllib.request.Request(base_url + "/api/providers")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_unauth)
        assert exc_info.value.code == 401

        # Request with wrong token -> 401
        req_bad = urllib.request.Request(base_url + "/api/providers", headers={"Authorization": "Bearer wrong"})
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad)
        assert exc_info.value.code == 401

        # Request with correct token -> 200
        req_good = urllib.request.Request(base_url + "/api/providers", headers={"Authorization": "Bearer secret-test-token"})
        with urllib.request.urlopen(req_good) as resp:
            assert resp.status == 200
    finally:
        httpd.shutdown()


def test_web_cannot_disable_tal_or_approvals(web_server):
    for config in ({"tal_mode": False}, {"guardrails": False}):
        req = urllib.request.Request(
            web_server["url"] + "/api/config",
            data=json.dumps(config).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        assert error.value.code == 403


def test_terminal_outcome_does_not_promote_unverified_steps():
    from agent import BasicAgent
    from web import _terminal_outcome

    agent = BasicAgent(tal_mode=True)
    agent.event_log.append("task_outcome", {"status": "verified"})
    assert _terminal_outcome(agent) == "verified"

    class FakePlan:
        basic_agent = agent

    assert _terminal_outcome(FakePlan()) == "completed_unverified"


def test_plan_terminal_failure_is_visible_from_shared_execution_log():
    from agent import BasicAgent
    from planning_agent import PlanningAgent
    from web import _terminal_outcome
    basic = BasicAgent(tal_mode=True)
    planner = PlanningAgent(basic, basic.llm_client, tal_mode=True)
    basic.event_log.append("task_outcome", {"status": "failed"})
    assert _terminal_outcome(planner) == "failed"


def test_cookie_is_server_issued_and_ignores_spoofed_session_header(web_server):
    import http.cookiejar
    import web

    one_jar, two_jar = http.cookiejar.CookieJar(), http.cookiejar.CookieJar()
    one = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(one_jar))
    two = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(two_jar))

    one.open(web_server["url"] + "/index.html").close()
    two.open(web_server["url"] + "/index.html").close()
    one_cookie = next(c for c in one_jar if c.name == "capybara_sid")
    two_cookie = next(c for c in two_jar if c.name == "capybara_sid")
    assert one_cookie.value != two_cookie.value
    assert "HttpOnly" in one_cookie._rest
    first_id = one_cookie.value.split(".")[0]
    second_id = two_cookie.value.split(".")[0]
    assert first_id != second_id

    # Server-to-server tests can seed files directly; the REST endpoint must
    # expose only the authenticated browser's own scope.
    first_state = web._get_web_session(first_id)
    second_state = web._get_web_session(second_id)
    from pathlib import Path
    Path(first_state["workspace_dir"], "private.txt").write_text("first private", encoding="utf-8")
    Path(second_state["workspace_dir"], "private.txt").write_text("second private", encoding="utf-8")

    first_url = web_server["url"] + "/api/workspace/file?name=private.txt"
    assert json.loads(one.open(first_url).read())["content"] == "first private"
    assert json.loads(two.open(first_url).read())["content"] == "second private"

    spoofed = urllib.request.Request(first_url, headers={"X-Capybara-Session": first_id})
    assert json.loads(two.open(spoofed).read())["content"] == "second private"


def test_invalid_cookie_is_not_an_ownership_credential(web_server):
    invalid_cookie = "capybara_sid=00000000-0000-0000-0000-000000000001.invalid"
    request = urllib.request.Request(
        web_server["url"] + "/api/workspace",
        headers={"Cookie": invalid_cookie},
    )
    with urllib.request.urlopen(request) as response:
        assert response.status == 200
        new_cookie = response.headers.get("Set-Cookie", "")
    assert "capybara_sid=" in new_cookie
    assert "invalid" not in new_cookie


def test_workspace_context_flows_into_tool_worker(tmp_path):
    from pathlib import Path
    from agent import BasicAgent
    from tal.context_packer import ExecutionPhase
    from tools.file_tools import read_file, workspace_scope

    first = Path(tmp_path, "a")
    second = Path(tmp_path, "b")
    first.mkdir()
    second.mkdir()
    (first / "note.txt").write_text("from-a", encoding="utf-8")
    (second / "note.txt").write_text("from-b", encoding="utf-8")
    with workspace_scope(str(first)):
        agent = BasicAgent(tal_mode=True, tool_registry={"read_file": read_file})
        agent.current_phase = ExecutionPhase.EXECUTION
        first_result = agent.act_result("read_file", '{"path":"note.txt"}')
    with workspace_scope(str(second)):
        agent2 = BasicAgent(tal_mode=True, tool_registry={"read_file": read_file})
        agent2.current_phase = ExecutionPhase.EXECUTION
        second_result = agent2.act_result("read_file", '{"path":"note.txt"}')
    agent._executor.shutdown(wait=True)
    agent2._executor.shutdown(wait=True)
    assert first_result.stdout == "from-a"
    assert second_result.stdout == "from-b"


def test_web_rejects_other_browser_session_file(web_server):
    import http.cookiejar
    import web
    jar1 = http.cookiejar.CookieJar()
    jar2 = http.cookiejar.CookieJar()
    browser1 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar1))
    browser2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar2))
    browser1.open(web_server["url"] + "/index.html").close()
    browser2.open(web_server["url"] + "/index.html").close()
    sid1 = next(c for c in jar1 if c.name == "capybara_sid").value.split(".")[0]
    manager = web._get_web_session(sid1)["session_manager"]
    manager.start_new_session()
    manager.auto_save([{"role": "user", "content": "secret"}])
    payload = json.dumps({"filepath": manager.current_session_file}).encode("utf-8")
    request = urllib.request.Request(
        web_server["url"] + "/api/sessions/load", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        browser2.open(request)
    assert error.value.code == 403


def test_browser_memory_is_bound_to_its_session(tmp_path):
    import uuid
    import web
    from tools.basic_tools import remember_to_store, recall_from_store

    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    first = web._get_web_session(first_id)
    second = web._get_web_session(second_id)
    remember_to_store(first["knowledge_store"], '{"key":"private_fact","value":"first"}')
    assert recall_from_store(first["knowledge_store"], '{"key":"private_fact"}') == "first"
    assert "not found" in recall_from_store(
        second["knowledge_store"], '{"key":"private_fact"}'
    ).lower()
    one_agent = web.get_agent(first_id)
    two_agent = web.get_agent(second_id)
    assert one_agent.tools["recall"]('{"key":"private_fact"}') == "first"
    assert "not found" in two_agent.tools["recall"](
        '{"key":"private_fact"}'
    ).lower()


def test_web_session_directory_is_private_on_posix():
    import os
    import uuid
    import web

    state = web._get_web_session(str(uuid.uuid4()))
    assert os.path.isdir(state["workspace_dir"])
    assert state["workspace_dir"].startswith(state["session_manager"].sessions_dir)
    if os.name == "posix":
        assert os.stat(state["session_manager"].sessions_dir).st_mode & 0o077 == 0
        assert os.stat(state["workspace_dir"]).st_mode & 0o077 == 0


def test_memory_fact_does_not_disable_ssl_verification(monkeypatch, tmp_path):
    import tools.external_tools as external
    from tools.basic_tools import remember_to_store
    from memory.knowledge_store import KnowledgeStore
    import ssl

    monkeypatch.delenv("CAPYBARA_INSECURE_SSL", raising=False)
    external._ssl_context_cache.clear()
    remember_to_store(
        KnowledgeStore(filepath=str(tmp_path / "facts.json")),
        '{"key":"CAPYBARA_INSECURE_SSL","value":"1"}',
    )
    secure_context = external._get_ssl_context()
    assert secure_context.verify_mode == ssl.CERT_REQUIRED
    assert secure_context.check_hostname is True


def test_browser_repl_evidence_is_never_shared():
    import uuid
    import web

    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    first = web._get_web_session(first_id)
    second = web._get_web_session(second_id)
    first["repl_scope"].globals["secret_answer"] = 100
    second["repl_scope"].globals["secret_answer"] = 200

    first_agent = web.get_agent(first_id)
    second_agent = web.get_agent(second_id)
    assert first_agent.repl_globals_provider()["secret_answer"] == 100
    assert second_agent.repl_globals_provider()["secret_answer"] == 200
    assert first_agent.repl_globals_provider() is not second_agent.repl_globals_provider()


def test_csrf_rejects_same_host_wrong_port(web_server):
    request = urllib.request.Request(
        web_server["url"] + "/api/sessions/new", data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:1",
        },
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 403
