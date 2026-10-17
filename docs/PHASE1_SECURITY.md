# Phase 1 hardening: trust boundaries and operational limits

Updated October 2026. This document describes the safe defaults introduced
by Phase 1 and the security claims that **have not** been established.

## Default execution

TAL remains enabled in the browser and cannot be disabled through `/api/config`.
Effectful TAL actions pass closed-schema validation, capability and phase checks,
workspace-path checks, explicit user approval (when required), and a one-use
authorization bound to the task, manifest, session, tool, phase and canonical
arguments. A disabled legacy guardrails flag does **not** bypass TAL approval.

Files must be named explicitly. The agent no longer selects the newest file
when a model omits `read_file.path`.

Unknown/unavailable execution capabilities are not advertised as safe. By
default the model-driven Python REPL is disabled, and `run_command` is only
available with an explicitly configured isolated container runtime.

## Experimental stateless container executor

Set `CAPYBARA_CONTAINER_RUNTIME=docker` or `podman`, and
`CAPYBARA_SANDBOX_IMAGE=<image>@sha256:<64-hexadecimal-digest>`.
A mutable tag is rejected. The runtime executable must exist in PATH.

The stateless runner uses an ephemeral container with a nonroot UID, dropped
capabilities, no network namespace access, a read-only root filesystem,
a limited process count, memory and CPU limits, and an explicit workspace bind
mount. Python scripts are copied to an immutable in-memory snapshot **before approval**,
and that exact snapshot hash is displayed for review and executed afterward.
On timeout the container is force-removed by its ID. The runner does not provide
a stateful REPL, and it does not attempt host execution as a fallback.

**Limitations:** Docker/Podman installation, permissions, image provenance,
kill/recovery behavior, filesystem permissions and sandbox availability must
be validated on each deployment. User-selectable images and privileged
container flags are unsupported. A shared workspace is not suitable for
untrusted multi-user operation; that isolation is Phase 2.

`CAPYBARA_UNSAFE_LOCAL_EXEC=1` is an explicit developer/testing override
that enables legacy in-process REPL/host command behavior. Never use it with
untrusted prompts or data. The web server refuses non-loopback binding with
this override. The Python unit-test fixture uses it only to exercise existing
trusted test scripts. CLI legacy mode is not a security boundary.

## Verified versus unverified

A TAL task has a terminal status of `verified`,
`completed_unverified`, `failed`, `escalated`, or
`waiting_for_user`. An empty set of acceptance criteria fails the
independent-verification gate. A filename inferred from a user prompt can
trigger a fresh-artifact check, but such **heuristic** evidence is not proof of
correct task semantics, so the outcome remains `completed_unverified`.

Pipelines no longer mark a step verified merely because it has no acceptance
criteria. The benchmark's `verified_success_rate` counts only runs with an
explicit verified outcome, not just nonempty model output.

## Validation

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest
```

CI tests on Linux and Windows with Python 3.10, 3.11, and 3.12. These checks
do not replace sandbox penetration testing, real LLM benchmarking, Android
device verification, or multi-user deployment hardening.


## Phase 6 addendum: isolated stateful benchmark worker

The historical stateless container notes above remain accurate for the
`run_command` tool. Fixed-pipeline benchmark runs can additionally use a
separate, persistent **OS-contained** Python worker if a reviewed,
digest-pinned image and runtime are configured. The ordinary browser and CLI
entrypoints still disable model-directed stateful REPL execution in safe
mode. See [stateful worker deployment](STATEFUL_CONTAINER_WORKER.md).
