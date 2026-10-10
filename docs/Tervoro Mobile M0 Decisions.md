# Tervoro Mobile M0 Decisions

Status: frozen for the Android-first MVP on 2026-08-30. Changes require a new versioned
artifact, migration note, fixtures, and conformance review.

## D-001: TAL mobile profile

- Decision: use `tal.mobile.secure_assistant-0.1.0` over TAL core compatibility `0.3.x`.
- Grammar and manifest identifiers: `tal-core-0.3.0` and `tal-manifest-0.3.0`.
- Canonicalization: `tal-json-c14n-0.2`.
- Rationale: the profile is closed, independently versioned, and can be shared by the Python
  oracle and native mobile implementations.

## D-002: Android support profile

- Decision: Android API 28+ and `arm64-v8a` for the local-inference MVP.
- Rationale: this matches the existing Android minimum and keeps the certified device matrix
  small while the model/runtime boundary is proven.
- Consequence: unsupported devices show an explicit unavailable state; no cloud fallback is used.

## D-003: Local model route

- Decision: retain the provider-neutral `ModelAdapter` interface; use the scripted model for
  conformance and LiteRT-LM as the first local inference candidate.
- Certification unit: exact package hash, weights, quantization, tokenizer, runtime, prompt
  profile, decoding parameters, OS, and device profile.
- Consequence: no unsigned imported model may start a protected production run. Selecting a
  production weight package remains a licensing and certification gate, not an implicit runtime
  choice.

## D-004: Encrypted durable storage

- Decision: Room-compatible transactional event-store interface backed by an encrypted database,
  with a Keystore-wrapped data-encryption key. Secrets remain outside the event ledger.
- Rationale: a per-file audit sink cannot satisfy atomic state/event updates, replay, indexes, or
  deletion propagation.

## D-005: Document and image processing

- Decision: selected documents use the Android Storage Access Framework. Text extraction and
  lexical retrieval ship first. Image OCR is an optional local adapter and cannot bypass
  provenance, bounded output, or deletion rules. Vector retrieval is deferred until the lexical
  flow, device budgets, and encrypted-index design are certified.

## D-006: Network policy

- Decision: M0-M6 uses `local_only` and declares no `INTERNET` permission in the production
  profile. `ask_before_cloud` and `managed_hybrid` are cataloged future modes, not active routes.

## D-007: Scope boundary

- Decision: prove selected-document answers, summaries, local drafts, notes, tasks, and vault
  search before calendar writes, direct sending, plugins, enterprise synchronization, or high
  impact effects.
