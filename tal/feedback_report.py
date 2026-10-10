import datetime
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TALFeedbackReport:
    """Telemetry and evaluation feedback report generated for a normal TAL execution turn/session."""
    prompt: str = ""
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    mode: str = "react"                      # react | planning | multi-agent
    model: str = "unknown"
    provider: str = "unknown"
    final_answer: str = ""
    success: bool = True
    error: str | None = None
    duration_seconds: float = 0.0
    steps_taken: int = 0
    max_steps: int = 10
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_count: int = 0
    tool_error_count: int = 0
    thoughts: list[str] = field(default_factory=list)
    parse_repairs: int = 0
    protocol_error_count: int = 0
    gate_blocks: int = 0
    gate_block_details: list[dict[str, Any]] = field(default_factory=list)
    epistemic_fact_count: int = 0
    epistemic_facts: list[dict[str, Any]] = field(default_factory=list)
    verification_passed: bool | None = None
    verification_messages: list[str] = field(default_factory=list)
    events_count: int = 0
    health_score: int = 100
    health_rating: str = "Optimal"
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TALFeedbackReport":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def compute_health_score(report: TALFeedbackReport) -> tuple[int, str, list[str]]:
    """
    Computes an objective execution health score (0-100), rating, and actionable diagnosis tips.
    """
    score = 100
    recommendations = []

    # Deduct for hard failure or unhandled errors
    if not report.success or report.error:
        score -= 40
        recommendations.append(f"Execution encountered an error: {report.error}")

    # Deduct for verification failures
    if report.verification_passed is False:
        score -= 25
        recommendations.append("Deterministic acceptance criteria failed (one or more expected files/assertions missing).")

    # Deduct for tool execution errors
    actual_tool_errors = report.tool_error_count
    if actual_tool_errors == 0 and report.tool_calls:
        for tc in report.tool_calls:
            res = str(tc.get("result", "")).strip().lower()
            if res.startswith("error:") or "syntaxerror" in res:
                actual_tool_errors += 1

    if actual_tool_errors > 0:
        penalty = min(actual_tool_errors * 10, 20)
        score -= penalty
        recommendations.append(f"{actual_tool_errors} tool call(s) failed during execution.")

    # Deduct for excessive step budget consumption
    if report.max_steps > 0:
        step_ratio = report.steps_taken / report.max_steps
        if step_ratio >= 0.9:
            score -= 10
            recommendations.append(f"Step budget nearly exhausted ({report.steps_taken}/{report.max_steps} steps used).")

    # Deduct for high parse repairs
    if report.parse_repairs > 2:
        score -= 5
        recommendations.append(f"Model output required {report.parse_repairs} syntax repairs.")

    if report.protocol_error_count:
        penalty = min(report.protocol_error_count * 5, 15)
        score -= penalty
        recommendations.append(f"{report.protocol_error_count} model proposal(s) violated the TAL response schema.")

    if report.duration_seconds > 900:
        score -= 15
        recommendations.append(f"Execution latency was excessive ({report.duration_seconds:.1f}s).")
    elif report.duration_seconds > 300:
        score -= 8
        recommendations.append(f"Execution latency exceeded the normal turn budget ({report.duration_seconds:.1f}s).")

    if report.input_tokens > 10_000 and report.steps_taken <= 2:
        score -= 8
        recommendations.append("Input context was disproportionately large for the amount of completed work.")

    score = max(0, min(100, score))

    if score >= 90:
        rating = "Optimal"
    elif score >= 75:
        rating = "Good"
    elif score >= 50:
        rating = "Needs Optimization"
    else:
        rating = "Critical Failure"

    if not recommendations:
        recommendations.append("All operations executed cleanly with zero tool errors and full verification pass.")

    return score, rating, recommendations


def format_feedback_card(report: TALFeedbackReport) -> str:
    """
    Renders an ASCII performance summary card for terminal output.
    """
    width = 74
    lines = []
    lines.append("┌" + "─" * (width - 2) + "┐")
    title = f"  📊 TAL PERFORMANCE FEEDBACK REPORT [{report.mode.upper()}]  "
    lines.append(f"│{title.center(width - 2)}│")
    lines.append("├" + "─" * (width - 2) + "┤")
    
    # Model & Timing
    model_info = f" Model: {report.provider}/{report.model}"
    timing_info = f"Time: {report.duration_seconds:.1f}s | Steps: {report.steps_taken}/{report.max_steps} "
    lines.append(f"│{model_info:<{width // 2 - 1}}{timing_info:>{width // 2 - 1}}│")

    # Tokens & LLM Calls
    tok_info = f" Tokens: {report.total_tokens:,} (in: {report.input_tokens:,} | out: {report.output_tokens:,})"
    llm_info = f"LLM Calls: {report.llm_calls} "
    lines.append(f"│{tok_info:<{width - len(llm_info) - 2}}{llm_info}│")

    lines.append("├" + "─" * (width - 2) + "┤")

    # Tool Execution
    tool_names = [tc.get("tool", "unknown") for tc in report.tool_calls]
    tool_summary = f" Tools ({report.tool_call_count}): {', '.join(tool_names) if tool_names else 'None'}"
    if len(tool_summary) > width - 4:
        tool_summary = tool_summary[:width - 7] + "..."
    lines.append(f"│{tool_summary:<{width - 2}}│")
    
    tool_status = f" Tool Errors: {report.tool_error_count} | Gate Blocks: {report.gate_blocks} | Repairs: {report.parse_repairs}"
    lines.append(f"│{tool_status:<{width - 2}}│")

    # Epistemic & Verification
    if report.verification_passed is True:
        v_str = "✅ Passed"
    elif report.verification_passed is False:
        v_str = "❌ Failed"
    else:
        v_str = "➖ N/A"

    epi_v_str = f" Epistemic Facts: {report.epistemic_fact_count} | Verification: {v_str} | Events: {report.events_count}"
    lines.append(f"│{epi_v_str:<{width - 2}}│")

    lines.append("├" + "─" * (width - 2) + "┤")

    # Health Score & Grade
    score_str = f" Execution Health: {report.health_score}/100 ({report.health_rating})"
    lines.append(f"│{score_str:<{width - 2}}│")

    # Primary recommendation
    if report.recommendations:
        rec_str = f" Note: {report.recommendations[0]}"
        if len(rec_str) > width - 4:
            rec_str = rec_str[:width - 7] + "..."
        lines.append(f"│{rec_str:<{width - 2}}│")

    lines.append("└" + "─" * (width - 2) + "┘")
    return "\n".join(lines)


