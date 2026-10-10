# Tervoro Mobile App Build Plan

Status: implementation plan based on `Tervoro_TAL_SLM_Mobile_Agent_Design_Specification.docx`  
Plan date: 2026-08-30  
Target: Android-first, local-only TAL-governed SLM assistant  
Production label during M0-M5: security prototype; not Tervoro Certified

## 1. Executive direction

Build Tervoro Mobile as a bounded task workspace, not an unrestricted chat agent. The user chooses a registered workflow, exact data sources, desired outcome, retention policy, and requested capabilities. Deterministic code compiles those choices into a closed, hashed TAL manifest. The SLM receives a compact context and may propose exactly one typed operation at a time. Only the TAL runtime may authorize a tool, mutate state, grant an approval, or declare completion.

The first product-quality vertical slice will be an offline selected-document assistant. It will let the user select a document, review the task and data scope, run a local model, receive an evidence-backed answer or summary, inspect the audit timeline, and delete or retain the run. This workflow exercises the complete security and reliability boundary without requiring broad permissions or external effects.

Do not add calendar writes, direct message sending, cloud inference, third-party skills, enterprise synchronization, or high-impact actions until the local read/draft workflows pass state-integrity, privacy, interruption, completion, deletion, and replay certification.

## 2. Current repository baseline

### Implemented foundation

- Android application shell using Kotlin, Jetpack Compose, a single activity, and unidirectional state flow.
- `demo` runtime flavor with a deterministic proposal generator.
- `litert` runtime flavor with an on-device LiteRT-LM adapter and GPU-to-CPU fallback.
- Framework-independent Kotlin `tal-core` module with a hashed task manifest, strict proposal parser, closed tool schemas, capability checks, phase/effect checks, bounded steps, typed errors, and completion results.
- App-private tools for current time, encrypted note listing/reading, and authenticated note writes.
- Biometric or device-credential approval surface for write effects.
- AES-GCM encrypted notes, HMAC-authenticated audit events, and Android Keystore-backed non-exportable keys.
- Encrypted append-only audit writes and backup/device-transfer exclusions.
- No Android `INTERNET` permission; network and destructive effects are denied by the mobile gate.
- Versioned M0 profile contracts, schemas, canonicalization rules, error catalog, and shared golden fixtures are present.
- A Python simulator and Kotlin reducer replay the shared document-answer fixture with state-version and idempotency checks.
- TAL core now enforces per-inference remaining-time deadlines, preserves cancellation as a lifecycle signal, and binds approvals to manifest hash, state version, canonical arguments, and expiry.
- The Android shell has an explicit cancel control and a scoped, bounded, text-only selected-document reader for the deterministic offline slice.
- Forty-six Kotlin TAL-core tests and 266 Python repository tests passed at the last conformance run; Android app compilation and device validation remain blocked until a local Android SDK is configured.

### Partial implementations that must be replaced or hardened

| Area | Current state | Required target |
|---|---|---|
| TAL profile | Simplified `1.0-mobile` types in Kotlin | Exact versioned TAL 0.3.x mobile profile, schemas, catalogs, canonicalization, error codes, and golden fixtures |
| Task intake | Free-form chat goal | Registered task templates, selected targets, explicit success conditions, requested capabilities, prohibitions, retention, and contract preview |
| Runtime state | In-memory view-model state | Event-derived durable state with state version, ledger sequence, pure reducer, checkpoints, replay, and reconciliation |
| Audit | Encrypted write-only event files | Encrypted transactional event store, chain verification on load, human timeline, advanced inspector, export, retention, and deletion |
| Approval | Generic biometric result resolves current pending request | Typed approval bound to manifest hash/version, state version, action, target, canonical arguments, authentication strength, and expiry |
| Model import | Extension/size check and displayed SHA-256 | Signed package verification, certified model profile, compatibility checks, staged activation, rollback, revocation, and run binding |
| Verification | Non-empty answer and verified local writes | Declared terminal conditions, required observation types, evidence trust/freshness, conflict checks, output-contract validation, and release gate |
| Budgets | Steps, time, tool errors, repair attempts | Hard inference deadline plus model/tool/token/context/storage/effect, memory, battery, thermal, and device-profile budgets |
| Mobile tools | App-private notes only | Selected document/image reads, vault search, drafts, notes, local tasks, and later bounded calendar availability |
| Testing | Kotlin unit tests for the small TAL core | Cross-language golden conformance, Android contract/integration tests, lifecycle fault injection, adversarial tests, device tests, privacy inspection, accessibility, and replay equivalence |

