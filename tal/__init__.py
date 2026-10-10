"""TAL (Task Abstraction Language) enforcement layer for Capybara."""

TAL_VERSION = "1.0.0"

from .action_gate import (
    ActionGate,
    GateResult,
)
from .budget import (
    BudgetLimits,
    BudgetTracker,
)
from .capability import (
    CapabilityEnvelope,
    compute_envelope,
)
from .context_packer import (
    ContextPacker,
    ExecutionPhase,
)
from .effect_classes import (
    EFFECT_APPROVAL_MAP,
    TOOL_EFFECTS,
    ApprovalPolicy,
    EffectClass,
    get_approval_policy,
    get_effect_class,
)
from .epistemic import (
    EpistemicFact,
    EpistemicState,
    EpistemicStore,
)
from .event_store import (
    EventLog,
    TaskEvent,
    TaskState,
    state_reducer,
)
from .execution import (
    ExecutionErrorCode,
    ToolResult,
    classify_legacy_tool_output,
)
from .manifest import (
    TaskManifest,
    to_canonical_json,
)
from .materializer import (
    OutputMaterializer as OutputMaterializer,
)
from .pipeline_runner import (
    PipelineExecutionResult as PipelineExecutionResult,
    StepTelemetry as StepTelemetry,
    StructuredPipelineRunner as StructuredPipelineRunner,
)
from .proposal_types import (
    ActionProposal,
    CompleteProposal,
    EscalateProposal,
    Proposal,
    ProposalProtocolError,
    QueryProposal,
    parse_proposal,
    parse_strict_proposal,
)
from .repair import (
    MAX_REPAIR_ATTEMPTS,
    repair_and_parse,
    repair_json_string,
)
from .recovery import (
    RecoveryCategory,
    RecoveryDiagnostic,
    diagnose_tool_result,
    diagnose_verification_messages,
)
from .schemas import (
    CalcParams,
    ConvertUnitsParams,
    CountWordsParams,
    HelpParams,
    ListFilesParams,
    OutputSpec as OutputSpec,
    PipelineStep as PipelineStep,
    PythonReplParams,
    ReadFileParams,
    ReadUrlParams,
    RecallParams,
    RememberParams,
    RunCommandParams,
    SchemaViolationError,
    StructuredPipeline as StructuredPipeline,
    TimeParams,
    ToolParamSchema,
    WebSearchParams,
    WriteFileParams,
    get_schema_for_tool,
    validate_tool_args,
)
from .slm_profile import (
    build_slm_system_prompt,
    build_standard_system_prompt,
    is_slm_model,
)
from .task_graph import (
    TaskGraph,
    TaskGraphExecutionResult,
    TaskGraphNode,
    TaskGraphRunner,
    TaskGraphValidationError,
)
from .verification import (
    ASTSyntaxCheck as ASTSyntaxCheck,
    CrossEntityConsistencyCheck as CrossEntityConsistencyCheck,
    ExitCodeCheck,
    FileExistsCheck,
    JSONSchemaCheck as JSONSchemaCheck,
    NonEmptyOutputCheck,
    RegexMatchCheck,
    REPLGraphCheck,
    REPLVariableCheck as REPLVariableCheck,
    VerificationCriterion,
    create_criterion_from_dict,
    run_verification,
)
from .artifact_catalog import (
    ArtifactCatalog,
    ArtifactRecord,
)
from .bounded_search import (
    BoundedSearch,
    SearchEvaluation,
    SearchResult,
)
from .repository_index import (
    RepositoryIndex,
    SymbolRecord,
)
from .trace_dataset import (
    TraceDataset,
    TraceExample,
    sanitize_trace_value,
)

__all__ = [
    "EFFECT_APPROVAL_MAP",
    "MAX_REPAIR_ATTEMPTS",
    "TAL_VERSION",
    "TOOL_EFFECTS",
    "ActionGate",
    "ArtifactCatalog",
    "ArtifactRecord",
    "BoundedSearch",
    "ActionProposal",
    "ApprovalPolicy",
    "BudgetLimits",
    "BudgetTracker",
    "CalcParams",
    "CapabilityEnvelope",
    "CompleteProposal",
    "ContextPacker",
    "ConvertUnitsParams",
    "CountWordsParams",
    "EffectClass",
    "EpistemicFact",
    "EpistemicState",
    "EpistemicStore",
    "EscalateProposal",
    "EventLog",
    "ExecutionErrorCode",
    "ExecutionPhase",
    "ExitCodeCheck",
    "FileExistsCheck",
    "GateResult",
    "HelpParams",
    "ListFilesParams",
    "NonEmptyOutputCheck",
    "Proposal",
    "ProposalProtocolError",
    "PythonReplParams",
    "QueryProposal",
    "ReadFileParams",
    "ReadUrlParams",
    "RecallParams",
    "RegexMatchCheck",
    "REPLGraphCheck",
    "RememberParams",
    "RecoveryCategory",
    "RecoveryDiagnostic",
    "RepositoryIndex",
    "RunCommandParams",
    "SchemaViolationError",
    "SearchEvaluation",
    "SearchResult",
    "TaskEvent",
    "TaskGraph",
    "TaskGraphExecutionResult",
    "TaskGraphNode",
    "TaskGraphRunner",
    "TaskGraphValidationError",
    "TaskManifest",
    "TaskState",
    "TraceDataset",
    "TraceExample",
    "TimeParams",
    "ToolParamSchema",
    "ToolResult",
    "SymbolRecord",
    "VerificationCriterion",
    "WebSearchParams",
    "WriteFileParams",
    "build_slm_system_prompt",
    "build_standard_system_prompt",
    "compute_envelope",
    "classify_legacy_tool_output",
    "create_criterion_from_dict",
    "diagnose_tool_result",
    "diagnose_verification_messages",
    "get_approval_policy",
    "get_effect_class",
    "get_schema_for_tool",
    "is_slm_model",
    "parse_proposal",
    "parse_strict_proposal",
    "repair_and_parse",
    "repair_json_string",
    "run_verification",
    "BenchmarkCase",
    "BenchmarkScorecard",
    "BenchmarkSuite",
    "BenchmarkTrial",
    "SLMBenchmarkRunner",
    "load_benchmark_suite",
    "save_scorecard",
    "sanitize_trace_value",
    "state_reducer",
    "to_canonical_json",
    "validate_tool_args",
]


# Benchmark support depends on ``tal_test_runner``, which in turn depends on
# ``agent``.  Loading it eagerly here makes importing any ``tal.*`` module
# recurse back into a partially initialized ``agent`` module.  Keep the
# package-level API while loading these optional, runner-backed exports only
# when they are actually requested.
_BENCHMARK_EXPORTS = {
    "BenchmarkCase",
    "BenchmarkScorecard",
    "BenchmarkSuite",
    "BenchmarkTrial",
    "SLMBenchmarkRunner",
    "load_benchmark_suite",
    "save_scorecard",
}


def __getattr__(name: str):
    if name in _BENCHMARK_EXPORTS:
        from . import benchmark

        value = getattr(benchmark, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
