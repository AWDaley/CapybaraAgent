import ast
import datetime
import json
import operator

from memory.knowledge_store import KnowledgeStore

# Persistent fact storage
_knowledge_store = KnowledgeStore()

def safe_pow(base, exp):
    if exp > 1000:
        raise ValueError("Exponent too large (max 1000)")
    return base ** exp

# Safe operators for the calculator
_SAFE_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: safe_pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_SAFE_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_SAFE_FUNCTIONS = {"abs": abs, "round": round, "min": min, "max": max}

def _safe_eval_node(node):
    """Recursively evaluate an AST node with only safe math operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINARY_OPS:
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        return _SAFE_BINARY_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY_OPS:
        return _SAFE_UNARY_OPS[type(node.op)](_safe_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        func_name = node.func.id
        if func_name in _SAFE_FUNCTIONS:
            args = [_safe_eval_node(arg) for arg in node.args]
            return _SAFE_FUNCTIONS[func_name](*args)
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")

def calculator(args: str) -> str:
    """Evaluates a mathematical expression safely using AST parsing. Expects JSON args."""
    try:
        data = json.loads(args)
        expression = data.get("expression", "")
        if not expression:
            return "Error: 'expression' must be provided."
        tree = ast.parse(expression.strip(), mode='eval')
        result = _safe_eval_node(tree)
        return str(result)
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"expression\": \"...\"}"
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as e:
        return f"Error calculating '{expression if 'expression' in locals() else args}': {e}"

def get_time(args: str = "") -> str:
    """Returns the current local time."""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")



def count_words(args: str) -> str:
    """Counts the number of words in a string. Expects JSON args."""
    try:
        data = json.loads(args)
        text = data.get("text", "")
        if not text:
            return "Error: 'text' must be provided."
        words = text.split()
        return f"The text contains {len(words)} words."
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"text\": \"...\"}"

def convert_units(args: str) -> str:
    """Simple unit converter. Expects format like '100 km to miles'. Expects JSON args."""
    try:
        data = json.loads(args)
        query = data.get("query", "")
        if not query:
            return "Error: 'query' must be provided."
            
        parts = query.strip().split()
        if len(parts) != 4 or parts[2].lower() != "to":
            return "Error: format must be 'value unit1 to unit2' (e.g. 100 km to miles)"
            
        value = float(parts[0])
        unit1 = parts[1].lower()
        unit2 = parts[3].lower()
        
        # Simple hardcoded conversions
        conversions = {
            ("km", "miles"): value * 0.621371,
            ("miles", "km"): value * 1.60934,
            ("kg", "lbs"): value * 2.20462,
            ("lbs", "kg"): value / 2.20462,
            ("c", "f"): (value * 9/5) + 32,
            ("f", "c"): (value - 32) * 5/9,
            ("cm", "inches"): value * 0.393701,
            ("inches", "cm"): value * 2.54,
        }
        
        result = conversions.get((unit1, unit2))
        if result is None:
            return f"Error: Conversion from {unit1} to {unit2} not supported."
            
        return f"{value} {unit1} is equal to {result:.2f} {unit2}"
    except json.JSONDecodeError:
        return "Error: Arguments must be valid JSON: {\"query\": \"...\"}"
    except ValueError:
        return "Error: Invalid number format."
    except Exception as e:
        return f"Error converting units: {e}"

def get_help(args: str = "") -> str:
    """Returns a list of available commands."""
    return (
        "Available commands:\n"
        "- calc [expression]: Calculate math (e.g., calc 2 + 2)\n"
        "- time: Get the current time\n"
        "- count words [text]: Count words in a string\n"
        "- convert units [value unit1 to unit2]: Convert units\n"
        "- remember [json]: Save a persistent fact\n"
        "- recall [json]: Recall a persistent fact\n"
        "- help: Show this message\n"
        "- exit or quit: Stop the agent"
    )

def remember_to_store(store: KnowledgeStore, args: str) -> str:
    """Write a fact to the explicitly bound session store."""
    try:
        data = json.loads(args)
        key = data.get("key", "")
        value = data.get("value", "")
        if not key or not value:
            return "Error: Both 'key' and 'value' must be provided."
        return store.save_fact(key, value)
    except json.JSONDecodeError:
        return 'Error: Arguments must be valid JSON: {"key": "...", "value": "..."}'
    except Exception as exc:
        return f"Error remembering fact: {exc}"


def recall_from_store(store: KnowledgeStore, args: str = "") -> str:
    """Read facts exclusively from the supplied session store."""
    try:
        data = json.loads(args) if args and args.strip() else {}
        key = data.get("key", "")
        if not key:
            facts = store.get_all_facts()
            if not facts:
                return "I don't remember any facts yet."
            return "All remembered facts:\n" + "\n".join(
                f"- {name}: {value}" for name, value in facts.items()
            )
        return store.get_fact(key)
    except json.JSONDecodeError:
        return 'Error: Arguments must be valid JSON: {"key": "..."}'
    except Exception as exc:
        return f"Error recalling fact: {exc}"


def remember(args: str) -> str:
    """Legacy CLI storage; web agents bind to private session stores."""
    return remember_to_store(_knowledge_store, args)


def recall(args: str = "") -> str:
    """Legacy CLI storage; web agents bind to private session stores."""
    return recall_from_store(_knowledge_store, args)


BASIC_TOOL_REGISTRY = {
    "calc": calculator,
    "time": get_time,
    "count words": count_words,
    "convert units": convert_units,
    "remember": remember,
    "recall": recall,
    "help": get_help
}

BASIC_TOOL_DESCRIPTIONS = '''
1. {"tool": "calc", "args": "{\\"expression\\": \\"2 + 2\\"}"}
   - Evaluates a mathematical expression. MUST pass JSON arguments.
2. {"tool": "time", "args": "{}"}
   - Returns the current local time. MUST pass empty JSON arguments.
3. {"tool": "count words", "args": "{\\"text\\": \\"hello world\\"}"}
   - Counts the number of words in a string. MUST pass JSON arguments.
4. {"tool": "convert units", "args": "{\\"query\\": \\"100 km to miles\\"}"}
   - Converts units. Supported: km/miles, kg/lbs, c/f, cm/inches. MUST pass JSON arguments.
5. {"tool": "remember", "args": "{\\"key\\": \\"fact_name\\", \\"value\\": \\"fact_content\\"}"}
   - Saves a persistent fact that you will remember across sessions. MUST pass JSON arguments.
6. {"tool": "recall", "args": "{\\"key\\": \\"fact_name\\"}"}
   - Retrieves a persistent fact. Leave args empty to recall all facts. MUST pass JSON arguments.
7. {"tool": "help", "args": "{}"}
   - Returns a list of available commands. MUST pass empty JSON arguments.
'''
