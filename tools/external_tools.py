import ast
import io
import ipaddress
import json
import os
import re
import shlex
import socket
import ssl
import subprocess
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from tal.safe_paths import validate_relative_workspace_path


# --- .env loader -----------------------------------------------------------
def _load_dotenv():
    """Load key=value pairs from the project .env file into os.environ."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass

_load_dotenv()

# SSL policy is controlled by trusted process configuration ONLY.
# Model-writeable memory must never alter transport security for other users.
_ssl_context_cache = {}

def _get_ssl_context():
    """Use a verified context by default; cache each explicit policy separately."""
    insecure = os.environ.get("CAPYBARA_INSECURE_SSL") == "1"
    cached = _ssl_context_cache.get(insecure)
    if cached is not None:
        return cached
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
    _ssl_context_cache[insecure] = ctx
    return ctx


def _validate_remote_url(url: str) -> urllib.parse.ParseResult:
    """Allow only public HTTP(S) destinations and reject SSRF-prone addresses."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must include a hostname and cannot include credentials")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host '{parsed.hostname}'") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise ValueError("URL resolves to a non-public network address")
    return parsed


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_remote_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_remote_url(request: urllib.request.Request, timeout: int):
    _validate_remote_url(request.full_url)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_get_ssl_context()), _SafeRedirectHandler())
    return opener.open(request, timeout=timeout)

