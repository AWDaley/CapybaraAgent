package com.tervoro.tal

import java.time.Instant
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Compiles a registered mobile task to the frozen TAL 0.3 profile manifest. */
object MobileProfileManifestCompiler {
    fun compile(draft: TaskContractDraft, now: Instant = Instant.now()): JsonObject {
        val target = draft.sourceRefs.first()
        val outcome = if (draft.templateId == "document.summary") "summary_delivered" else "answer_delivered"
        val condition = draft.successConditionId
        fun obj(vararg values: Pair<String, kotlinx.serialization.json.JsonElement>) = CanonicalJson.objectOf(*values)
        fun arr(vararg values: kotlinx.serialization.json.JsonElement) = JsonArray(values.toList())
        val root = linkedMapOf<String, kotlinx.serialization.json.JsonElement>(
            "tal_version" to JsonPrimitive(MobileProfileContract.TAL_VERSION), "grammar_id" to JsonPrimitive(MobileProfileContract.GRAMMAR_ID),
            "schema_id" to JsonPrimitive(MobileProfileContract.MANIFEST_SCHEMA_ID), "domain_pack" to JsonPrimitive(MobileProfileContract.DOMAIN_PACK_ID),
            "request" to obj("request_id" to JsonPrimitive("request:${draft.templateId.replace('.', '-')}") , "submitted_by" to JsonPrimitive("user:local-owner"), "submitted_at" to JsonPrimitive(now.toString()), "channel" to JsonPrimitive("mobile")),
            "scope" to obj("scope_id" to JsonPrimitive("scope:${draft.templateId.replace('.', '-')}") , "organization_ref" to JsonPrimitive("organization:personal"), "target_refs" to JsonArray(draft.sourceRefs.sorted().map(::JsonPrimitive)), "entity_declarations" to arr(obj("entity_type" to JsonPrimitive("document"), "entity_ref" to JsonPrimitive(target))), "timezone" to JsonPrimitive("UTC")),
            "goal" to obj("goal_id" to JsonPrimitive("goal:${draft.templateId.replace('.', '-')}") , "actor_ref" to JsonPrimitive("agent:tervoro-mobile"), "owner_ref" to JsonPrimitive("user:local-owner"), "target_ref" to JsonPrimitive(target), "outcome_id" to JsonPrimitive(draft.templateId)),
            "unknowns" to arr(obj("id" to JsonPrimitive("unknown:requested-answer"), "subject_ref" to JsonPrimitive(target), "field_id" to JsonPrimitive("document.answer"), "blocking" to JsonPrimitive(true))),
            "requirements" to arr(obj("id" to JsonPrimitive("requirement:evidence"), "rule_id" to JsonPrimitive("answer.material_claims_require_evidence"), "verifier_id" to JsonPrimitive("claim_citation_verifier"), "target_refs" to arr(JsonPrimitive(target)))),
            "constraints" to arr(obj("id" to JsonPrimitive("constraint:model-calls"), "kind" to JsonPrimitive("model_calls"), "maximum" to JsonPrimitive(4)), obj("id" to JsonPrimitive("constraint:external"), "kind" to JsonPrimitive("external_actions"), "maximum" to JsonPrimitive(0)), obj("id" to JsonPrimitive("constraint:time"), "kind" to JsonPrimitive("time_millis"), "maximum" to JsonPrimitive(120000))),
            "requested_capabilities" to JsonArray(draft.requestedCapabilities.sorted().mapIndexed { index, capability -> obj("id" to JsonPrimitive("capability:$index"), "action_id" to JsonPrimitive(capability), "target_ref" to JsonPrimitive(target)) }),
            "prohibited_actions" to arr(obj("id" to JsonPrimitive("prohibition:network"), "action_id" to JsonPrimitive("cloud_model.request"), "target_ref" to JsonPrimitive(target))),
            "success_conditions" to arr(obj("id" to JsonPrimitive("success:release"), "condition_id" to JsonPrimitive(condition), "terminal_outcome" to JsonPrimitive(outcome), "verification_mode" to JsonPrimitive("deterministic_validator"), "required_observation_types" to arr(JsonPrimitive(if (outcome == "summary_delivered") "verified_summary_package" else "verified_answer_package")))),
            "fallbacks" to arr(obj("id" to JsonPrimitive("fallback:insufficient-evidence"), "trigger" to JsonPrimitive("information_timeout"), "terminal_outcome" to JsonPrimitive("escalated"))),
            "output_contract" to obj("output_type" to JsonPrimitive(if (outcome == "summary_delivered") "summary_package" else "answer_package"), "required_fields" to arr(JsonPrimitive("outcome"), JsonPrimitive("evidence_summary"), JsonPrimitive("remaining_unknowns"), JsonPrimitive("audit_reference")), "format" to JsonPrimitive("mobile_ui"), "destination" to JsonPrimitive("local_ui")),
            "integrity" to obj("canonicalization" to JsonPrimitive(MobileProfileContract.CANONICALIZATION_ID), "compiler_version" to JsonPrimitive(MobileProfileContract.COMPILER_VERSION), "manifest_version" to JsonPrimitive(1), "manifest_hash" to JsonPrimitive("")),
        )
        val unsigned = JsonObject(root)
        val hash = MobileProfileContract.manifestHash(unsigned)
        root["integrity"] = obj("canonicalization" to JsonPrimitive(MobileProfileContract.CANONICALIZATION_ID), "compiler_version" to JsonPrimitive(MobileProfileContract.COMPILER_VERSION), "manifest_version" to JsonPrimitive(1), "manifest_hash" to JsonPrimitive(hash))
        return JsonObject(root).also(MobileProfileContract::validateManifest)
    }
}
