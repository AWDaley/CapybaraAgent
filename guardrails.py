from collections.abc import Callable

from tal.effect_classes import (
    ApprovalPolicy,
    get_approval_policy,
)

# Legacy tier mapping preserved for 100% backward compatibility
TOOL_SAFETY = {
    # SAFE: Auto-execute, no confirmation needed (sandboxed in workspace)
    "calc": "safe",
    "time": "safe",
    "help": "safe",
    "read notes": "safe",
    "count words": "safe",
    "convert units": "safe",
    "recall": "safe",
    "read_file": "safe",
    "list_files": "safe",
    "write_file": "safe",
    
    # MODERATE: Execute but log a notice
    "note": "moderate",
    "remember": "dangerous",
    "web_search": "moderate",
    "read_url": "moderate",
    
    # DANGEROUS: Require explicit user confirmation
    "run_command": "dangerous",
    "python_repl": "dangerous",
}


def get_safety_tier(tool_name: str, tal_mode: bool = False) -> str:
    """Returns the safety tier of a tool. Unknown tools default to dangerous."""
    if tal_mode:
        policy = get_approval_policy(tool_name)
        if policy == ApprovalPolicy.AUTO:
            return "safe"
        elif policy == ApprovalPolicy.LOG:
            return "moderate"
        else:
            return "dangerous"
    return TOOL_SAFETY.get(tool_name, "dangerous")


def request_confirmation(tool_name: str, tool_args: str, approval_callback: Callable | None = None) -> bool:
    """
    Prompts the user for confirmation before executing a dangerous tool.
    Returns True if approved, False if denied.
    """
    if approval_callback:
        return approval_callback(tool_name, tool_args)

    is_truncated = len(tool_args) > 50
    display_args = tool_args[:50] + ('... [enter "details" to see full args]' if is_truncated else '')
    print(f"\n⚠️  CONFIRMATION REQUIRED: {tool_name}('{display_args}')")
    
    while True:
        choice = input("   Allow this action? (y/n/details): ").strip().lower()
        if choice in ('y', 'yes'):
            return True
        elif choice in ('n', 'no'):
            return False
        elif choice == 'details':
            print("\n   --- Tool Details ---")
            print(f"   Tool: {tool_name}")
            print(f"   Args: {tool_args}")
            print("   --------------------")
        else:
            print("   Please enter 'y', 'n', or 'details'.")