# --- Web search (Tavily → DuckDuckGo Lite fallback) -----------------------
def _tavily_search(query: str, ctx) -> str | None:
    """Search using the Tavily REST API. Returns formatted string or None."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return None

    url = "https://api.tavily.com/search"
    payload = json.dumps({
        "query": query,
        "max_results": 5,
        "include_answer": True,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        with _open_remote_url(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

            parts = []
            answer = data.get("answer")
            if answer:
                parts.append(f"Summary: {answer}")

            for r in data.get("results", []):
                title = r.get("title", "")
                link = r.get("url", "")
                snippet = r.get("content", "")[:200]
                parts.append(f"- {title}\n  URL: {link}\n  {snippet}")

            if parts:
                return "\n\n".join(parts)
    except Exception:
        pass
    return None


def _ddg_lite_search(query: str, ctx) -> str | None:
    """Fallback: scrape DuckDuckGo Lite HTML for search results."""
    try:
        url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with _open_remote_url(req, timeout=10) as response:
            html = response.read(512_001).decode("utf-8", errors="ignore")[:512_000]

        # Extract result links (skip ad links that go through duckduckgo.com/y.js)
        raw_links = re.findall(
            r'<a[^>]*rel="nofollow"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        results = []
        for link, title in raw_links:
            # Resolve DDG redirect URLs
            actual = re.search(r'uddg=([^&]+)', link)
            if actual:
                resolved = urllib.parse.unquote(actual.group(1))
            else:
                resolved = link
            # Skip ad tracking URLs
            if "duckduckgo.com/y.js" in resolved:
                continue
            title_clean = re.sub(r'<[^>]+>', '', title).strip()
            if title_clean and resolved.startswith("http"):
                results.append(f"- {title_clean}\n  URL: {resolved}")
            if len(results) >= 5:
                break

        if results:
            return "\n\n".join(results)
    except Exception:
        pass
    return None


def web_search(query: str) -> str:
    """Searches the web using Tavily Search API (primary) with DuckDuckGo Lite fallback."""
    if not query:
        return "Error: Query cannot be empty."

    ctx = _get_ssl_context()

    # Primary: Tavily Search API
    result = _tavily_search(query, ctx)
    if result:
        return result

    # Fallback: DuckDuckGo Lite HTML scraping
    result = _ddg_lite_search(query, ctx)
    if result:
        return result

    return "No results found. Try rephrasing your search query."

def read_url(args: str) -> str:
    """Reads a webpage and extracts plain text. Expects JSON args."""
    try:
        data = json.loads(args)
        url = data.get("url", "")
        if not url:
            return "Error: 'url' must be provided."
            
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with _open_remote_url(req, timeout=10) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                return f"Error: Unsupported content type '{content_type}'."
            max_bytes = 512_000
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raw = raw[:max_bytes]
            html = raw.decode('utf-8', errors='ignore')
            
            try:
                from html.parser import HTMLParser
                class TextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.text = []
                        self.ignore_tags = {'script', 'style', 'head', 'meta', 'title', 'noscript'}
                        self.in_ignore = False
                        
                    def handle_starttag(self, tag, attrs):
                        if tag in self.ignore_tags:
                            self.in_ignore = True
                            
                    def handle_endtag(self, tag):
                        if tag in self.ignore_tags:
                            self.in_ignore = False
                            
                    def handle_data(self, data):
                        if not self.in_ignore and data.strip():
                            self.text.append(data.strip())
                            
                parser = TextExtractor()
                parser.feed(html)
                text = " ".join(parser.text)
            except Exception:
                # Fallback to crude regex
                html = re.sub(r'<(script|style).*?>.*?</\1>', '', html, flags=re.IGNORECASE | re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', html)
                
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Truncate to avoid blowing up LLM context
            max_len = 2000
            if len(text) > max_len:
                text = text[:max_len] + "... (truncated)"
            return text
            
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"url\": \"...\"}"
    except ValueError as e:
        return f"Error reading URL: {e}"
    except urllib.error.URLError as e:
        if hasattr(e, 'reason') and ("CERTIFICATE_VERIFY_FAILED" in str(e.reason) or isinstance(e.reason, ssl.SSLCertVerificationError)):
            return "Error: SSL Certificate Verification Failed. If you are behind a corporate proxy or using self-signed certificates, please set the environment variable CAPYBARA_INSECURE_SSL=1 to bypass SSL verification."
        return f"Error reading URL: {e}"
    except Exception as e:
        return f"Error reading URL: {e}"

def run_command(args: str) -> str:
    """Executes a sandboxed shell command. Expects JSON args."""
    try:
        data = json.loads(args)
        command = data.get("command", "")
        if not command:
            return "Error: 'command' must be provided."
            
        # Check for shell metacharacters
        SHELL_METACHARACTERS = {'&', '|', ';', '$', '`', '>', '<', '\n', '\r'}
        if any(c in command for c in SHELL_METACHARACTERS):
            return "Error: Command contains disallowed characters (shell operators are not permitted)."
            
        # Tokenize and validate
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return f"Error: Invalid command syntax: {e}"
            
        if not tokens:
            return "Error: Empty command."

        for token in tokens[1:]:
            try:
                validate_relative_workspace_path(token)
            except ValueError:
                return "Error: Command arguments cannot reference paths outside the workspace."
            
        # Whitelist of safe commands
        ALLOWED_COMMANDS = {"dir", "echo", "type", "findstr", "ping", "ls", "cat", "python", "python3"}
        base_command = os.path.basename(tokens[0]).lower()
        if base_command not in ALLOWED_COMMANDS:
            return f"Error: Command '{base_command}' not allowed. Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}"

        import tools.file_tools
        workspace_dir = tools.file_tools.WORKSPACE_DIR
        os.makedirs(workspace_dir, exist_ok=True)

        # Handle python execution safely: disallow inline -c execution, use sys.executable
        if base_command in ("python", "python3"):
            if any(tok.startswith("-c") or tok == "-c" for tok in tokens[1:]):
                return "Error: Inline python execution (-c) is not allowed."
            script_args = []
            script_seen = False
            for tok in tokens[1:]:
                if not script_seen and not tok.startswith("-"):
                    script_args.append(os.path.join(workspace_dir, tok))
                    script_seen = True
                else:
                    script_args.append(tok)
            exec_args = [sys.executable] + script_args
            use_shell = False
        else:
            # On Windows, shell builtins use an explicit cmd process; shell=True is never used.
            WINDOWS_BUILTINS = {"dir", "echo", "type"}
            use_shell = False
            exec_args = ["cmd", "/d", "/s", "/c", command] if sys.platform == "win32" and base_command in WINDOWS_BUILTINS else tokens
        
        result = subprocess.run(
            exec_args,
            shell=use_shell,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
            
        if not output.strip():
            return "Command executed successfully (no output)."
            
        # Truncate to prevent context bloat
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        return output
        
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"command\": \"...\"}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 15 seconds."
    except Exception as e:
        return f"Error executing command: {e}"

SAFE_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in [
        'print', 'len', 'range', 'int', 'float', 'str', 'list', 'dict',
        'tuple', 'set', 'enumerate', 'zip', 'map', 'filter', 'sorted',
        'reversed', 'isinstance', 'hasattr', 'callable', 'repr', 'iter', 'next',
        'hash', 'slice', 'bool', 'abs', 'round', 'min',
        'max', 'sum', 'any', 'all', 'ord', 'hex', 'bin', 'oct',
        'True', 'False', 'None', 'Exception', 'ValueError', 'TypeError',
        'KeyError', 'IndexError', 'StopIteration',
        '__build_class__', 'object', 'super', 'property', 'classmethod', 'staticmethod',
    ]
}

import base64
import bisect
import collections
import copy
import csv
import dataclasses
import datetime
import decimal
import enum
import fractions
import functools
import hashlib
import heapq
import hmac
import itertools
import math
import operator
import pprint
import queue
import random
import statistics
import string
import time
import typing

try:
    import networkx
except ImportError:
    networkx = None


class _MiniGraph:
    def __init__(self, **attr):
        self._adj = {}
        self._node_attr = {}
        self._edge_attr = {}
        self.graph = attr

    def add_node(self, node_for_adding, **attr):
        if node_for_adding not in self._adj:
            self._adj[node_for_adding] = set() if not self.is_directed() else dict()
            self._node_attr[node_for_adding] = {}
        self._node_attr[node_for_adding].update(attr)

    def add_nodes_from(self, nodes_for_adding, **attr):
        for n in nodes_for_adding:
            if isinstance(n, tuple) and len(n) == 2 and isinstance(n[1], dict):
                self.add_node(n[0], **{**attr, **n[1]})
            else:
                self.add_node(n, **attr)

    def add_edge(self, u_of_edge, v_of_edge, **attr):
        u, v = u_of_edge, v_of_edge
        self.add_node(u)
        self.add_node(v)
        if isinstance(self._adj[u], set):
            self._adj[u].add(v)
            self._adj[v].add(u)
        else:
            self._adj[u][v] = attr
        self._edge_attr[(u, v)] = attr
        if not self.is_directed():
            self._edge_attr[(v, u)] = attr

    def add_edges_from(self, ebunch_to_add, **attr):
        for e in ebunch_to_add:
            if len(e) == 2:
                self.add_edge(e[0], e[1], **attr)
            elif len(e) == 3:
                self.add_edge(e[0], e[1], **{**attr, **e[2]})

    @property
    def nodes(self):
        class _NodeView:
            def __init__(self, graph):
                self._graph = graph
            def __iter__(self):
                return iter(self._graph._adj.keys())
            def __len__(self):
                return len(self._graph._adj)
            def __contains__(self, n):
                return n in self._graph._adj
            def __call__(self, data=False):
                if data:
                    return [(n, self._graph._node_attr.get(n, {})) for n in self._graph._adj]
                return list(self._graph._adj.keys())
            def __repr__(self):
                return f"NodeView({list(self._graph._adj.keys())})"
        return _NodeView(self)

    @property
    def edges(self):
        class _EdgeView:
            def __init__(self, graph):
                self._graph = graph
            def __iter__(self):
                return iter(self._graph._edge_attr.keys())
            def __len__(self):
                return len(self._graph._edge_attr)
            def __call__(self, data=False):
                if data:
                    return [(u, v, d) for (u, v), d in self._graph._edge_attr.items()]
                return list(self._graph._edge_attr.keys())
            def __repr__(self):
                return f"EdgeView({list(self._graph._edge_attr.keys())})"
        return _EdgeView(self)

    def number_of_nodes(self):
        return len(self._adj)

    def number_of_edges(self):
        return len(self._edge_attr) if self.is_directed() else len(self._edge_attr) // 2

    def is_directed(self):
        return False

    def __contains__(self, n):
        return n in self._adj

    def __iter__(self):
        return iter(self._adj)

    def __len__(self):
        return len(self._adj)

    def __getitem__(self, n):
        return self._adj[n]

    def copy(self):
        new_g = self.__class__(**self.graph)
        if self.is_directed():
            new_g._adj = {k: dict(v) for k, v in self._adj.items()}
        else:
            new_g._adj = {k: set(v) for k, v in self._adj.items()}
        new_g._node_attr = {k: dict(v) for k, v in self._node_attr.items()}
        new_g._edge_attr = {k: dict(v) for k, v in self._edge_attr.items()}
        return new_g

    def remove_node(self, n):
        if n not in self._adj:
            return
        if self.is_directed():
            del self._adj[n]
            for u in list(self._adj.keys()):
                if n in self._adj[u]:
                    del self._adj[u][n]
        else:
            for neighbor in list(self._adj[n]):
                if neighbor in self._adj and n in self._adj[neighbor]:
                    self._adj[neighbor].remove(n)
            del self._adj[n]
        self._node_attr.pop(n, None)
        self._edge_attr = {e: attr for e, attr in self._edge_attr.items() if n not in e}

    def remove_nodes_from(self, nodes):
        for n in nodes:
            self.remove_node(n)

    def remove_edge(self, u, v):
        if self.is_directed():
            if u in self._adj and v in self._adj[u]:
                del self._adj[u][v]
            self._edge_attr.pop((u, v), None)
        else:
            if u in self._adj and v in self._adj[u]:
                self._adj[u].remove(v)
            if v in self._adj and u in self._adj[v]:
                self._adj[v].remove(u)
            self._edge_attr.pop((u, v), None)
            self._edge_attr.pop((v, u), None)

    def remove_edges_from(self, ebunch):
        for e in ebunch:
            self.remove_edge(e[0], e[1])

    def subgraph(self, nodes):
        nodes_set = set(nodes)
        sub = self.copy()
        for n in list(sub.nodes):
            if n not in nodes_set:
                sub.remove_node(n)
        return sub


class _MiniDiGraph(_MiniGraph):
    def is_directed(self):
        return True


def _mini_shortest_path(G, source, target, weight=None):
    from collections import deque
    queue = deque([(source, [source])])
    visited = {source}
    while queue:
        current, path = queue.popleft()
        if current == target:
            return path
        neighbors = G[current] if isinstance(G, dict) or hasattr(G, "__getitem__") else []
        for n in neighbors:
            if n not in visited:
                visited.add(n)
                queue.append((n, path + [n]))
    raise ValueError(f"No path between {source} and {target}")


def _mini_has_path(G, source, target):
    try:
        _mini_shortest_path(G, source, target)
        return True
    except Exception:
        return False


def _mini_all_pairs_shortest_path(G):
    nodes = list(G.nodes) if hasattr(G, "nodes") else list(G.keys())
    res = {}
    for n in nodes:
        res[n] = {}
        for target in nodes:
            try:
                res[n][target] = _mini_shortest_path(G, n, target)
            except Exception:
                pass
    return res


def _mini_all_pairs_dijkstra_path_length(G):
    paths = _mini_all_pairs_shortest_path(G)
    res = {}
    for s, targets in paths.items():
        res[s] = {t: len(p) - 1 for t, p in targets.items()}
    return res


def _mini_is_connected(G):
    nodes = list(G.nodes) if hasattr(G, "nodes") else list(G.keys())
    if not nodes:
        return True
    for t in nodes[1:]:
        if not _mini_has_path(G, nodes[0], t):
            return False
    return True


def _mini_descendants(G, source):
    from collections import deque
    queue = deque([source])
    visited = set()
    while queue:
        cur = queue.popleft()
        neighbors = G[cur] if isinstance(G, dict) or hasattr(G, "__getitem__") else []
        for n in neighbors:
            if n not in visited and n != source:
                visited.add(n)
                queue.append(n)
    return visited


def _mini_ancestors(G, source):
    nodes = list(G.nodes) if hasattr(G, "nodes") else list(G.keys())
    ancestors_set = set()
    for n in nodes:
        if n != source and _mini_has_path(G, n, source):
            ancestors_set.add(n)
    return ancestors_set


def _mini_single_source_shortest_path_length(G, source, cutoff=None):
    from collections import deque
    queue = deque([(source, 0)])
    lengths = {source: 0}
    while queue:
        cur, dist = queue.popleft()
        if cutoff is not None and dist >= cutoff:
            continue
        neighbors = G[cur] if isinstance(G, dict) or hasattr(G, "__getitem__") else []
        for n in neighbors:
            if n not in lengths:
                lengths[n] = dist + 1
                queue.append((n, dist + 1))
    return lengths


def _mini_single_source_reachable(G, source):
    return set(_mini_single_source_shortest_path_length(G, source).keys())


def _mini_copy(G):
    return G.copy() if hasattr(G, "copy") else copy.deepcopy(G)


class _MiniNetworkXModule:
    Graph = _MiniGraph
    DiGraph = _MiniDiGraph
    shortest_path = staticmethod(_mini_shortest_path)
    dijkstra_path = staticmethod(_mini_shortest_path)
    has_path = staticmethod(_mini_has_path)
    all_pairs_shortest_path = staticmethod(_mini_all_pairs_shortest_path)
    all_pairs_dijkstra_path_length = staticmethod(_mini_all_pairs_dijkstra_path_length)
    is_connected = staticmethod(_mini_is_connected)
    descendants = staticmethod(_mini_descendants)
    ancestors = staticmethod(_mini_ancestors)
    single_source_shortest_path_length = staticmethod(_mini_single_source_shortest_path_length)
    single_source_reachable = staticmethod(_mini_single_source_reachable)
    copy = staticmethod(_mini_copy)
    
    @staticmethod
    def nodes(G):
        return list(G.nodes) if hasattr(G, "nodes") else list(G.keys())
    
    @staticmethod
    def edges(G):
        return list(G.edges) if hasattr(G, "edges") else []


ALLOWED_IMPORT_MODULES = {
    'math', 'json', 'datetime', 'time', 'statistics', 're',
    'collections', 'itertools', 'functools', 'random', 'string',
    'decimal', 'fractions', 'hashlib', 'hmac', 'base64',
    'heapq', 'bisect', 'queue', 'copy', 'typing', 'enum',
    'dataclasses', 'csv', 'operator', 'pprint', 'networkx', 'nx'
}

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root_mod = name.split('.')[0]
    if root_mod not in ALLOWED_IMPORT_MODULES:
        raise ImportError(f"Import of module '{name}' is not allowed for security reasons.")
    if root_mod in ("networkx", "nx") and networkx is None:
        return _MiniNetworkXModule
    return __import__(name, globals, locals, fromlist, level)

SAFE_BUILTINS['__import__'] = _safe_import

SAFE_MODULES = {
    'math': math,
    'json': json,
    'datetime': datetime,
    'time': time,
    'statistics': statistics,
    're': re,
    'random': random,
    'collections': collections,
    'itertools': itertools,
    'functools': functools,
    'string': string,
    'decimal': decimal,
    'fractions': fractions,
    'hashlib': hashlib,
    'hmac': hmac,
    'base64': base64,
    'heapq': heapq,
    'bisect': bisect,
    'queue': queue,
    'copy': copy,
    'typing': typing,
    'enum': enum,
    'dataclasses': dataclasses,
    'csv': csv,
    'operator': operator,
    'pprint': pprint,
}
if networkx is not None:
    if not hasattr(networkx, "copy"):
        try:
            networkx.copy = _mini_copy
        except Exception:
            pass
    if not hasattr(networkx, "single_source_reachable"):
        try:
            networkx.single_source_reachable = _mini_single_source_reachable
        except Exception:
            pass

effective_nx = networkx if networkx is not None else _MiniNetworkXModule
SAFE_MODULES['networkx'] = effective_nx
SAFE_MODULES['nx'] = effective_nx


SAFE_DUNDER_ATTRS = {'__name__', '__doc__', '__len__', '__iter__', '__contains__', '__getitem__'}


def _check_code_safety(code: str) -> str | None:
    """Returns an error message if the code contains unsafe constructs, else None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        line = f" at line {exc.lineno}" if exc.lineno else ""
        return f"Error: Python syntax error{line}: {exc.msg}. Repair the code before execution."
    
    BLOCKED_NAMES = {
        'eval', 'exec', 'compile', 'open', 'getattr', 'setattr',
        'delattr', 'globals', 'locals', 'vars', 'dir', 'breakpoint',
        '__import__', 'type', 'chr',
    }
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            seen_literal_keys = set()
            for key in node.keys:
                if not isinstance(key, ast.Constant):
                    continue
                marker = (type(key.value).__name__, repr(key.value))
                if marker in seen_literal_keys:
                    line = f" at line {getattr(key, 'lineno', '?')}"
                    return (
                        "Error: Duplicate literal dictionary key"
                        f" {key.value!r}{line}. Remove the duplicate before execution."
                    )
                seen_literal_keys.add(marker)
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split('.')[0]
                if root_mod not in ALLOWED_IMPORT_MODULES:
                    return f"Error: Import of module '{alias.name}' is not allowed for security reasons."
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_mod = node.module.split('.')[0]
                if root_mod not in ALLOWED_IMPORT_MODULES:
                    return f"Error: Import from module '{node.module}' is not allowed for security reasons."
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") and node.attr not in SAFE_DUNDER_ATTRS:
                return f"Error: Access to private attribute '{node.attr}' is not allowed for security reasons."
            if node.attr == "sleep":
                return "Error: sleep is not allowed in the Python REPL."
        elif isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            return f"Error: Use of '{node.id}' is not allowed for security reasons."
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith('__') and node.value.endswith('__') and node.value not in SAFE_DUNDER_ATTRS:
                return f"Error: Dunder string '{node.value}' is not allowed for security reasons."
    return None

