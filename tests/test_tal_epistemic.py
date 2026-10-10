from tal.epistemic import EpistemicFact, EpistemicState, EpistemicStore


def test_epistemic_fact_creation_and_states():
    fact = EpistemicFact(
        fact_id="f1",
        claim="The file data.csv contains 100 rows",
        state=EpistemicState.OBSERVED,
        source="tool:read_file",
        confidence=1.0
    )
    assert fact.state == EpistemicState.OBSERVED
    assert fact.to_dict()["state"] == "observed"


def test_epistemic_store_add_and_promote():
    store = EpistemicStore()
    fid = store.add_fact("Server is running on port 8080", state=EpistemicState.REPORTED, source="user:prompt")
    
    assert store.get_fact(fid).state == EpistemicState.REPORTED
    
    # Promote to verified
    promoted = store.promote(fid, EpistemicState.VERIFIED, source="tool:ping", turn=2)
    assert promoted is True
    assert store.get_fact(fid).state == EpistemicState.VERIFIED
    assert store.get_fact(fid).turn_verified == 2


def test_epistemic_store_filtering_and_context_string():
    store = EpistemicStore()
    store.add_fact("User is located in New York", EpistemicState.REPORTED, "user")
    store.add_fact("workspace/app.py exists", EpistemicState.OBSERVED, "tool:list_files")
    store.add_fact("Hypothesis: module uses Flask", EpistemicState.INFERRED, "model:thought")
    
    verified_and_observed = store.get_verified_facts()
    assert len(verified_and_observed) == 0
    
    ctx = store.to_context_string()
    assert "[REPORTED]" in ctx
    assert "[OBSERVED]" in ctx
    assert "[INFERRED]" in ctx


def test_conflict_marking():
    store = EpistemicStore()
    f1 = store.add_fact("Port is 8080", EpistemicState.REPORTED, "user")
    f2 = store.add_fact("Port is 9090", EpistemicState.OBSERVED, "tool:read_file")
    
    store.mark_conflicted(f1, f2, reason="Different port numbers reported")
    
    assert store.get_fact(f1).state == EpistemicState.CONFLICTED
    assert store.get_fact(f2).state == EpistemicState.CONFLICTED
    conflicts = store.detect_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0][0].claim == "Port is 8080"