def format_markdown_report(report: TALFeedbackReport) -> str:
    """
    Renders a formatted Markdown report file for persistent evaluation logs.
    """
    v_str = "✅ Passed" if report.verification_passed is True else ("❌ Failed" if report.verification_passed is False else "N/A")
    status_str = "✅ Success" if report.success else f"❌ Failed ({report.error})"

    recs_formatted = "\n".join(f"- {r}" for r in report.recommendations)

    tools_table = ""
    if report.tool_calls:
        tool_rows = []
        for i, tc in enumerate(report.tool_calls, 1):
            t_name = tc.get("tool", "unknown")
            t_args = str(tc.get("args", ""))
            if len(t_args) > 60:
                t_args = t_args[:57] + "..."
            t_res = str(tc.get("result", "ok"))
            if len(t_res) > 60:
                t_res = t_res[:57] + "..."
            tool_rows.append(f"| {i} | `{t_name}` | `{t_args}` | {t_res} |")
        tools_table = "\n### Tool Execution Log\n| # | Tool | Arguments | Result Summary |\n|---|---|---|---|\n" + "\n".join(tool_rows) + "\n"

    md = f"""# TAL Performance Feedback Report

- **Task Prompt:** {report.prompt}
- **Timestamp:** `{report.timestamp}`
- **Execution Mode:** `{report.mode.upper()}`
- **Model / Provider:** `{report.provider}/{report.model}`
- **Health Grade:** **{report.health_score}/100 ({report.health_rating})**

---

## 1. Executive Performance Metrics

| Metric | Measured Value | Benchmark Context |
| :--- | :--- | :--- |
| **Execution Status** | {status_str} | Overall run status |
| **Wall-Clock Duration** | `{report.duration_seconds:.2f}s` | Total latency |
| **Step Budget Used** | `{report.steps_taken} / {report.max_steps}` steps | Budget consumption |
| **LLM Generations** | `{report.llm_calls}` calls | Model turns |
| **Tokens Consumed** | `{report.total_tokens:,}` total (`{report.input_tokens:,}` in / `{report.output_tokens:,}` out) | Token efficiency |
| **Tool Invocations** | `{report.tool_call_count}` calls (`{report.tool_error_count}` errors) | Tool execution reliability |
| **Epistemic Facts Tracked** | `{report.epistemic_fact_count}` facts | Belief state store |
| **Action Gate Interventions** | `{report.gate_blocks}` blocked | Policy enforcement |
| **Output Parse Repairs** | `{report.parse_repairs}` repairs | Syntax resilience |
| **Proposal Protocol Errors** | `{report.protocol_error_count}` errors | Structured-output reliability |
| **Acceptance Verification** | {v_str} | Deterministic verification |
| **Audit Events Logged** | `{report.events_count}` events | Event sourcing trace |

---

## 2. Diagnostics & Recommendations

{recs_formatted}
{tools_table}
---

## 3. Final Agent Response

```
{report.final_answer.strip() if report.final_answer else "(No answer output)"}
```
"""
    return md


def save_feedback_report(report: TALFeedbackReport, storage_dir: str = "data/tal_reports") -> tuple[str, str]:
    """
    Saves the feedback report as both a structured JSON file and a Markdown summary.
    Returns (json_path, md_path).
    """
    # Find project root if storage_dir is relative
    if not os.path.isabs(storage_dir):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        storage_dir = os.path.join(base_dir, storage_dir)

    os.makedirs(storage_dir, exist_ok=True)
    
    # Generate timestamp filename
    ts_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    json_filename = f"report_{ts_str}.json"
    md_filename = f"report_{ts_str}.md"
    
    json_path = os.path.join(storage_dir, json_filename)
    md_path = os.path.join(storage_dir, md_filename)
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
        
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_markdown_report(report))
        
    return json_path, md_path