def _get_fresh_repl_globals() -> dict:
    return {
        "__builtins__": SAFE_BUILTINS,
        **SAFE_MODULES,
    }

_repl_globals = _get_fresh_repl_globals()
_repl_lock = threading.RLock()
_stdout_lock = threading.RLock()
REPL_TIMEOUT_SECONDS = 3.0
REPL_MAX_TRACE_EVENTS = 200_000


class ReplScope:
    """An isolated, persistent REPL namespace for a single agent session."""

    def __init__(self):
        self.globals = _get_fresh_repl_globals()
        self.lock = threading.RLock()

    def run(self, args: str) -> str:
        return _execute_repl(args, self.globals, self.lock)

    def reset(self) -> None:
        with self.lock:
            self.globals = _get_fresh_repl_globals()


def create_repl_scope() -> ReplScope:
    """Create a stateful namespace that is not shared with other sessions."""
    return ReplScope()

def get_repl_globals() -> dict:
    """Returns a view of current persistent REPL global variables."""
    return _repl_globals

def eval_in_repl(expr: str) -> Any:
    """Evaluates a data-only expression within the current REPL environment."""
    from tal.safe_eval import evaluate_expression
    return evaluate_expression(expr, _repl_globals)

def reset_repl_globals():
    """Clears the persistent REPL state to prevent accumulated bypasses."""
    global _repl_globals
    _repl_globals = _get_fresh_repl_globals()

