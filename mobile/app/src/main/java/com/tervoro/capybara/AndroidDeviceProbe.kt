package com.tervoro.capybara

import android.app.ActivityManager
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import com.tervoro.tal.DeviceProfile

/**
 * Reports only coarse device capabilities; no stable hardware identifiers,
 * contact data, account names or file contents are collected.
 *
 * This does not certify that a specific model fits RAM/thermal budgets.
 * Signed model/resource manifest requirements must be compared separately.
 */
object AndroidDeviceProbe {
    fun capture(context: Context): DeviceProfile {
        val memory = ActivityManager.MemoryInfo()
        val activity = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        activity.getMemoryInfo(memory)
        val batteryIntent = context.registerReceiver(
            null, IntentFilter(Intent.ACTION_BATTERY_CHANGED),
        )
        val level = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val batteryPercent = if (scale > 0 && level >= 0) (level * 100 / scale) else -1
        val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager

        return DeviceProfile(
            androidApi = Build.VERSION.SDK_INT,
            abi = Build.SUPPORTED_ABIS.firstOrNull().orEmpty(),
            availableRamBytes = memory.availMem,
            availableStorageBytes = context.noBackupFilesDir.usableSpace,
            batteryPercent = batteryPercent,
            thermalStatus = if (Build.VERSION.SDK_INT >= 29) power.currentThermalStatus else 0,
            isDeviceLocked = keyguard.isDeviceLocked,
        )
    }
}
