from enum import Enum


class EffectClass(Enum):
    READ = "read"             # Side-effect free (e.g. read_file, calc)
    WRITE = "write"           # Local filesystem / memory mutations (e.g. write_file)
    EXEC = "exec"             # Subprocess execution, REPL execution (e.g. run_command, python_repl)
    NETWORK = "network"       # Outbound network requests (e.g. web_search, read_url)
    DESTRUCTIVE = "destruct"  # Irreversible or dangerous operations, default for unknown tools


class ApprovalPolicy(Enum):
    AUTO = "auto"             # Auto-execute without confirmation
    LOG = "log"               # Auto-execute with structured logging
    CONFIRM = "confirm"       # Requires explicit user confirmation / HITL approval


EFFECT_APPROVAL_MAP: dict[EffectClass, ApprovalPolicy] = {
    EffectClass.READ: ApprovalPolicy.AUTO,
    EffectClass.WRITE: ApprovalPolicy.CONFIRM,
    EffectClass.EXEC: ApprovalPolicy.CONFIRM,
    EffectClass.NETWORK: ApprovalPolicy.LOG,
    EffectClass.DESTRUCTIVE: ApprovalPolicy.CONFIRM,
}


TOOL_EFFECTS: dict[str, EffectClass] = {
    "calc": EffectClass.READ,
    "time": EffectClass.READ,
    "help": EffectClass.READ,
    "read notes": EffectClass.READ,
    "count words": EffectClass.READ,
    "convert units": EffectClass.READ,
    "recall": EffectClass.READ,
    "read_file": EffectClass.READ,
    "list_files": EffectClass.READ,
    "note": EffectClass.WRITE,
    "remember": EffectClass.WRITE,
    "web_search": EffectClass.NETWORK,
    "read_url": EffectClass.NETWORK,
    "write_file": EffectClass.WRITE,
    "run_command": EffectClass.EXEC,
    "python_repl": EffectClass.EXEC,
}

# Individual policy overrides when effect class alone needs nuance.  Writes
# intentionally have no auto-execute override: user approval is the default.
TOOL_APPROVAL_OVERRIDES: dict[str, ApprovalPolicy] = {}


def get_effect_class(tool_name: str) -> EffectClass:
    """Returns the effect class of a tool. Unknown tools default to DESTRUCTIVE."""
    return TOOL_EFFECTS.get(tool_name, EffectClass.DESTRUCTIVE)


def get_approval_policy(tool_name: str) -> ApprovalPolicy:
    """Returns whether the tool requires AUTO execution, LOGGING, or CONFIRMATION."""
    if tool_name in TOOL_APPROVAL_OVERRIDES:
        return TOOL_APPROVAL_OVERRIDES[tool_name]
    effect = get_effect_class(tool_name)
    return EFFECT_APPROVAL_MAP.get(effect, ApprovalPolicy.CONFIRM)
