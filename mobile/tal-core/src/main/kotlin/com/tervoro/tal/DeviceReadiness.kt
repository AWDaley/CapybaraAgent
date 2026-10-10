package com.tervoro.tal

data class DeviceProfile(
    val androidApi: Int,
    val abi: String,
    val availableRamBytes: Long,
    val availableStorageBytes: Long,
    val batteryPercent: Int,
    val thermalStatus: Int,
    val isDeviceLocked: Boolean,
)
data class ModelResourceRequirements(val minimumRamBytes: Long, val minimumStorageBytes: Long, val minimumBatteryPercent: Int = 15)

object DeviceReadiness {
    /** Returns stable fail-closed codes suitable for a user-facing availability explanation. */
    fun evaluate(profile: DeviceProfile, resources: ModelResourceRequirements): List<String> = buildList {
        if (profile.androidApi < 28) add("DEVICE_ANDROID_API_UNSUPPORTED")
        if (profile.abi != "arm64-v8a") add("DEVICE_ABI_UNSUPPORTED")
        if (profile.availableRamBytes < resources.minimumRamBytes) add("DEVICE_MEMORY_INSUFFICIENT")
        if (profile.availableStorageBytes < resources.minimumStorageBytes) add("DEVICE_STORAGE_INSUFFICIENT")
        if (profile.batteryPercent !in resources.minimumBatteryPercent..100) add("DEVICE_BATTERY_INSUFFICIENT")
        if (profile.thermalStatus >= THERMAL_SEVERE) add("DEVICE_THERMAL_UNSAFE")
        if (profile.isDeviceLocked) add("DEVICE_LOCKED")
    }
    private const val THERMAL_SEVERE = 4
}
