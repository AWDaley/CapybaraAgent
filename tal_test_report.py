import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RunMetrics:
    """Telemetry data collected from a single agent run (with or without TAL)."""
    mode: str = "react"                      # react | planning | multi-agent
    tal_enabled: bool = False
    final_answer: str = ""
    success: bool = True
    error: str | None = None
    steps_taken: int = 0
    wall_clock_time: float = 0.0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tools_called: list[dict[str, Any]] = field(default_factory=list)
    tool_call_count: int = 0
    tool_error_count: int = 0
    thoughts: list[str] = field(default_factory=list)
    parse_repairs: int = 0
    gate_blocks: int = 0
    gate_block_details: list[dict[str, Any]] = field(default_factory=list)
    epistemic_fact_count: int = 0
    epistemic_facts: list[dict[str, Any]] = field(default_factory=list)
    verification_passed: bool | None = None
    verification_messages: list[str] = field(default_factory=list)
    events_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunMetrics":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TALTestResult:
    """Paired comparison of a baseline run vs TAL run for a single prompt."""
    prompt: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    mode: str = "react"
    model: str = "unknown"
    provider: str = "unknown"
    baseline: RunMetrics = field(default_factory=RunMetrics)
    tal: RunMetrics = field(default_factory=RunMetrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "model": self.model,
            "provider": self.provider,
            "baseline": self.baseline.to_dict(),
            "tal": self.tal.to_dict(),
            "diffs": self.get_diffs(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TALTestResult":
        return cls(
            prompt=data.get("prompt", ""),
            timestamp=data.get("timestamp", datetime.datetime.now().isoformat()),
            mode=data.get("mode", "react"),
            model=data.get("model", "unknown"),
            provider=data.get("provider", "unknown"),
            baseline=RunMetrics.from_dict(data.get("baseline", {})),
            tal=RunMetrics.from_dict(data.get("tal", {})),
        )

    def get_diffs(self) -> dict[str, Any]:
        """Calculates differences between Baseline and TAL (positive/negative impact)."""
        b = self.baseline
        t = self.tal

        def calc_pct(b_val, t_val):
            if b_val == 0:
                return 0.0 if t_val == 0 else 100.0
            return round(((t_val - b_val) / b_val) * 100, 1)

        return {
            "steps_diff": t.steps_taken - b.steps_taken,
            "steps_diff_pct": calc_pct(b.steps_taken, t.steps_taken),
            "time_diff_sec": round(t.wall_clock_time - b.wall_clock_time, 3),
            "time_diff_pct": calc_pct(b.wall_clock_time, t.wall_clock_time),
            "tokens_diff": t.total_tokens - b.total_tokens,
            "tokens_diff_pct": calc_pct(b.total_tokens, t.total_tokens),
            "tool_calls_diff": t.tool_call_count - b.tool_call_count,
            "tool_errors_diff": t.tool_error_count - b.tool_error_count,
            "gate_interventions": t.gate_blocks,
            "epistemic_facts_gained": t.epistemic_fact_count,
            "verification_passed": t.verification_passed,
        }


def format_comparison_table(result: TALTestResult) -> str:
    """Generates an ASCII comparison table of baseline vs TAL metrics."""
    b = result.baseline
    t = result.tal
    diffs = result.get_diffs()

    # Step indicator
    if diffs["steps_diff"] < 0:
        step_indicator = f"✅ ({diffs['steps_diff']})"
    elif diffs["steps_diff"] > 0:
        step_indicator = f"⚠️ (+{diffs['steps_diff']})"
    else:
        step_indicator = "➖ (same)"

    # Time indicator
    time_sign = "+" if diffs["time_diff_sec"] > 0 else ""
    time_indicator = f"({time_sign}{diffs['time_diff_sec']}s / {diffs['time_diff_pct']:+}%)"

    # Token indicator
    tok_sign = "+" if diffs["tokens_diff"] > 0 else ""
    token_indicator = f"({tok_sign}{diffs['tokens_diff']} / {diffs['tokens_diff_pct']:+}%)"

    # Tool error indicator
    if t.tool_error_count < b.tool_error_count:
        err_indicator = "✅ (improved)"
    elif t.tool_error_count > b.tool_error_count:
        err_indicator = "⚠️ (more errors)"
    else:
        err_indicator = "➖ (same)"

    # Verification string
    if t.verification_passed is True:
        v_str = "✅ Passed"
    elif t.verification_passed is False:
        v_str = "❌ Failed"
    else:
        v_str = "N/A (no criteria)"

    lines = []
    width = 76
    lines.append("=" * width)
    lines.append("  TAL TEST MODE — A/B EFFECTIVENESS REPORT")
    lines.append("=" * width)
    lines.append(f"Prompt:   {result.prompt}")
    lines.append(f"Mode:     {result.mode.upper()}  |  Provider: {result.provider}  |  Model: {result.model}")
    lines.append(f"Date:     {result.timestamp}")
    lines.append("-" * width)
    lines.append(f"{'Metric':<26} | {'Baseline (No TAL)':<20} | {'TAL Mode':<24}")
    lines.append("-" * width)
    lines.append(f"{'Execution Status':<26} | {('✅ Success' if b.success else '❌ Error'):<20} | {('✅ Success' if t.success else '❌ Error'):<24}")
    lines.append(f"{'Steps Taken':<26} | {b.steps_taken!s:<20} | {f'{t.steps_taken} {step_indicator}':<24}")
    lines.append(f"{'Wall-Clock Time':<26} | {f'{b.wall_clock_time:.2f}s':<20} | {f'{t.wall_clock_time:.2f}s {time_indicator}':<24}")
    lines.append(f"{'LLM Calls':<26} | {b.llm_calls!s:<20} | {t.llm_calls!s:<24}")
    lines.append(f"{'Tokens (In / Out / Tot)':<26} | {f'{b.input_tokens}/{b.output_tokens}/{b.total_tokens}':<20} | {f'{t.input_tokens}/{t.output_tokens}/{t.total_tokens} {token_indicator}':<24}")
    lines.append(f"{'Tool Calls (Total)':<26} | {b.tool_call_count!s:<20} | {t.tool_call_count!s:<24}")
    lines.append(f"{'Tool Errors':<26} | {b.tool_error_count!s:<20} | {f'{t.tool_error_count} {err_indicator}':<24}")
    lines.append(f"{'Action Gate Blocks':<26} | {'N/A':<20} | {t.gate_blocks!s:<24}")
    lines.append(f"{'Output Parse Repairs':<26} | {b.parse_repairs!s:<20} | {t.parse_repairs!s:<24}")
    lines.append(f"{'Epistemic Facts Tracked':<26} | {'N/A':<20} | {t.epistemic_fact_count!s:<24}")
    lines.append(f"{'Verification Result':<26} | {'N/A':<20} | {v_str:<24}")
    lines.append(f"{'Event Log Entries':<26} | {'N/A':<20} | {t.events_count!s:<24}")
    lines.append("-" * width)

    # Tools detailed breakdown
    if b.tools_called or t.tools_called:
        lines.append("TOOL USAGE BREAKDOWN:")
        b_tool_names = [tc.get("tool", "unknown") for tc in b.tools_called]
        t_tool_names = [tc.get("tool", "unknown") for tc in t.tools_called]
        lines.append(f"  Baseline Tools : {', '.join(b_tool_names) if b_tool_names else 'None'}")
        lines.append(f"  TAL Tools      : {', '.join(t_tool_names) if t_tool_names else 'None'}")
        lines.append("-" * width)

    # Gate block details
    if t.gate_block_details:
        lines.append("ACTION GATE INTERVENTIONS:")
        for blk in t.gate_block_details:
            lines.append(f"  🚫 Tool '{blk.get('tool')}': [{blk.get('stage')}] {blk.get('reason')}")
        lines.append("-" * width)

    # Final Answers
    lines.append("FINAL ANSWERS:")
    lines.append("\n[BASELINE ANSWER]:")
    b_ans = b.final_answer.strip() if b.final_answer else "(No answer produced / Error)"
    lines.append(f"  {b_ans}")

    lines.append("\n[TAL ANSWER]:")
    t_ans = t.final_answer.strip() if t.final_answer else "(No answer produced / Error)"
    lines.append(f"  {t_ans}")
    lines.append("=" * width)

    return "\n".join(lines)


def format_batch_summary(results: list[TALTestResult]) -> str:
    """Generates an aggregated summary report across multiple test prompts."""
    if not results:
        return "No test results to summarize."

    total = len(results)
    tal_fewer_steps = sum(1 for r in results if r.get_diffs()["steps_diff"] < 0)
    tal_more_steps = sum(1 for r in results if r.get_diffs()["steps_diff"] > 0)
    same_steps = total - tal_fewer_steps - tal_more_steps

    tal_fewer_errors = sum(1 for r in results if r.get_diffs()["tool_errors_diff"] < 0)
    tal_more_errors = sum(1 for r in results if r.get_diffs()["tool_errors_diff"] > 0)
    same_errors = total - tal_fewer_errors - tal_more_errors

    tal_fewer_tokens = sum(1 for r in results if r.get_diffs()["tokens_diff"] < 0)
    tal_more_tokens = sum(1 for r in results if r.get_diffs()["tokens_diff"] > 0)

    total_gate_blocks = sum(r.tal.gate_blocks for r in results)
    total_facts = sum(r.tal.epistemic_fact_count for r in results)

    avg_b_time = sum(r.baseline.wall_clock_time for r in results) / total
    avg_t_time = sum(r.tal.wall_clock_time for r in results) / total
    avg_b_tokens = sum(r.baseline.total_tokens for r in results) / total
    avg_t_tokens = sum(r.tal.total_tokens for r in results) / total

    lines = []
    width = 76
    lines.append("=" * width)
    lines.append(f"  TAL TEST MODE — BATCH SUMMARY ({total} PROMPTS)")
    lines.append("=" * width)
    lines.append(f"{'Category':<32} | {'Result':<40}")
    lines.append("-" * width)
    lines.append(f"{'Step Efficiency (TAL vs Base)':<32} | {f'{tal_fewer_steps} fewer / {same_steps} same / {tal_more_steps} more'}")
    lines.append(f"{'Error Reduction (TAL vs Base)':<32} | {f'{tal_fewer_errors} fewer / {same_errors} same / {tal_more_errors} more'}")
    lines.append(f"{'Token Overhead (TAL vs Base)':<32} | {f'{tal_fewer_tokens} fewer / {tal_more_tokens} more'}")
    lines.append(f"{'Avg Wall-Clock Time':<32} | {f'Baseline: {avg_b_time:.2f}s  |  TAL: {avg_t_time:.2f}s'}")
    lines.append(f"{'Avg Total Tokens':<32} | {f'Baseline: {avg_b_tokens:.0f}  |  TAL: {avg_t_tokens:.0f}'}")
    lines.append(f"{'Total Gate Interventions':<32} | {f'{total_gate_blocks} blocked actions'}")
    lines.append(f"{'Total Epistemic Facts':<32} | {f'{total_facts} structured facts tracked'}")
    lines.append("=" * width)

    return "\n".join(lines)


def save_test_result(result: TALTestResult, storage_dir: str | None = None) -> str:
    """Saves a single test result to a JSON file."""
    base_dir = storage_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tal_tests")
    os.makedirs(base_dir, exist_ok=True)

    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"test_{timestamp_str}.json"
    filepath = os.path.join(base_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    return filepath


def save_batch_result(results: list[TALTestResult], storage_dir: str | None = None) -> str:
    """Saves a batch of test results to a JSON file."""
    base_dir = storage_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tal_tests")
    os.makedirs(base_dir, exist_ok=True)

    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"batch_{timestamp_str}.json"
    filepath = os.path.join(base_dir, filename)

    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total_prompts": len(results),
        "results": [r.to_dict() for r in results]
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return filepath
