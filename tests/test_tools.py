import json

import pytest

from tools.basic_tools import calculator
from tools.external_tools import python_repl, run_command
from tools.file_tools import read_file


def test_run_command_safe(monkeypatch, temp_workspace):
    # Mock subprocess.run so we don't actually execute commands on the host
    class MockCompletedProcess:
        def __init__(self, stdout, stderr=""):
            self.stdout = stdout
            self.stderr = stderr
            
    def mock_run(*args, **kwargs):
        return MockCompletedProcess(stdout="mocked output")
        
    import subprocess
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    args = json.dumps({"command": "ping 127.0.0.1 -n 1"})
    result = run_command(args)
    assert "mocked output" in result

def test_run_command_unsafe(monkeypatch, temp_workspace):
    def mock_run(*args, **kwargs):
        pytest.fail("Unsafe command should not be executed")
        
    import subprocess
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    args = json.dumps({"command": "python -c \"print('hello')\" && ls"})
    result = run_command(args)
    assert "Error:" in result
    assert "disallowed characters" in result

def test_python_repl_safe(temp_workspace):
    args = json.dumps({"code": "print('hello world')"})
    result = python_repl(args)
    assert "hello world" in result


def test_python_repl_safe_imports(temp_workspace):
    code = """
import json
import math
import datetime

data = {'val': math.sqrt(16), 'date': str(datetime.date(2026, 1, 1))}
print(json.dumps(data))
"""
    args = json.dumps({"code": code})
    result = python_repl(args)
    assert '"val": 4.0' in result
    assert "2026-01-01" in result


def test_python_repl_safe_introspection(temp_workspace):
    code = """
x = {'a': 1, 'b': 2}
print(f"Is dict: {isinstance(x, dict)}")
print(f"Has get: {hasattr(x, 'get')}")
print(f"Callable: {callable(x.get)}")
print(f"Doc exists: {x.__doc__ is not None}")
print(f"Len dunder: {x.__len__()}")
"""
    args = json.dumps({"code": code})
    result = python_repl(args)
    assert "Is dict: True" in result
    assert "Has get: True" in result
    assert "Callable: True" in result
    assert "Doc exists: True" in result
    assert "Len dunder: 2" in result


def test_python_repl_dunder_escape_remains_blocked(temp_workspace):
    # __class__ and __subclasses__ must remain blocked
    res1 = python_repl(json.dumps({"code": "print(().__class__.__subclasses__())"}))
    assert "Error: Access to private attribute" in res1

    res2 = python_repl(json.dumps({"code": "eval('1 + 1')"}))
    assert "Error: Use of 'eval' is not allowed" in res2


def test_python_repl_networkx_graph(temp_workspace):
    code = """
import networkx as nx
G = nx.DiGraph()
G.add_nodes_from(['A', 'B', 'C'])
G.add_edge('A', 'B')
G.add_edge('B', 'C')
path = nx.shortest_path(G, 'A', 'C')
has_p = nx.has_path(G, 'A', 'C')
no_p = nx.has_path(G, 'C', 'A')
all_p = nx.all_pairs_shortest_path(G)
desc = nx.descendants(G, 'A')
print(f"Path: {' -> '.join(path)}, HasPath: {has_p}, NoPath: {no_p}, Desc: {sorted(list(desc))}")
"""
    args = json.dumps({"code": code})
    result = python_repl(args)
    assert "Path: A -> B -> C" in result
    assert "HasPath: True" in result
    assert "NoPath: False" in result
    assert "Desc: ['B', 'C']" in result


def test_mini_graph_copy_and_isolation(temp_workspace):
    code = """
import networkx as nx
G = nx.DiGraph()
G.add_nodes_from(['SRC', 'CHOKE', 'DEST', 'UNRELATED'])
G.add_edge('SRC', 'CHOKE')
G.add_edge('CHOKE', 'DEST')
G.add_edge('SRC', 'UNRELATED')

# Clone using both .copy() and nx.copy()
G_isolated = G.copy()
G_isolated2 = nx.copy(G)

# Remove choke point node
G_isolated.remove_node('CHOKE')
orig_has_path = nx.has_path(G, 'SRC', 'DEST')
iso_has_path = nx.has_path(G_isolated, 'SRC', 'DEST')
iso_nodes = len(G_isolated.nodes)
orig_nodes = len(G.nodes)
reachable = sorted(list(nx.single_source_reachable(G_isolated, 'SRC')))

print(f"OrigPath: {orig_has_path}, IsoPath: {iso_has_path}, OrigNodes: {orig_nodes}, IsoNodes: {iso_nodes}, Reachable: {reachable}")
"""
    args = json.dumps({"code": code})
    result = python_repl(args)
    assert "OrigPath: True" in result
    assert "IsoPath: False" in result
    assert "OrigNodes: 4" in result
    assert "IsoNodes: 3" in result
    assert "Reachable: ['SRC', 'UNRELATED']" in result