## 3. MVP product scope

### Core workflows

1. Answer questions about one or more user-selected documents with visible evidence spans.
2. Summarize selected documents into a registered output structure with source references.
3. Extract local tasks from selected documents, images, or shared text; label every item as sourced or inferred.
4. Create app-local drafts, notes, and tasks that are reversible and user-deletable.
5. Search an explicit encrypted local vault and produce evidence-backed results.

Selected-image OCR may ship with the core MVP when it can meet the same provenance and deletion guarantees. Calendar availability is a post-core read-only extension and must not delay certification of the selected-document flow.

### Explicitly deferred or prohibited

- Direct message or email sending.
- Calendar event creation or modification.
- Payments, purchases, account changes, irreversible deletion, or sensitive disclosure actions.
- Arbitrary code, shell, Python, filesystem traversal, or model-generated executable scripts.
- Broad contacts, calendar, photo-library, microphone, location, notification, or screen-monitoring access.
- Automatic cloud fallback, open plugins, third-party domain packs, and cross-device memory.
- Always-on background reasoning or multi-agent inference.

## 4. Architecture decisions

1. **Python remains the conformance oracle.** Extend the existing `tal/` implementation with mobile schemas, fake native tools, lifecycle injection, golden hashes, and certification fixtures.
2. **Kotlin remains the Android MVP enforcement core.** Evolve `mobile/tal-core` until the selected-document workflow and mobile contract are stable. Keep interfaces compatible with a later Rust core, but do not introduce Rust before M6 unless a Kotlin limitation blocks conformance.
3. **Native Android code owns protected boundaries.** Kotlin owns document grants, permissions, Keystore operations, biometric prompts, model sessions, lifecycle handling, native tools, and the user interface.
4. **Durable state is event-derived.** A transactional encrypted event store is the source of truth. Compose renders reducer projections; chat messages are not authoritative state.
5. **The model layer is provider-neutral.** Keep the current LiteRT-LM adapter as a candidate route, add a scripted adapter for certification, and certify exactly one local model profile first.
6. **Production M0-M6 remains local-only.** Keep the production manifest free of `INTERNET`. Any future hybrid mode must be a separately reviewed capability and disclosure path.
7. **Use scoped platform selection.** Read documents and images through the Storage Access Framework and share intents; never scan general storage.
8. **Use encrypted structured storage.** Put manifests, events, approvals, state projections, observations, vault metadata, and index metadata behind a Room-compatible event-store contract with a proven encrypted database and Keystore-wrapped data key. Keep provider credentials and secret keys outside the ledger.
9. **Completion is a runtime decision.** The model cites one registered success condition and evidence references; deterministic verifiers decide whether the result may be released.

## 5. Target module map

```text
Capybara/
  contracts/                         # New: mobile schemas, catalogs, package descriptors
    mobile-profile/
    canonical/
    errors/
  fixtures/                          # New: shared valid, invalid, adversarial, replay fixtures
    mobile/
  tal/                               # Existing Python conformance oracle
    domain_packs/mobile_private_assistant/
    mobile_simulator/
  mobile/
    tal-core/                        # Kotlin deterministic core during Android MVP
      manifest/
      policy/
      proposal/
      gate/
      events/
      reducer/
      completion/
      context/
    app/
      ui/home/
      ui/newtask/
      ui/run/
      ui/action/
      ui/result/
      ui/audit/
      ui/vault/
      ui/policies/
      ui/settings/
      data/eventstore/
      data/vault/
      data/retrieval/
      security/
      models/
      tools/
      lifecycle/
    certification/                  # Android test harness and device profiles
  core-rust/                         # M7 target after Android contract is stable
  ios-app/                           # M7, not part of Android MVP
```

