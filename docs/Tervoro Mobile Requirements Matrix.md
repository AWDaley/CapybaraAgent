# Tervoro Mobile Requirement Traceability Matrix

This matrix anchors the approved design specification to implementation artifacts and evidence.
Rows expand as domain packs and release profiles are added.

| ID | Requirement | Primary implementation artifact | Evidence |
|---|---|---|---|
| MOB-TAL-001 | The SLM proposes one typed operation and never directly executes a tool. | `mobile/tal-core`, model adapters, action gate | Kotlin proposal/gate tests and scripted integration fixture |
| MOB-TAL-002 | All profile objects are closed and versioned. | `contracts/mobile-profile/schemas`, profile catalog | Python contract test, Kotlin golden-contract test |
| MOB-TAL-003 | Python and Kotlin use identical canonical manifest bytes and hashes. | `fixtures/mobile/golden-manifests.json`, `tal/mobile_profile.py`, `MobileProfileContract.kt` | Python and Kotlin golden-fixture tests |
| MOB-TAL-004 | Rejected proposals have no enforceable state mutation or effect key. | Event reducer and action gate | M1 fault-injection/replay fixture |
| MOB-SEC-001 | Core MVP remains local-only and has no agent network path. | Android manifest, policy bundle, native registry | Manifest inspection and network-capture certification |
| MOB-SEC-002 | Model, policy, tool, and domain packages are signed, compatible, and revocable. | Package descriptor, verifier, model store | M3 package contract and tamper tests |
| MOB-SEC-003 | Every consequential approval binds manifest, state, target, arguments, user, strength, and expiry. | Approval record and provider | M4 stale-approval tests |
| MOB-SEC-004 | Sensitive state is encrypted and keys remain protected by Android Keystore. | Encrypted event store and key manager | M3 storage/key tests and security review |
| MOB-DATA-001 | The app reads only user-selected sources or scoped vault items. | SAF adapter, capability engine | M2/M4 URI scope tests |
| MOB-DATA-002 | Retained data and derivatives can be deleted according to policy. | Vault repository and deletion reducer | M3/M5 deletion propagation tests |
| MOB-REL-001 | State is derived from an append-only ledger and can be replayed. | Event store, reducer, replay verifier | M1/M3 replay equivalence fixtures |
| MOB-REL-002 | Process death cannot duplicate an effect. | Intent-before-effect, idempotency, reconciliation | M4 interruption fixtures |
| MOB-REL-003 | Completion is established only by a deterministic verifier. | Completion verifier and output contracts | M5 insufficient-evidence tests |
| MOB-PERF-001 | Inference, tools, context, storage, battery, memory, and thermal use are bounded. | Device profile, budget engine, lifecycle manager | M2 hard timeout and M6 device suite |
| MOB-UX-001 | The user can inspect scope, progress, approval need, evidence, audit, and deletion. | Task, Run, Result, Audit, and Vault screens | M2-M5 UI/instrumentation and accessibility tests |
| MOB-CERT-001 | A certified label requires conformance, adversarial, replay, privacy, device, accessibility, and security evidence. | Certification suite and release checklist | M6 release dossier |
