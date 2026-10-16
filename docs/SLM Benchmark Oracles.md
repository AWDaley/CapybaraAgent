# SLM benchmark acceptance oracles

The `acceptance` field in the v1 suite is an explanatory sentence, **not**
an executable success condition. Historically, success reporting could confuse
agent-returned text or optional internal acceptance events with independently
verified completion. That would misrepresent the impact of TAL.

A case may now declare a closed `oracle` with:
- `final_contains_all`: nonempty expected substrings in the final answer.
- `tool_observations`: required tool names and substrings in **actual tool
  results**, rather than model claims that the tool ran.

Both baseline ReAct and TAL use the **same oracle** after their trials. Each
trial records `baseline_oracle_passed` and `tal_oracle_passed` as booleans
only when a machine-checkable oracle exists. Otherwise they are `null`,
and the case is excluded from the verified-success denominator. The scorecard
shows oracle coverage and counts of scored versus unscored cases.

The current suite has an independent oracle for the calculator case. The
stateful Python and distributed saga cases still require richer controlled
state and artifact acceptance adapters before they can be scored. Adding
a seemingly successful model final answer is **not** a substitute.

The scorecard also preserves **agent-reported verification** as a separate
diagnostic metric; it is never substituted for the independent oracle rate.
These oracles are intentionally narrow. They verify the specified conditions,
not universal semantic correctness. Hold out evaluation tasks, capture tool
versions/inputs and device details, and report confidence intervals before
claiming TAL capability improvements.
