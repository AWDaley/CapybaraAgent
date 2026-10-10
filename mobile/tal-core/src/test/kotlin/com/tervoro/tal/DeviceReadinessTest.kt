package com.tervoro.tal

import kotlin.test.Test
import kotlin.test.assertEquals

class DeviceReadinessTest {
    @Test fun `resource and thermal conditions fail closed`() {
        val profile = DeviceProfile(36, "arm64-v8a", 1, 1, 10, 4, false)
        assertEquals(listOf("DEVICE_MEMORY_INSUFFICIENT", "DEVICE_STORAGE_INSUFFICIENT", "DEVICE_BATTERY_INSUFFICIENT", "DEVICE_THERMAL_UNSAFE"),
            DeviceReadiness.evaluate(profile, ModelResourceRequirements(2, 2)))
    }
}