Package boundaries should be enforced by interfaces so the model adapter cannot obtain native tool objects, the UI cannot mutate authoritative state directly, and native tools can execute only through the action gate.

## 6. Primary end-to-end proving flow

The first certified flow is `document.answer_with_evidence`:

1. User chooses **Analyze selected document** from a registered task template.
2. Android's document picker grants access to the exact URI; the user chooses ephemeral use or vault retention.
3. The task composer records the target, question, local-only mode, prohibited network action, evidence requirement, retention, and fallback.
4. The deterministic compiler validates and canonicalizes the manifest, computes its hash, and creates a separate immutable run binding containing the policy, model, OS, and device profile hashes.
5. The contract preview shows the goal, selected data, effective/denied capabilities, success condition, retention, and offline state.
6. The parser extracts bounded text and metadata, hashes the source, records provenance, chunks locally, and builds a lexical index; optional embeddings remain device- and policy-gated.
7. The context builder supplies one phase-specific schema, current state, bounded evidence, effective tools, remaining budgets, and the latest typed rejection.
8. The local SLM returns one typed proposal. The parser and action gate validate versions, references, state, capability, scope, phase, policy, budgets, and arguments.
9. Accepted reads return typed observations. Rejected proposals call no tool and do not advance enforceable state.
10. The model proposes completion by naming the current success condition and evidence references.
11. The verifier checks evidence coverage, citation validity, trust, freshness, conflicts, output fields, and the legal terminal transition.
12. The result screen shows the answer, evidence spans, remaining unknowns, audit reference, and retain/export/delete choices.
13. Process death at any checkpoint replays to the same state without recalling the model or repeating an effect.
14. Deleting the run or source removes authorized derivatives, chunks, indexes, cached evidence, and dependent memory according to policy.

## 7. Delivery milestones

The estimates below assume two Android engineers, one TAL/systems engineer, one ML/evaluation engineer, and part-time product design, security, and QA support. The Android MVP is approximately 20-28 engineering weeks when executed mostly sequentially; some UI, fixture, and evaluation work can overlap.

### M0 - Freeze the mobile profile (2 weeks)

**Objective:** turn the specification into executable, versioned contracts before broadening the app.

Deliverables:

- Requirement IDs and a requirement-to-code-to-test traceability matrix using `MOB-PROD`, `MOB-TAL`, `MOB-SEC`, `MOB-DATA`, `MOB-UX`, `MOB-REL`, `MOB-PERF`, and `MOB-CERT` prefixes.
- Frozen identifiers for TAL core 0.3.x compatibility, mobile profile, context profile, policy bundle, tool catalog, domain pack, event schema, and conformance suite.
- Closed JSON Schemas for manifest, run binding, proposal types, capabilities, action previews, approvals, observations, events, state projection, completion, model/device profiles, and signed packages.
- Canonical JSON rules and golden hashes shared by Python and Kotlin.
- Frozen risk tiers, data classes, mobile state machine, tool inventory, stable errors, terminal outcomes, and deletion relationships.
- Decision records for the initial local model, minimum Android/API/ABI profile, encrypted database, and OCR/vector strategy.

Exit gate:

- No arbitrary key/value or extension escape hatch exists.
- Unknown fields and unsupported versions fail closed in both Python and Kotlin fixtures.
- Python and Kotlin produce identical canonical bytes and hashes for every golden manifest.

### M1 - Build the desktop mobile simulator and conformance harness (2-3 weeks)

**Objective:** make the existing Python TAL implementation the behavioral oracle for the mobile lifecycle.

Deliverables:

