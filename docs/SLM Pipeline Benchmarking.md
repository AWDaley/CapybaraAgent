# Fixed-pipeline SLM evaluation (suite v3)

Use `benchmarks/slm_v3.json` for task suites with fixed structured pipelines.
The `pipeline_fixture` field is a checked-in `data/<basename>.json` path.
The evaluator does **not** permit model-generated pipeline definitions or
arbitrary absolute/local paths. The same pipeline graph, tool registry, and
independent acceptance checks run in both the baseline and TAL arms.

The pipeline runner permits only local, deterministic tools
(`calc`, `read_file`, `list_files`, etc.) and a predeclared deterministic
file materializer. Requests for model-driven host subprocesses, network
capabilities, in-process REPL execution, or expression-based materialization
fail during **preflight before the model is called**. The no-exec policy is
independent of `CAPYBARA_UNSAFE_LOCAL_EXEC`; the benchmark harness does not
gain host privileges from developer test overrides. Workspace writes proposed
by an SLM are denied unless an explicitly reviewed policy changes that rule.

`data/benchmark_safe_pipeline.json` exercises a fully offline two-stage
harness and is validated by CI. The long-horizon saga uses the unchanged
`data/distributed_saga_recovery_pipeline.json` but **cannot run** with
the current safe-mode backend: it requires a separately isolated persistent
REPL. It is scored as **unsupported**, *not* as a model failure, and no
provider inference is attempted. The scorecard exposes `unsupported_trials`
and excludes unsupported arms from the verified success denominator.

Before publishing SLM capability comparisons, implement an isolated,
stateful Python execution worker with bounded memory, allowed imports,
mandatory termination, and independent state export. Certify the worker and
run the same fixture under both conditions without weakening safety gates.
Random seeds in benchmark metadata control trial ordering only; provider
sampling determinism requires separate support. A deterministic harness
smoke test is **not evidence of TAL performance improvement**.
