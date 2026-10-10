from guardrails import get_safety_tier
from tal.effect_classes import (
    ApprovalPolicy,
    EffectClass,
    get_approval_policy,
    get_effect_class,
)


def test_tool_effect_classification():
    assert get_effect_class("calc") == EffectClass.READ
    assert get_effect_class("read_file") == EffectClass.READ
    assert get_effect_class("list_files") == EffectClass.READ
    assert get_effect_class("write_file") == EffectClass.WRITE
    assert get_effect_class("remember") == EffectClass.WRITE
    assert get_effect_class("web_search") == EffectClass.NETWORK
    assert get_effect_class("read_url") == EffectClass.NETWORK
    assert get_effect_class("run_command") == EffectClass.EXEC
    assert get_effect_class("python_repl") == EffectClass.EXEC


def test_unknown_tool_defaults_destructive():
    assert get_effect_class("format_hard_drive") == EffectClass.DESTRUCTIVE
    assert get_approval_policy("format_hard_drive") == ApprovalPolicy.CONFIRM


def test_approval_policies():
    assert get_approval_policy("calc") == ApprovalPolicy.AUTO
    assert get_approval_policy("read_file") == ApprovalPolicy.AUTO
    assert get_approval_policy("write_file") == ApprovalPolicy.CONFIRM
    assert get_approval_policy("remember") == ApprovalPolicy.CONFIRM
    assert get_approval_policy("run_command") == ApprovalPolicy.CONFIRM
    assert get_approval_policy("python_repl") == ApprovalPolicy.CONFIRM


def test_guardrails_bridge():
    assert get_safety_tier("calc", tal_mode=True) == "safe"
    assert get_safety_tier("write_file", tal_mode=True) == "dangerous"
    assert get_safety_tier("remember", tal_mode=True) == "dangerous"
    assert get_safety_tier("run_command", tal_mode=True) == "dangerous"
    assert get_safety_tier("unknown_tool", tal_mode=True) == "dangerous"
