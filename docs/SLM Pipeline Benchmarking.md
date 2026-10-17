# Fixed-pipeline SLM evaluation (suite v3)

Use `benchmarks/slm_v3.json` for task suites with fixed structured pipelines.
The `pipeline_fixture` field is a checked-in `data/<basename>.json` path.
The evaluator does **not** permit model-generated pipeline definitions or
arbitrary absolute/local paths. Every trial records the SHA-256 of the exact
fixed workflow file as `pipeline_sha256`, so fixture changes remain visible
even if suite metadata has not been updated. The same pipeline graph, tool registry, and
independent acceptance checks run in both the baseline and TAL arms.

The pipeline runner permits only local, deterministic tools
(`calc`, `read_file`, `list_files`, etc.) and predeclared deterministic
file materialization by default. Host subprocess and network operations are
never admitted. When a **digest-pinned Docker/Podman worker** is available, it
also accepts the exact container-bound `python_repl` tool, stateful REPL
checks and restricted data-only materialization. The benchmark harness
never uses the local in-process REPL, regardless of
`CAPYBARA_UNSAFE_LOCAL_EXEC`. The model may mutate only its scratch
workspace, never application or customer folders.

`data/benchmark_safe_pipeline.json` exercises a two-stage offline harness.
`data/benchmark_isolated_stateful_pipeline.json` exercises an isolated,
persistent REPL and a JSON export. The full eight-stage
`data/distributed_saga_recovery_pipeline.json` can now run **only** when
the sandbox worker is configured and available. Otherwise both trial arms are
reported as **unsupported**, not as a model failure. The scorecard excludes
unsupported runs from the verified-success denominator.

Real Docker integration tests execute the full saga with scripted synthetic
proposals. These tests verify runtime integration and deterministic oracles,
not a real SLM's long-horizon capability.

Before publishing SLM capability comparisons, certify the container
deployment, evaluate held-out real model trials under both conditions,
measure completion and resource variance, and avoid weakening safety gates.
See [stateful container worker](STATEFUL_CONTAINER_WORKER.md).
Random seeds in benchmark metadata control trial ordering only; provider
sampling determinism requires separate support. A deterministic harness
smoke test is **not evidence of TAL performance improvement**.
