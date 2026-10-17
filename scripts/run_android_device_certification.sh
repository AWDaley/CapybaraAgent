#!/usr/bin/env bash
# Requires an explicitly chosen, physical ARM64 Android device.
# Exits nonzero rather than reporting a partial 'pass' on missing device tests.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the physical phone selected for certification}"
command -v adb >/dev/null || { echo "adb is required" >&2; exit 2; }

adb_device=(adb -s "$ANDROID_SERIAL")
state="$("${adb_device[@]}" get-state 2>/dev/null || true)"
[[ "$state" == "device" ]] || { echo "Device is unavailable, unauthorized, or offline" >&2; exit 2; }
api="$("${adb_device[@]}" shell getprop ro.build.version.sdk | tr -d '\r')"
abi="$("${adb_device[@]}" shell getprop ro.product.cpu.abi | tr -d '\r')"
[[ "$api" =~ ^[0-9]+$ ]] && ((api >= 28)) || { echo "Android API is below minimum 28" >&2; exit 3; }
[[ "$abi" == "arm64-v8a" ]] || { echo "Expected a physical arm64-v8a certification device, got $abi" >&2; exit 3; }

# Emulators are useful for CI but are NOT physical device certification.
hardware="$("${adb_device[@]}" shell getprop ro.hardware | tr -d '\r' | tr '[:upper:]' '[:lower:]')"
case "$hardware" in
  ranchu|goldfish|qemu*|vbox86) echo "Emulator detected; physical device required" >&2; exit 3;;
esac

cd "$repo_root/mobile"
bash ./gradlew --no-daemon :tal-core:test :app:assembleDemoDebug :app:assembleDemoDebugAndroidTest

app_apk="app/build/outputs/apk/demo/debug/app-demo-debug.apk"
test_apk="app/build/outputs/apk/androidTest/demo/debug/app-demo-debug-androidTest.apk"
[[ -f "$app_apk" && -f "$test_apk" ]] || { echo "Expected APK outputs not found" >&2; exit 4; }
"${adb_device[@]}" install -r "$app_apk"
"${adb_device[@]}" install -r "$test_apk"

result_log="$(mktemp)"
trap 'rm -f "$result_log"' EXIT
set +e
"${adb_device[@]}" shell am instrument -w \
    com.tervoro.capybara.demo.test/androidx.test.runner.AndroidJUnitRunner \
    | tee "$result_log"
cmd_status=${PIPESTATUS[0]}
set -e

if ((cmd_status != 0)) || ! grep -Eq 'OK \([0-9]+ tests?\)' "$result_log" \
   || grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|shortMsg=Process crashed' "$result_log"; then
  echo "Device instrumentation did not pass all tests" >&2
  exit 5
fi

# Do not print/store the serial or full build fingerprint in the receipt.
fingerprint_hash="$("${adb_device[@]}" shell getprop ro.build.fingerprint | tr -d '\r' | sha256sum | cut -d' ' -f1)"
printf '%s\n' "Device certification passed: API=$api ABI=$abi fingerprint_sha256=$fingerprint_hash"
printf '%s\n' "Manual sign-offs still required: real biometric approve/deny/cancel, model import+rollback,"
printf '%s\n' "GPU/CPU fallback, low memory/storage, thermal throttle, and signed production model validation."