def _sanitize_repl_code(code: str) -> str:
    """Cleans up common formatting artifacts emitted by SLMs in python_repl code."""
    c = code.strip()
    # Strip enclosing markdown code block fences if present
    m = re.match(r'^```(?:python)?\s*([\s\S]*?)\s*```$', c)
    if m:
        c = m.group(1).strip()

    # Strip outer wrapping triple quotes if the entire block was enclosed as a literal
    if (c.startswith('"""') and c.endswith('"""') and len(c) >= 6) or \
       (c.startswith("'''") and c.endswith("'''") and len(c) >= 6):
        inner = c[3:-3].strip()
        if "\n" in inner or any(kw in inner for kw in ("import ", "def ", "for ", "print(", "=", "if ")):
            c = inner

    # Strip unclosed or dangling trailing triple quote delimiters (e.g. `print(result)"""`)
    if c.endswith('"""') and c.count('"""') % 2 != 0 or c.endswith("'''") and c.count("'''") % 2 != 0:
        c = c[:-3].rstrip()

    # Strip unmatched trailing closing delimiters (e.g. `print(result)}` or `data = [1, 2]]`)
    while c.endswith("}") and c.count("{") < c.count("}"):
        c = c[:-1].rstrip()
    while c.endswith("]") and c.count("[") < c.count("]"):
        c = c[:-1].rstrip()
    while c.endswith(")") and c.count("(") < c.count(")"):
        c = c[:-1].rstrip()

    return c