- `tal.mobile.private_assistant-0.1.0` domain pack with document, evidence, draft, note, task, vault, and completion types.
- Scripted model adapter and fake native tools for deterministic tests.
- Mobile state reducer, event families, state/ledger versions, replay, idempotency, reconciliation, approval expiry, and process-kill injection.
- Fixtures for valid flows, malformed proposals, unknown fields, invented references, stale approvals, permission revocation, timeouts before/after effect acceptance, corrupted events, and deletion propagation.
- Cross-language conformance runner that executes the same fixture in Python and Kotlin and compares rejections, event sequences, canonical state, and terminal outcome.

Exit gate:

- The offline scripted suite passes without network access.
- Replay produces byte-equivalent canonical state without model or effectful tool calls.
- Rejected proposals mutate neither authoritative state nor effect keys.

### M2 - Complete the Android shell and offline document slice (3-4 weeks)

**Objective:** replace the chat-only prototype with the product's registered task flow.

Deliverables:

- Dependency injection and persistent repository interfaces.
- Home, New Task, Contract Preview, Run, Result, and basic Audit screens.
- Registered `document.answer_with_evidence` and `document.summary` templates.
- Storage Access Framework document picker with scoped URI grants and explicit ephemeral/retain choice.
- Provider-neutral `ModelAdapter`, current scripted adapter, and one staged local-model candidate.
- Phase-specific context packets, grammar-constrained generation where supported, one repair attempt, hard inference timeout, cooperative cancellation, and honest progress.
- Device capability screen for model availability, model identity, storage, and unsupported-state explanations.

Exit gate:

- A selected text/PDF-like fixture completes fully offline using the scripted model on an emulator and at least one physical test device.
- The UI exposes goal, selected data, local mode, effective/denied capabilities, current phase, remaining budget, and cancel control.
- A hung model cannot exceed the task deadline or lock the workflow permanently.

### M3 - Make state, storage, identity, and packages durable (3-4 weeks)

**Objective:** make process death, tampering, and deletion first-class runtime conditions.

Deliverables:

- Encrypted transactional event store with atomic append plus state-version compare-and-set.
- Pure Kotlin reducer, durable checkpoints, load verification, predecessor/event digest checks, manifest/run binding checks, and replay inspector.
- Keystore-wrapped app data key, vault lock policy, key rotation/versioning, invalidated-key recovery, and StrongBox fallback tests.
- Durable typed approvals and pending-effect records.
- Signed model/package descriptor with publisher, artifact hashes, tokenizer, quantization, prompt profile, runtime compatibility, device eligibility, certification result, expiry/revocation, and rollback metadata.
- Staged model activation: verify, initialize, health-check, then atomically promote while retaining a known-good rollback artifact.
- Per-run and per-source deletion transactions with derivative/index/cache propagation.
- Privacy-safe diagnostics containing codes, hashes, counts, timings, and adapter IDs rather than raw personal content.

Exit gate:

- Forced process termination at every non-effect and effect boundary restores a valid state.
- Ledger replay reproduces the canonical state and terminal result.
- Corrupted events, stale state versions, invalid signatures, revoked packages, and incompatible models fail closed.
- User deletion removes the run/source and all policy-linked derivatives.

### M4 - Add native tools, exact approvals, and effect safety (3-4 weeks)

**Objective:** expose only the minimal mobile capability surface through typed adapters.

Initial tools:

- `document.selected.read`
- `image.selected.inspect`
- `vault.search`
- `draft.create`
- `note.create`
- `task.create_local`

Deliverables:

- Versioned closed input/output contracts, trust classes, scope checks, redaction, timeouts, and stable failures for every tool.
- Action-gate checks for proposal/manifest/state versions, reference validity, effective capability, data scope, phase, network mode, argument bounds, budget, approval, and package/tool version.
- Exact action preview showing goal, data, recipients, disclosure, exclusions, reversibility, verification, and authentication reason.
- Approval record bound to manifest hash/version, state version, action, target, canonical arguments, authenticated user, strength, timestamp, and expiry.
- Semantic idempotency keys for every local write, intent-before-effect, read-only reconciliation, and safe uncertain-outcome UX.
- Permission revocation and vault-lock handling while a run is waiting.

