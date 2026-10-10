package com.tervoro.tal

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

internal val StrictJson = Json {
    ignoreUnknownKeys = false
    isLenient = false
    allowTrailingComma = false
    explicitNulls = true
}

object CanonicalJson {
    fun encode(value: JsonElement): String = when (value) {
        is JsonObject -> value.entries
            .sortedBy { it.key }
            .joinToString(prefix = "{", postfix = "}", separator = ",") { (key, child) ->
                "${JsonPrimitive(key)}:${encode(child)}"
            }

        is JsonArray -> value.joinToString(prefix = "[", postfix = "]", separator = ",") { encode(it) }
        is JsonPrimitive -> value.toString()
        JsonNull -> "null"
    }

    fun objectOf(vararg fields: Pair<String, JsonElement>): JsonObject = JsonObject(linkedMapOf(*fields))
}

fun Map<String, JsonElement>.string(name: String): String? =
    (get(name) as? JsonPrimitive)?.takeIf { it.isString }?.content

fun Map<String, JsonElement>.integer(name: String): Int? =
    (get(name) as? JsonPrimitive)?.content?.toIntOrNull()

fun Map<String, JsonElement>.boolean(name: String): Boolean? =
    (get(name) as? JsonPrimitive)?.content?.toBooleanStrictOrNull()