def _execute_repl(args: str, repl_globals: dict, repl_lock: threading.RLock) -> str:
    """Execute code in one scope with a cooperative time and instruction budget."""
    try:
        if isinstance(args, dict):
            data = args
        else:
            try:
                data = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                # Try repairing via tal.repair if available
                try:
                    from tal.repair import repair_json_string
                    data = json.loads(repair_json_string(str(args)))
                except Exception:
                    # Fallback: If raw python code was passed directly instead of {"code": "..."}
                    s_args = str(args).strip()
                    if s_args and not s_args.startswith("{"):
                        data = {"code": s_args}
                    else:
                        raise

        code = data.get("code", "")
        if not code:
            return "Error: 'code' must be provided."

        code = _sanitize_repl_code(code)
            
        safety_error = _check_code_safety(code)
        if safety_error:
            return safety_error
            
        with repl_lock, _stdout_lock:
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = stdout_buffer = io.StringIO()
            sys.stderr = stderr_buffer = io.StringIO()
            started = time.monotonic()
            trace_events = 0
            old_trace = sys.gettrace()

            def watchdog(frame, event, arg):
                nonlocal trace_events
                if event == "line":
                    trace_events += 1
                    if trace_events > REPL_MAX_TRACE_EVENTS or time.monotonic() - started > REPL_TIMEOUT_SECONDS:
                        raise TimeoutError("REPL execution exceeded its resource limit")
                return watchdog

            try:
                sys.settrace(watchdog)
                exec(code, repl_globals)
            except Exception:
                traceback.print_exc()
            finally:
                sys.settrace(old_trace)
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            
        output = stdout_buffer.getvalue()
        err_output = stderr_buffer.getvalue()
        
        if err_output:
            output += f"\nSTDERR:\n{err_output}"
            
        if not output.strip():
            return "Code executed successfully (no output)."
            
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        return output
        
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"code\": \"...\"}"
    except Exception as e:
        return f"Error executing python REPL: {e}"


