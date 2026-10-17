# Isolated stateful Python execution for TAL pipelines

This worker is enabled **only** for fixed-pipeline benchmark runs that
explicitly declare `python_repl` and use an approved OS container runtime.
The normal web, CLI and non-benchmark agent entrypoints still do **not**
advertise a stateful Python REPL in safe mode.

## Configuration

Install and secure a compatible Docker/Podman runtime on a trusted,
dedicated worker host. The account must be permitted to run *only* the
appropriate sandbox workloads; do not expose its Docker API/socket to agents.

Set:

```bash
export CAPYBARA_CONTAINER_RUNTIME=docker
export CAPYBARA_SANDBOX_IMAGE='python@sha256:<approved-64-hex-digest>'
```

The image must be a reviewed Python image pinned to an immutable registry
digest. The container must support `python -I -B -u /worker.py`. No image is
downloaded by Capybara automatically. A missing runtime, missing image,
mutable tag, invalid policy or failed startup denies the capability **before
a model call**.

Each paired trial creates a new empty private workspace and a new, independent
container session. The process receives a read-only mounted Python worker and
a single, task-scoped workspace bind mount. Policy applies:
- `--network none` and no host socket/device mount;
- non-root UID, dropped Linux capabilities, `no-new-privileges`;
- read-only root filesystem and bounded writable `/tmp`;
- CPU, memory and PID limits;
- bounded input, tool output and JSON-serialized state snapshots;
- per-request monotonic deadlines, and forced container removal by random
  name if the worker times out or the protocol fails;
- all workers terminated when the trial ends.

Python's `exec` is called **inside** the OS container only. The host
interpreter parses tool arguments as strict JSON or bounded Python *literal*
data using `ast.literal_eval`; it never executes model code. Model-produced
state and files remain **untrusted** until the host's independent verification
gates and benchmark oracle inspect them.

A checked-in structured pipeline may use a session-local `python_repl`
and data-only REPL-variable/REPL-graph checks, but still cannot request
host-shell or network tools. The harness may authorize effects **only within
that new temporary workspace**; this is not a general-purpose permission to
write application or customer files. Arbitrary tool registries named
`python_repl` do not pass TAL governance.

## Testing

```bash
python -m pytest tests/test_stateful_worker.py -q
```

Default CI tests only the worker's protocol using literal, trusted snippets
and skips real container tests. The `stateful-container.yml` workflow also
pulls a known Python test image, resolves its immutable digest and runs:

- container state persistence and bounded exports;
- workspace confinement (without host home mounts);
- forced timeout and container-name cleanup;
- baseline/TAL parity on a deterministic stateful two-step pipeline;
- the complete eight-stage synthetic distributed-saga fixture, with an
  independent 26-event ledger hash-chain and business-invariant oracle.

The saga test uses deterministic scripted model proposals. A passing script
test **does not demonstrate a real small model's performance or TAL benefit**.

## Security limitations and next gates

This is OS-container-based containment, not a formally proven sandbox.
A vulnerable shared/rootful container daemon or kernel, permissive container
engine configuration, compromised host filesystem, malicious image and
unbounded model/system-resource interactions remain relevant threats.
Deploy with rootless or user-namespace-isolated containers, restricted host
accounts, explicit service lifetimes and defense-in-depth controls; perform
sandbox escape testing on target hosts before allowing untrusted customer code.

There is no per-task outbound network authorization (network is disabled),
and no persistent state across independent trial containers. Checkpoint
**resumption** of REPL variables across killed containers is not supported;
do not rely on the legacy in-process `dict.update()` resume mechanism.
Real SLM benchmark trials, held-out task evaluation, repeat sampling with
provider-specific seeds, and statistical significance remain future gates.

Do not set `CAPYBARA_UNSAFE_LOCAL_EXEC=1` for untrusted workloads; the
fixed-pipeline benchmark never relies on that opt-in.
