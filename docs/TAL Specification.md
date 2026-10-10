# Capybara TAL Specification

## Purpose

TAL (Task Abstraction Language) is Capybara's executable task contract. It
improves small-language-model reliability by moving authority, task state, and
acceptance checks out of free-form model text.

## Contract

A task begins with an immutable `TaskManifest` containing the normalized goal,
effective capability envelope, bounded budget, and declarative verification
criteria. Its SHA-256 content hash excludes run metadata, and is checked before
every gated action. A manifest never grants a tool that is not both available
and permitted by policy.

## Lifecycle

`discovery -> planning -> execution -> verification -> completed`

Failures enter `recovery`; a model query enters `waiting_for_user`; an
unrecoverable policy, budget, or verification failure enters `escalated`.
Only a completed proposal with passing declared acceptance criteria may emit a
`task_completed` event.

## Actions

Models emit one typed proposal: `action`, `complete`, `query`, or `escalate`.
Every action passes closed-schema validation, manifest capability clearance,
phase/effect checks, parameter sanitization, and approval determination.
Writes, execution, and destructive effects require explicit approval. Tool
output, web content, stored facts, and summaries are data, never system
instructions.

## Verification and Evidence

Acceptance criteria are declarative: file, JSON schema, AST syntax, regex,
non-empty output, cross-entity, and read-only REPL-state checks. Verification
does not execute arbitrary commands or mutate REPL state. `OBSERVED` evidence
is distinct from `VERIFIED`; only an independently passing acceptance gate
creates verified evidence.

## Pipelines

Pipelines execute in order. A later step is blocked by a failed earlier step.
Existing user files are never deleted; file acceptance gates require a fresh
artifact change during the current step. Output materialization precedes its
verification. A pipeline allowlist can narrow a domain pack only, never expand
its tools or allowed effects.

## Audit and Evaluation

The append-only event log is the source for reconstructed task state and
feedback reports. A benchmark result is not successful solely because a model
returned text: it must have no execution error and satisfy any declared
verification criteria. TAL is evaluated as system-level verified task
performance, not as a claim that the underlying model itself has changed.