def python_repl(args: str) -> str:
    """Execute Python code in the backwards-compatible default REPL scope."""
    return _execute_repl(args, _repl_globals, _repl_lock)


EXTERNAL_TOOL_REGISTRY = {
    "web_search": web_search,
    "read_url": read_url,
    "run_command": run_command,
    "python_repl": python_repl,
}

EXTERNAL_TOOL_DESCRIPTIONS = '''
11. {"tool": "web_search", "args": "search query"}
   - Searches the web using Tavily Search API. Returns a summary and top results with URLs.
12. {"tool": "read_url", "args": "{\\"url\\": \\"https://example.com\\"}"}
   - Reads a webpage and extracts plain text. MUST pass JSON arguments.
13. {"tool": "run_command", "args": "{\\"command\\": \\"dir\\"}"}
   - Executes a shell command in the workspace directory. MUST pass JSON arguments.
   - Allowed commands: dir, echo, type, findstr, ping.
14. {"tool": "python_repl", "args": "{\\"code\\": \\"x = 5\\\\nprint(x)\\"}"}
   - Stateful Python REPL. Executes Python code and maintains global variables across turns. MUST pass JSON arguments.
   - IMPORTANT: Do NOT use input(). Hardcode all variable values directly. The REPL has no stdin.
'''