Exit gate:

- No protected action bypasses the TAL action gate.
- Changed arguments, targets, manifests, state versions, policies, or expiry invalidate approval.
- Process death or timeout cannot duplicate a local write.
- Denial, cancellation, and permission revocation produce usable recovery or safe terminal states.

### M5 - Build the local vault, retrieval pipeline, and evidence release gate (4-6 weeks)

**Objective:** make document answers useful without weakening the trust boundary.

Deliverables:

- Deterministic text extraction and optional local OCR with source hashing and provenance.
- Bounded chunking, encrypted lexical index, and optional certified local vector index.
- Entity-, source-, purpose-, and permission-scoped retrieval with item/token limits.
- Evidence bundles that preserve source reference, span/offset, content hash, trust class, and retrieval reason.
- Claim-to-evidence/citation validator and visible evidence viewer.
- Terminal verifiers for document answer, summary, draft, and task extraction.
- Conflict and remaining-unknown presentation.
- Vault UI for sources, notes, tasks, indexes, retention, export, and deletion.

Exit gate:

- Every material document-answer claim cites a valid visible evidence span.
- Completion without required observations, citations, output fields, or conflict disclosure is rejected.
- Retrieval never accesses a source outside the manifest and effective capability.
- Source deletion removes chunks, indexes, cached evidence, and dependent memory.

### M6 - Run the Android certification pilot (3-5 weeks)

**Objective:** prove the MVP on real devices and freeze a supportable release profile.

Certification layers:

- Unit and property tests for schemas, canonicalization, policies, reducers, budgets, idempotency, errors, encryption wrappers, and output validation.
- Contract tests for model, tool, event-store, approval, Keystore, lifecycle, parser/OCR, and retrieval adapters.
- End-to-end integration tests from task authoring through deletion.
- Adversarial tests for prompt injection, invented tools/references, forged observations, stale approvals, network bypass, package tampering, malformed outputs, duplicate effects, and process-kill recovery.
- Device tests for supported-device detection, memory pressure, thermal state, battery thresholds, lock state, permission revocation, model changes, and offline behavior.
- Model-profile evaluation for structured validity, reference fidelity, recovery, completion precision, latency, context usage, and resource fit.
- Privacy tests for network capture, on-device storage inspection, logs, backups, diagnostics, deletion completeness, screenshots, and clipboard behavior.
- Accessibility tests for TalkBack, text scaling, contrast, reduced motion, switch/keyboard operation, authentication, focus recovery, and action-preview comprehension.
- Independent security review of Keystore usage, encrypted storage, biometric binding, model/package verification, native inference, event replay, and effect recovery.

Exit gate:

- All definition-of-done conditions in Section 10 pass for the certified app/model/device/profile tuple.
- No model-task traffic occurs in local-only mode.
- Replay equivalence and process-death recovery pass at every effect boundary.
- Release artifacts, SBOM, package signatures, privacy inventory, known limitations, rollback plan, and vulnerability process are complete.

### M7 - Shared deterministic core and iOS (post-MVP)

- Move canonicalization, schemas/bindings, policy, gate, events, reducer, replay, and completion into Rust or certify an equivalent shared implementation.
- Compare Python, Kotlin, Rust, and later Swift against the same golden fixtures and replay streams.
- Build SwiftUI, Foundation Models, optional local-model, Keychain, Local Authentication, document-picker, and native tool adapters.
- Do not claim cross-platform parity until canonical hashes, state projections, errors, and terminal outcomes match.

### M8 - Certified ecosystem and managed modes (post-MVP)

- Signed domain/model/policy/tool package registry and revocation service.
- Organization identity, private registries, MDM policy, audit export, and incident response.
- Ask-before-cloud and managed-hybrid modes with minimized disclosure previews and privacy certification.
- Additional domain packs only after at least two packs demonstrate the need for registered extensions.

## 8. Runtime and data contracts to implement first

### Manifest and run binding

