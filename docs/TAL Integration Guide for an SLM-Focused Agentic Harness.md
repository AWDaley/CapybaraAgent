[Download the TAL SLM Harness Adaptation Guide](sandbox:/mnt/data/TAL_SLM_Harness_Adaptation_Guide.md)

The Markdown file is a self-contained, implementation-oriented reference covering:

- TAL’s controlled English vocabulary and exact semantic categories.
- Closed schemas and the decision to exclude custom keys.
- Deterministic form-to-manifest compilation.
- Canonical JSON, versioning, hashing, and immutable manifests.
- Epistemic states: reported, observed, inferred, assumed, conflicted, and verified.
- Requested, effective, and denied capabilities.
- A reduced **TAL-SLM Core Profile** suitable for smaller models.
- Phase-specific, token-efficient SLM context packets.
- Strict proposal types and bounded malformed-output repair.
- The deterministic validation pipeline and action gate.
- Typed tools, effect classes, approvals, idempotency, and reconciliation.
- Event-derived state, pure reducers, optimistic concurrency, and replay.
- Independent completion verification.
- Budgets, bounded execution, and escalation behavior.
- State, context, and persistent-memory separation.
- Domain-pack design without arbitrary extension fields.
- Architecture-neutral interfaces for adapting an existing harness.
- A reference execution loop and integration mapping table.
- SLM-specific reliability techniques and capability profiles.
- Threat modeling, stable error codes, tests, evaluation metrics, milestones, definition of done, and a full integration checklist.

The central SLM adaptation principle is:

> **Compress the model-facing protocol, not the enforcement guarantees.**