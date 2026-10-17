# Android device certification gate

## CI versus real device testing

Regular GitHub Actions builds `demoDebug` and its instrumented test APK and
runs TAL core JVM tests. It **does not** authenticate through a human biometric
prompt, verify hardware-backed keys, exercise real device faults, or certify a
specific model's resource needs.

`AndroidSecurityCertificationTest` adds on-device checks for:
- Denial of INTERNET permission and Android backup;
- Actual device API, ABI, RAM, storage, battery and thermal telemetry;
- AndroidKeyStore AES-GCM: unique ciphertext, correct AAD and tampering denial;
- AndroidKeyStore HMAC signed audit log, replay and ciphertext tampering denial;
- Encrypted notes: readback, idempotent retry and reject conflicting writes;
- Existing P-256 signed model provider/manifest conformance.

## Physical device runner

In a controlled test lab, install Android SDK tools, JDK 17, Android SDK 37.1
and connect one physical ARM64 Android 9+ phone with USB debugging. Select it
explicitly through `ANDROID_SERIAL`. Run:

```bash
ANDROID_SERIAL=<authorized-physical-device> \
  bash scripts/run_android_device_certification.sh
```

The script refuses absent/unapproved devices, non-ARM64 devices, known
emulators, Gradle build failure, missing APK outputs, or failed instrumentation.
The receipt contains **no device serial or raw fingerprint**; it hashes the
build fingerprint and prints only API and ABI for reproducibility.

## Release candidate sign-offs still requiring a tester

- Authenticate each proposed write with a real enrolled biometric and
  device credential, including denial and cancellation. Confirm no pending
  approval is accepted by a different task or after process restart.
- Import a vetted publisher-signed LiteRT model; reject wrong signature,
  expired/revoked metadata, wrong ABI/runtime and modified bytes.
- Interrupt a staged model installation or promotion; confirm prior model
  recovery and no orphaned large staged/rollback files.
- Capture available memory, thermal status, battery and storage on all target
  device classes with a signed model's actual resource requirements.
- Simulate exhausted storage, background/foreground transitions, thermal
  throttling and GPU fallback. Require bounded latency and no data disclosure.
- Confirm no Internet permission in both demo and LiteRT variants, and that
  device backup/export cannot expose notes, credentials or audit data.
- Verify encrypted event/session restore and denial after intentional data
  tampering, device sleep, and user lock transitions.
- Record build commit, model fingerprint, device-class classification and
  pass/fail evidence in a controlled test report with no customer secrets.

Do not claim hardware certification from compilation or emulator-only tests.