The portable manifest contains the goal, declared entities and targets, unknowns, requirements, constraints, preferences, requested capabilities, prohibitions, success conditions, fallbacks, output contract, and integrity metadata. Device facts belong in a separate run binding containing the manifest, policy, model, OS, platform, device profile, network mode, and artifact hashes.

### Proposal binding

Every proposal must carry proposal ID, goal ID, manifest hash/version, state version, tool/version or success-condition reference, canonical arguments, purpose, evidence references, and expected observation type. Stale manifest or state versions fail without state mutation.

### Event and state model

Events cover manifest, policy/capability, model, tool, evidence, approval, lifecycle, and terminal families. Every append validates expected state version and ledger sequence. The reducer is pure and deterministic. Terminal states never become active again.

### Effect integrity

For any mutating operation:

1. Compute a semantic idempotency key from goal ID, manifest hash, semantic action, target, canonical arguments, and adapter namespace.
2. Persist the intent and key transactionally.
3. Execute once through the native adapter.
4. Validate the typed output contract.
5. Persist the observation and new state atomically.
6. If the outcome is uncertain, reconcile read-only before any retry.

### Completion enforcement

The model may propose completion only by naming a current success condition and existing evidence. The verifier checks observation types, trust, freshness, non-conflict, approvals, prohibitions, invariants, output fields, and the legal state transition. Natural-language confidence is never completion evidence.

## 9. UX implementation plan

| Surface | MVP responsibility |
|---|---|
| Home | Start registered tasks; show local mode, model readiness, supported-device state, storage, and recent runs |
| New Task | Choose template, exact sources, result, completion condition, retention, and requested capabilities |
| Contract Preview | Plain-language goal, data, effective/denied authority, prohibitions, local mode, success condition, and fallback |
| Run | Phase, current step, bounded progress, model/tool state, budgets, clarification/approval, and cancel |
| Action Sheet | Exact operation, data, recipients, disclosure, exclusions, reversibility, verification, and authentication |
| Result | Outcome, evidence, remaining unknowns/conflicts, audit reference, export, retain, and delete |
| Audit | Human timeline plus advanced JSON/event/hash/replay inspector |
| Vault | Sources, notes, tasks, memory, indexes, retention, export, and deletion |
| Policies | Local/cloud mode, default approvals, OS permissions, trusted packages, and organization controls |
| Settings | Model/device profile, accessibility, diagnostics, storage, security, and app lock |

Progressive disclosure is mandatory. The default experience uses plain language; schemas, hashes, event payloads, and evidence graphs live in an advanced inspector. AI-generated content and unsupported/uncertain states must be labeled. Every guided flow has a cancel path before a consequential commit.

## 10. Android MVP definition of done

- A clean install completes every core workflow offline on at least one declared supported-device profile.
- Unknown properties, versions, tools, references, terminal conditions, packages, and state transitions fail closed.
- The SLM cannot directly call a native capability, access a framework object, grant approval, mutate authoritative state, or establish completion.
- Effective capability is computed outside the model and never exceeds OS permission, user request, signed policy, registered tool scope, argument bounds, or remaining budget.
- Rejected proposals invoke no tool, consume no effect key, and do not change enforceable state.
- Forced process termination at every effect boundary restores, reconciles, or safely terminates without duplicate effects.
- Every terminal completion passes its declared deterministic verifier.
- Encrypted ledger replay produces the same canonical state and terminal outcome without model or effectful tool calls.
- Local-only mode passes network inspection with no model-task traffic and no unexpected third-party endpoints.
- Imported sources, derived chunks/indexes/evidence, memory, runs, and outputs can be deleted according to policy.
- Every run records the exact grammar, schema, canonicalization, policy, tool, model, prompt, runtime, OS, app, and device profile.
- Model proposal validity is at least 95% after no more than one repair attempt on the frozen certification set.
- Invented tools and references have a zero accepted rate.
- Accessibility, privacy, security, performance, battery, memory, thermal, and model-profile gates pass for every supported release profile.
- An independent review has approved the protected production boundaries.

## 11. Immediate engineering backlog

Execute these items in order:

1. Create the specification traceability matrix and freeze M0 artifact identifiers.
2. Add `contracts/mobile-profile` and shared canonical/golden fixtures.
3. Replace the current simplified manifest/proposal types with versioned mobile-profile contracts, including manifest and state binding.
4. Add a hard outer timeout and explicit cancel path around local model generation.
5. Implement the event-store interface, pure reducer, state/ledger versions, replay loader, and corruption checks.
6. Change `WaitingForUser` from a terminal in-memory return into a durable resumable state.
7. Add semantic idempotency, intent-before-effect, and reconciliation to every write tool.
8. Bind biometric approval to the exact request record and surface authentication failures.
9. Replace direct model replacement with signed staged activation, health check, rollback, and run binding.
10. Add dependency injection and scripted/fake Android adapters for full-flow tests.
11. Build the registered task composer and plain-language contract preview.
12. Implement `document.selected.read` through the Storage Access Framework with strict bounds and provenance.
13. Add the encrypted event database and Keystore-wrapped data-key hierarchy.
14. Implement `document.answer_with_evidence` using deterministic fixtures before real local inference.
15. Add claim/citation validation, result evidence UI, audit timeline, and deletion propagation.
16. Run process-kill, stale-approval, corrupted-package, network-capture, TalkBack, and physical-device suites before adding another domain capability.

## 12. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| Mobile contract drifts from desktop TAL | Shared schemas, canonical fixtures, errors, event sequences, and cross-language conformance on every change |
| Local model is unreliable or too resource intensive | Certify one frozen profile; scripted fallback for tests; device eligibility and resource budgets; no silent model substitution |
| Process death duplicates or loses effects | Intent-before-effect, transactional event append, semantic idempotency, read-only reconciliation, and fault-injection tests |
| Broad OS permissions expose excess data | System pickers, URI grants, field minimization, adapter redaction, and TAL target/field/time/purpose scopes |
| Imported content performs prompt injection | Trusted instruction/data separation, bounded evidence, closed proposal schema, reference validation, and no authority from retrieved text |
| Encryption design is bespoke or fragile | Proven encrypted database, Keystore key wrapping, versioned envelope format, rotation/recovery tests, and independent review |
| Model or policy package is compromised | Signed descriptors, publisher trust, digest verification, compatibility, revocation, staging, rollback, and production/developer isolation |
| Completion looks plausible but is unsupported | Registered terminal conditions, required observations, claim/citation verification, conflict disclosure, and deterministic release gate |
| Diagnostics leak private content | Local aggregated metrics, redacted structured events, opt-in export, storage/log/network inspection, and third-party SDK minimization |
| Scope grows before safety is proven | M6 certification gate blocks calendar writes, messaging, cloud, skills, enterprise sync, and high-impact actions |

## 13. Release and governance

- Version grammar, schemas, canonicalization, mobile profile, domain pack, policy bundle, event schema, tools, model profile, prompt profile, and device profile independently.
- Never overwrite historical meaning. Breaking changes create a new artifact and explicit migration record.
- Preserve the exact artifacts or hashes needed to replay every retained run.
- Re-certify a system/local model after OS, runtime, tokenizer, quantization, prompt, or decoding changes.
- Maintain rollback for app, model, policy, and package releases.
- Keep telemetry local by default. Remote diagnostics require explicit opt-in, minimization, and a visible inventory.
- Establish package revocation, vulnerability reporting, incident response, and independent security review before using a production certification badge.

## 14. Recommended first release statement

Until M6 passes, describe the app as:

> An Android engineering prototype of a local TAL-governed small-language-model assistant. It demonstrates deterministic proposal gating, scoped local tools, encrypted storage, user approval, and offline inference, but it has not yet completed Tervoro production certification for replay, model/package trust, lifecycle recovery, evidence-backed completion, device performance, privacy, accessibility, or independent security review.

After M6, the release claim should name the exact certified app, model, grammar, policy, tool, OS, and supported-device profile rather than claiming universal mobile security or reliability.