def test_mini_graph_remove_edge_and_subgraph(temp_workspace):
    code = """
import networkx as nx
G = nx.Graph()
G.add_edges_from([('A', 'B'), ('B', 'C'), ('C', 'D'), ('D', 'A')])
G.remove_edge('A', 'B')
has_direct = 'B' in G['A']
sub = G.subgraph(['B', 'C', 'D'])
sub_nodes = sorted(list(sub.nodes))
print(f"DirectAB: {has_direct}, SubNodes: {sub_nodes}")
"""
    args = json.dumps({"code": code})
    result = python_repl(args)
    assert "DirectAB: False" in result
    assert "SubNodes: ['B', 'C', 'D']" in result


def test_python_repl_unsafe(temp_workspace):
    args = json.dumps({"code": "import os\nos.system('echo bad')"})
    result = python_repl(args)
    assert "Error: Import of module 'os' is not allowed" in result


def test_python_repl_rejects_duplicate_literal_dict_keys(temp_workspace):
    result = python_repl(json.dumps({"code": "graph = {'A': [], 'A': ['B']}"}))

    assert "Duplicate literal dictionary key 'A'" in result


def test_run_command_python_inline_blocked(temp_workspace):
    args = json.dumps({"command": "python -c \"print('inline')\""})
    result = run_command(args)
    assert "Error: Inline python execution (-c) is not allowed" in result


def test_run_command_python_script(monkeypatch, temp_workspace):
    # Mock subprocess.run for python script execution
    class MockCompletedProcess:
        def __init__(self, stdout, stderr=""):
            self.stdout = stdout
            self.stderr = stderr

    def mock_run(exec_args, *args, **kwargs):
        assert "test_script.py" in exec_args or any("test_script.py" in str(a) for a in exec_args)
        return MockCompletedProcess(stdout="Script output: 42")

    import subprocess
    monkeypatch.setattr(subprocess, "run", mock_run)

    args = json.dumps({"command": "python test_script.py"})
    result = run_command(args)
    assert "Script output: 42" in result

def test_calculator_safe():
    assert calculator(json.dumps({"expression": "2 + 2"})) == "4"
    assert calculator(json.dumps({"expression": "2 * 10"})) == "20"
    
def test_calculator_unsafe_pow():
    result = calculator(json.dumps({"expression": "999**1001"}))
    assert "Exponent too large (max 1000)" in result

def test_file_tools_path_traversal(temp_workspace):
    args = json.dumps({"path": "../../windows/system32/secret.txt"})
    result = read_file(args)
    assert "Error" in result
    assert "outside workspace" in result.lower()

from tools.external_tools import web_search


def test_web_search_empty_query():
    assert "Error: Query cannot be empty" in web_search("")

def test_web_search_tavily(monkeypatch):
    import urllib.request
    
    class MockResponse:
        def __init__(self, data):
            self.data = data
        def read(self, *_args):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
            
    def mock_urlopen(req, *args, **kwargs):
        # Return a mock Tavily response
        url = req.full_url if hasattr(req, 'full_url') else req
        if "api.tavily.com" in url:
            data = json.dumps({
                "answer": "Mocked Tavily Answer",
                "results": [{"title": "Mock Title", "url": "https://example.com", "content": "Mock Content"}]
            }).encode('utf-8')
            return MockResponse(data)
        elif "lite.duckduckgo.com" in url:
            pytest.fail("Should not reach fallback if Tavily succeeds")
        raise urllib.error.URLError("Mocked URL Error")

    monkeypatch.setattr("tools.external_tools._open_remote_url", lambda req, timeout: mock_urlopen(req))
    monkeypatch.setenv("TAVILY_API_KEY", "mock_key")
    
    result = web_search("test query")
    assert "Mocked Tavily Answer" in result
    assert "Mock Title" in result
    assert "https://example.com" in result

def test_web_search_fallback(monkeypatch):
    import urllib.request
    
    class MockResponse:
        def __init__(self, data):
            self.data = data
        def read(self, *_args):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
            
    def mock_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, 'full_url') else req
        if "api.tavily.com" in url:
            # Simulate Tavily failing
            raise urllib.error.URLError("Tavily down")
        elif "lite.duckduckgo.com" in url:
            # Simulate DDG Lite succeeding
            html = '''
            <a rel="nofollow" href="https://example.com/fallback">Fallback Title</a>
            '''
            return MockResponse(html.encode('utf-8'))
        raise urllib.error.URLError("Mocked URL Error")

    monkeypatch.setattr("tools.external_tools._open_remote_url", lambda req, timeout: mock_urlopen(req))
    monkeypatch.setenv("TAVILY_API_KEY", "mock_key")
    
    result = web_search("test query")
    assert "Fallback Title" in result
    assert "https://example.com/fallback" in result
