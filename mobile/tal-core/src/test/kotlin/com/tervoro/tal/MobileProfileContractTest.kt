package com.tervoro.tal

import java.io.File
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class MobileProfileContractTest {
    @Test
    fun `golden manifests have the same canonical bytes and hash in Kotlin`() {
        val fixtureDirectory = File(requireNotNull(System.getProperty("tervoro.fixtureDir")))
        val index = StrictJson.parseToJsonElement(File(fixtureDirectory, "golden-manifests.json").readText()).jsonObject
        index["fixtures"]!!.jsonArray.forEach { element ->
            val record = element.jsonObject
            val manifest = StrictJson.parseToJsonElement(
                File(fixtureDirectory, record["manifest_file"]!!.jsonPrimitive.content).readText(),
            ).jsonObject
            val canonical = CanonicalJson.encode(MobileProfileContract.manifestContract(manifest))
            assertEquals(record["expected_canonical"]!!.jsonPrimitive.content, canonical)
            assertEquals(record["expected_sha256"]!!.jsonPrimitive.content, MobileProfileContract.manifestHash(manifest))
            MobileProfileContract.validateManifest(manifest)
        }
    }

    @Test
    fun `unknown profile field fails closed before it can be accepted`() {
        val fixtureDirectory = File(requireNotNull(System.getProperty("tervoro.fixtureDir")))
        val manifest = StrictJson.parseToJsonElement(
            File(fixtureDirectory, "document-answer-manifest.unknown-field.json").readText(),
        ).jsonObject

        val error = assertFailsWith<MobileProfileValidationException> {
            MobileProfileContract.validateManifest(manifest)
        }
        assertEquals("UNKNOWN_FIELD", error.stableErrorCode)
    }
}
