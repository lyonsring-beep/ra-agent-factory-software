from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from ra_agent_studio.application.studio import StudioService
from ra_agent_studio.domain.production import ProductionState
from ra_agent_studio.infra.sqlite import SQLiteStateStore
from tests.support import ContractTestFactoryRuntime, authority_registry


def _service(tmp_path: Path) -> StudioService:
    return StudioService(
        db_path=str(tmp_path / "governance.db"),
        authority_registry=authority_registry(),
        factory_runtime=ContractTestFactoryRuntime(),
    )


def _full_candidate(service: StudioService):
    service.create_module_revision(
        module_id="m", revision_id="r1", name="M", content="print('x')",
        actor_principal_id="builder", provided_capabilities=("answer",), identity_domain="m",
    )
    service.compose("c1", ["r1"], actor_principal_id="builder")
    _, candidate=service.build("c1",actor_principal_id="builder",workspace_id="ws",lineage_id="lineage-1")
    return candidate


def test_main_authority_path_uses_exact_pr08_to_pr17_states(tmp_path: Path) -> None:
    service=_service(tmp_path)
    candidate=_full_candidate(service)
    run_id=f"production-run:{candidate.candidate_id.value}"
    assert service.snapshot()["production_runs"][0]["current_state"] == ProductionState.PR_09_IMPLEMENTATION_CANDIDATE.value
    review=service.review(
        candidate_id=candidate.candidate_id.value,reviewer_principal_id="reviewer",
        review_method="external_ai",passed=True,
    )
    assert service.store.get("production_run",run_id)["current_state"] == ProductionState.PR_15_IMPLEMENTATION_APPROVED.value
    freeze=service.freeze(candidate_id=candidate.candidate_id.value,review_id=review.review_id,actor_principal_id="freezer")
    assert service.store.get("production_run",run_id)["current_state"] == ProductionState.PR_16_IMPLEMENTATION_FROZEN.value
    service.create_baseline(
        baseline_id="b1",lineage_id="lineage-1",frozen_artifact_id=freeze.frozen_artifact.id.value,
        expected_predecessor_baseline_id=None,actor_principal_id="promoter",
    )
    assert service.store.get("production_run",run_id)["current_state"] == ProductionState.PR_17_RUN_COMPLETE.value
    transitions=service.store.list("production_run")
    assert transitions[0]["consistency_version"] == 5  # PR08→09→10→15→16→17


def test_candidate_bytes_and_exact_closure_are_immutable_at_freeze(tmp_path: Path) -> None:
    service=_service(tmp_path)
    candidate=_full_candidate(service)
    blob=service.store.get_blob(candidate.artifact_blob_hash.value)
    assert candidate.candidate_hash.value == __import__("hashlib").sha256(blob).hexdigest()
    closure=service.store.get_immutable("candidate_closure",candidate.candidate_id.value)
    assert closure["logical_payload_identity"] == candidate.logical_payload_identity.value
    assert closure["manifest_identity"] == candidate.manifest_identity.value
    review=service.review(candidate_id=candidate.candidate_id.value,reviewer_principal_id="reviewer",review_method="external_ai",passed=True)
    frozen=service.freeze(candidate_id=candidate.candidate_id.value,review_id=review.review_id,actor_principal_id="freezer")
    freeze_closure=service.store.get_immutable("freeze_closure",frozen.frozen_artifact.id.value)
    assert freeze_closure["artifact_blob_hash"] == candidate.artifact_blob_hash.value
    with pytest.raises(ValueError,match="immutable record mutation"):
        service.store.add_immutable("candidate_closure",candidate.candidate_id.value,{"tamper":True})


def test_pointer_fencing_and_expected_version_fail_closed(tmp_path: Path) -> None:
    store=SQLiteStateStore(str(tmp_path/"state.db"))
    with store.transaction():
        token1=store.acquire_fencing_token("lineage","owner-1")
        v1=store.compare_and_set_pointer(
            "current_baseline","lineage",expected_value=None,new_value="b1",
            expected_version=0,fencing_token=token1,
        )
    assert v1 == 1
    with pytest.raises(PermissionError,match="already held"):
        with store.transaction():
            store.acquire_fencing_token("lineage","owner-2")
    with store.transaction():
        store.release_promotion_lock("lineage",holder="owner-1",fencing_token=token1)
        token2=store.acquire_fencing_token("lineage","owner-2")
    with pytest.raises(PermissionError,match="stale fencing token"):
        with store.transaction():
            store.compare_and_set_pointer(
                "current_baseline","lineage",expected_value="b1",new_value="b2",
                expected_version=1,fencing_token=token1,
            )
    with pytest.raises(PermissionError,match="ExpectedConsistencyVersion"):
        with store.transaction():
            store.compare_and_set_pointer(
                "current_baseline","lineage",expected_value="b1",new_value="b2",
                expected_version=0,fencing_token=token2,
            )


def test_idempotency_and_recovery_epoch_reject_stale_commands(tmp_path: Path) -> None:
    store=SQLiteStateStore(str(tmp_path/"state.db"))
    request={"target":"x","action":"freeze"}
    with store.transaction():
        store.record_idempotency("idem-1","cmd-1",request,"freeze","f1")
        store.record_idempotency("idem-1","cmd-1",request,"freeze","f1")
        assert store.bump_recovery_epoch() == 2
    with pytest.raises(PermissionError,match="stale recovery epoch"):
        with store.transaction():
            store.record_idempotency("idem-1","cmd-1",request,"freeze","f1")


def test_audit_chain_detects_tamper(tmp_path: Path) -> None:
    db=tmp_path/"state.db"
    store=SQLiteStateStore(str(db))
    with store.transaction():
        store.append_audit(
            event_id="a1",actor_principal_id="p",action="x",subject_kind="k",subject_id="1",
            metadata={"v":1},occurred_at=datetime.now(UTC),
        )
        store.append_audit(
            event_id="a2",actor_principal_id="p",action="y",subject_kind="k",subject_id="2",
            metadata={"v":2},occurred_at=datetime.now(UTC),
        )
    assert len(store.list_audit()) == 2
    store._conn.execute("UPDATE audit_events SET metadata='{}' WHERE event_id='a1'")
    with pytest.raises(RuntimeError,match="audit integrity"):
        store.list_audit()
