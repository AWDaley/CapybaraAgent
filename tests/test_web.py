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
