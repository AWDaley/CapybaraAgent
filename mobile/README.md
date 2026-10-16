# Tervoro mobile

Tervoro is the Android-first mobile form of Capybara: a local small-language-model agent whose authority and completion claims are governed by TAL.

This first vertical slice is intentionally narrow and executable:

- `:tal-core` is a framework-independent Kotlin TAL runtime with immutable hashed manifests, closed proposal and tool schemas, capability and phase gates, approval policy, bounded execution, independent write verification, and hash-chained audit events.
- `:app` is a Jetpack Compose client with a local/offline security state, chat/task intake, a visible TAL action sheet, biometric or device-credential confirmation for writes, encrypted local notes, and encrypted no-backup audit records.
- The Android manifest declares no `INTERNET` permission. Network and destructive effects are denied by the mobile action gate.
- `demoDebug` uses a deterministic proposal generator for UI and policy testing. It is not represented as an SLM.
- `litertDebug` uses the official LiteRT-LM Kotlin API and imports a `.litertlm` model into app-private no-backup storage. GPU initialization falls back to CPU.

## Open in Android Studio

1. Install current Android Studio with Android SDK 37 and JDK 17 or newer. The `litert` flavor may require JDK 21 because of the native runtime's published Kotlin bytecode; the `demo` flavor and TAL core use JDK 17.
2. Open the `mobile` directory as the project.
3. Select the `demoDebug` build variant for the self-contained policy/UI demo.
4. Run `./gradlew :tal-core:test :app:assembleDemoDebug` from the `mobile` directory.
5. For real inference, select `litertDebug`, install the app on an arm64 phone, and use the add button to import a compatible `.litertlm` model.

The project does not download a model. Release builds enforce a pinned SHA-256
on imported and previously installed LiteRT-LM packages. Configure the Gradle
property `tervoroApprovedModelSha256=<64-character digest>` for a production
build; release without a valid pin refuses model activation. Debug builds can
import unpinned models for local testing. A digest validates byte identity,
**not model provenance, licensing, publisher identity, or a digital signature**;
signed manifests and distribution policy remain required before production release.

## Current trust boundary

```text
User goal
  -> immutable TaskManifest
  -> phase-specific compact prompt
  -> local SLM emits one strict typed proposal
  -> closed schema + capability + phase + local-only policy gate
  -> biometric action sheet when required
  -> typed native tool
  -> read-back verification
  -> encrypted, authenticated audit event
  -> independent completion gate
```

The SLM never receives an Android `Context`, storage handle, crypto key, approval callback, or tool implementation. LiteRT-LM automatic tool calling is disabled; tool-looking model output is parsed as untrusted proposal data and goes through TAL.

## Private storage

- AES-256/GCM and HMAC-SHA256 keys are generated as non-exportable Android Keystore keys.
- Each audit event is HMAC-authenticated, linked to the previous event hash, encrypted with event-specific associated data, fsynced, and written to a new file.
- Notes are AES-GCM encrypted and read back after writes. Their keys and values are not present in filenames.
- Backup and device-transfer extraction are disabled for all app data.

This protects data at rest and makes local log modification detectable by the app. It does not claim protection from a fully compromised OS, screen capture by privileged software, malicious accessibility services, or model-supply-chain compromise.

## Next implementation gates

1. Pin and verify a Tervoro-approved model package: signature, digest, model card, license, prompt-template compatibility, and device/RAM eligibility.
2. Add replay/load verification for encrypted audit sessions and event-derived UI state.
3. Add Android document retrieval through the Storage Access Framework with per-document grants, bounded chunking, provenance, and revocation.
4. Add signed capability/domain packs and stable migration rules.
5. Add thermal, memory, battery, context, and token budgets with device-class certification.
6. Add adversarial proposal, prompt-injection, model-package, crash/replay, idempotency, and biometric lifecycle tests on physical devices.
7. Add an iOS adapter only after the common TAL conformance suite passes independently of Android.


## Mobile smoke tests and CI

The Android workflow builds the demo flavor and runs pure Kotlin TAL tests plus
demo-provider JSON regression tests; it intentionally avoids downloading a
third-party model. Use `bash ./gradlew :tal-core:test :app:assembleDemoDebug
:app:testDemoDebugUnitTest` from `mobile/` to reproduce it.

Write approvals bind to a specific `ApprovalRequest.requestId`. A cancelled
or failed biometric prompt resolves as DENIED, and late callbacks cannot approve
a different task. Model imports delete abandoned staged files on all failure
paths and discard successful rollback copies. Device-specific biometric,
Keystore, GPU and performance behavior still requires physical-device testing.
