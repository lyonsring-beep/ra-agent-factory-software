from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine

from ra_factory.application.build_service import CandidateBuildService, FROZEN_ARCHITECTURE_SOURCE_LOCK
from ra_factory.application.composition_service import CompositionService
from ra_factory.application.registry_service import ModuleRegistryService
from ra_factory.domain.governance.state import ProductionState
from ra_factory.domain.registry.revisions import ModuleAuthorityClass, ModuleType
from ra_factory.infrastructure.blobstore import ContentAddressedBlobStore
from ra_factory.infrastructure.postgres.models import Base, ImplementationCandidateRow, ProductionRunRow
from ra_factory.persistence.postgres import PostgresUnitOfWork, RecoveryRepository


FACTORY_COMMIT = "bc0568926ef70ea6fa7e5e6cc8287c09e041fb4f"
FACTORY_CANDIDATE_SHA256 = "8387b7aa27d39be56a4f1e28ae979f9f233b1f29c196b5339c1b40dd6fdfec7b"
FACTORY_FROZEN_PACKAGE_SHA256 = "df04ac7cc938be23d7652fa8424dd50f220ed95941c1e6290e689c04bbaceeaa"
FACTORY_FROZEN_ARTIFACT_ID = 10334979844
FACTORY_FROZEN_RUN_ID = 34813046629


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require_exact_frozen_inputs(request: dict) -> tuple[Path, Path]:
    if request.get("expected_factory_commit") != FACTORY_COMMIT:
        raise RuntimeError("STUDIO_EXPECTED_FACTORY_COMMIT_MISMATCH")
    if request.get("expected_factory_candidate_sha256") != FACTORY_CANDIDATE_SHA256:
        raise RuntimeError("STUDIO_EXPECTED_FACTORY_CANDIDATE_MISMATCH")
    if request.get("expected_factory_frozen_package_sha256") != FACTORY_FROZEN_PACKAGE_SHA256:
        raise RuntimeError("STUDIO_EXPECTED_FACTORY_FROZEN_PACKAGE_MISMATCH")

    repo_root = Path(os.environ["RA_FACTORY_V111_REPO_ROOT"]).resolve()
    actual_commit = subprocess.check_output(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual_commit != FACTORY_COMMIT:
        raise RuntimeError(f"FACTORY_CHECKOUT_NOT_EXACT_V111:{actual_commit}")

    candidate_zip = Path(os.environ["RA_FACTORY_V111_CANDIDATE_ZIP"]).resolve()
    if sha256_file(candidate_zip) != FACTORY_CANDIDATE_SHA256:
        raise RuntimeError("FACTORY_V111_CANDIDATE_BYTES_MISMATCH")

    attestation = Path(os.environ["RA_FACTORY_V111_FROZEN_PACKAGE_ATTESTATION"]).resolve()
    data = json.loads(attestation.read_text(encoding="utf-8"))
    expected = {
        "artifact_id": FACTORY_FROZEN_ARTIFACT_ID,
        "run_id": FACTORY_FROZEN_RUN_ID,
        "artifact_name": "RA_AGENT_FACTORY_v1_11_STANDALONE_IR_B06_EVIDENCE_V8_FROZEN",
        "artifact_digest_sha256": FACTORY_FROZEN_PACKAGE_SHA256,
        "factory_commit": FACTORY_COMMIT,
        "factory_candidate_sha256": FACTORY_CANDIDATE_SHA256,
    }
    if any(data.get(k) != v for k, v in expected.items()):
        raise RuntimeError("FACTORY_V111_FROZEN_PACKAGE_ATTESTATION_MISMATCH")
    return candidate_zip, attestation


def template_parameters(module_revision_ids: tuple[str, ...], capability_bindings: dict[str, str]) -> dict[str, object]:
    return {
        "AGENT_PACKAGE": "ra_agent_studio_realized_agent",
        "OUTPUT_TYPE": "dict[str, object]",
        "REQUEST_TYPE": "dict[str, object]",
        "OUTPUT_INTEGRITY_CLASS": "OIC-2",
        "OUTPUT_INTEGRITY_RATIONALE": "Exact Studio composition realized by frozen Factory v1.11",
        "THREAT_MODEL_REF": "ra-agent-studio:factory-v1.11-integration",
        "FINALIZATION_MECHANISM": "factory-controlled-finalization",
        "HOSTILE_TESTS": "studio-live-factory-integration",
        "AGENT_SPECIFIC_EXECUTION": "return request",
        "ROLE_REF": "ra-agent-studio:realized-agent",
        "IMPLEMENTATION_REF": "ra-agent-studio:implementation-repair-v1_02",
        "REQUIRED_MODULES": repr(module_revision_ids),
        "EXTENSION_NAMESPACE": "ra_agent_studio",
        "AGENT_SPECIFIC_CAPABILITY_BINDINGS": repr(dict(sorted(capability_bindings.items()))),
        "AGENT_SPECIFIC_BOOTSTRAP_GUARDS": "()",
        "INSTRUCTION_REF": "ra-agent-studio:canonical-instructions",
    }


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: factory_v111_bridge.py REQUEST_JSON RESPONSE_JSON")
    request_path = Path(sys.argv[1]).resolve()
    response_path = Path(sys.argv[2]).resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    candidate_zip, frozen_attestation = require_exact_frozen_inputs(request)

    work = response_path.parent / "factory-v111-live"
    work.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite+pysqlite:///{work / 'factory.db'}", future=True)
    Base.metadata.create_all(engine)
    uow = PostgresUnitOfWork(engine)
    RecoveryRepository(uow).initialize(1)
    blobstore = ContentAddressedBlobStore(work / "blobs")

    factory_revisions: list[str] = []
    studio_to_factory: dict[str, str] = {}
    registry = ModuleRegistryService(uow, blobstore)
    for binding in request["bindings"]:
        content = base64.b64decode(binding["content_base64"], validate=True)
        studio_content_hash = binding["studio_content_hash"]
        module_type_name = binding.get("module_type", "")
        authority_class_name = binding.get("authority_class", "")
        if not hasattr(ModuleType, module_type_name) or not hasattr(ModuleAuthorityClass, authority_class_name):
            raise RuntimeError(f"SHARED_CHANGE_REQUIRED_STOP: unsupported frozen Factory authority classification:{module_type_name}:{authority_class_name}")
        module_type = getattr(ModuleType, module_type_name)
        authority_class = getattr(ModuleAuthorityClass, authority_class_name)
        revision = registry.create_revision(
            object_id=f"studio:{binding['module_id']}",
            content=content,
            module_type=module_type,
            authority_class=authority_class,
            predecessor_revision_id=None,
            principal_ref="studio-build-principal",
            workspace_ref="studio-live-integration",
            frozen=False,
        )
        factory_revisions.append(revision.revision_id.value)
        studio_to_factory[binding["studio_revision_id"]] = revision.revision_id.value
        if not studio_content_hash or len(studio_content_hash) != 64:
            raise RuntimeError("STUDIO_MODULE_IDENTITY_MISSING")

    required_capabilities: dict[str, str] = {}
    request_by_revision={b["studio_revision_id"]: b for b in request["bindings"]}
    for entry in request.get("capability_bindings", []):
        capability=str(entry["capability"])
        studio_revision_id=str(entry["studio_revision_id"])
        provider_binding=request_by_revision.get(studio_revision_id)
        if provider_binding is None:
            raise RuntimeError(f"FACTORY_CAPABILITY_PROVIDER_REVISION_UNKNOWN:{capability}:{studio_revision_id}")
        if capability not in provider_binding.get("provided_capabilities", []):
            raise RuntimeError(f"FACTORY_CAPABILITY_PROVIDER_CONTRACT_MISMATCH:{capability}:{studio_revision_id}")
        required_capabilities[capability]=studio_to_factory[studio_revision_id]
    all_required={cap for b in request["bindings"] for cap in b.get("required_capabilities", [])}
    if set(required_capabilities) != all_required:
        raise RuntimeError(
            f"FACTORY_EXACT_CAPABILITY_BINDING_SET_MISMATCH:expected={sorted(all_required)}:actual={sorted(required_capabilities)}"
        )
    binding_canonical="\n".join(
        f"{entry['capability']}:{entry['studio_revision_id']}"
        for entry in sorted(request.get("capability_bindings", []),key=lambda x:(x["capability"],x["studio_revision_id"]))
    ).encode("utf-8")
    binding_identity=hashlib.sha256(binding_canonical).hexdigest()
    if binding_identity != request.get("capability_binding_identity"):
        raise RuntimeError("FACTORY_CAPABILITY_BINDING_IDENTITY_MISMATCH")

    realized = CompositionService(uow).realize(
        module_revision_ids=tuple(factory_revisions),
        required_capabilities=required_capabilities,
    )
    if realized.integrity_standing.value != "INTEGRITY_MATCH":
        raise RuntimeError("FACTORY_REALIZATION_INTEGRITY_NOT_MATCHED")

    production_run_id = "studio-live-factory-v111"
    with uow.transaction() as session:
        session.add(
            ProductionRunRow(
                production_run_id=production_run_id,
                current_state=ProductionState.PR_08_IMPLEMENTATION_IN_PROGRESS.value,
                current_standing_record_id=None,
                current_consistency_version=0,
                recovery_epoch=1,
            )
        )

    candidate = CandidateBuildService(uow, blobstore).build(
        composition_id=realized.composition_id,
        agent_requirement_ref=request["agent_requirement_ref"],
        architecture_source_lock_ref=FROZEN_ARCHITECTURE_SOURCE_LOCK,
        production_run_id=production_run_id,
        template_parameters=template_parameters(tuple(factory_revisions), required_capabilities),
        principal_ref="studio-build-principal",
        workspace_ref="studio-live-integration",
    )
    with uow.transaction() as session:
        row = session.get(ImplementationCandidateRow, candidate.revision_id.value)
        if row is None:
            raise RuntimeError("FACTORY_IMPLEMENTATION_CANDIDATE_NOT_PERSISTED")
        artifact_bytes = blobstore.get(row.candidate_blob_id)
        persisted = {
            "candidate_revision_id": row.revision_id,
            "logical_payload_identity": row.logical_payload_identity,
            "manifest_identity": row.manifest_identity,
            "build_input_snapshot_id": row.build_input_snapshot_id,
            "candidate_blob_id": row.candidate_blob_id,
            "standard_template_artifact_ref": row.standard_template_artifact_ref,
            "standard_template_artifact_sha256": row.standard_template_artifact_sha256,
            "standard_template_manifest_identity": row.standard_template_manifest_identity,
            "production_standard_ref": row.production_standard_ref,
        }

    artifact_path = work / "factory-produced-studio-candidate.zip"
    artifact_path.write_bytes(artifact_bytes)
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    evidence = {
        "schema_version": "RA_AGENT_STUDIO_FACTORY_V111_LIVE_EVIDENCE_V2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "factory_runtime_commit": FACTORY_COMMIT,
        "factory_frozen_candidate_sha256": FACTORY_CANDIDATE_SHA256,
        "factory_frozen_candidate_size": candidate_zip.stat().st_size,
        "factory_frozen_package_sha256": FACTORY_FROZEN_PACKAGE_SHA256,
        "factory_frozen_package_artifact_id": FACTORY_FROZEN_ARTIFACT_ID,
        "factory_frozen_package_run_id": FACTORY_FROZEN_RUN_ID,
        "frozen_package_attestation": json.loads(frozen_attestation.read_text(encoding="utf-8")),
        "studio_composition_id": request["studio_composition_id"],
        "studio_composition_hash": request["studio_composition_hash"],
        "studio_agent_requirement_ref": request["agent_requirement_ref"],
        "studio_agent_authority_boundary_ref": request["agent_authority_boundary_ref"],
        "factory_realized_composition_id": realized.composition_id,
        "factory_realized_composition_hash": realized.composition_hash,
        "factory_realization_fingerprint": realized.realization_fingerprint,
        "factory_realization_integrity": realized.integrity_standing.value,
        "factory_implementation_candidate": persisted,
        "factory_produced_artifact_sha256": artifact_sha,
        "module_identity_map": studio_to_factory,
        "studio_capability_binding_identity": request.get("capability_binding_identity"),
        "studio_capability_bindings": request.get("capability_bindings", []),
        "factory_capability_bindings": required_capabilities,
        "module_authority_contract": [
            {
                "module_id": b["module_id"],
                "module_type": b["module_type"],
                "authority_class": b["authority_class"],
                "editability": b["editability"],
                "agent_requirement_ref": b["agent_requirement_ref"],
                "agent_authority_boundary_ref": b["agent_authority_boundary_ref"],
            }
            for b in request["bindings"]
        ],
        "reproducibility_basis": "exact frozen Factory v1.11 package digest and exact candidate identity",
    }
    evidence_path = work / "factory-v111-live-evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    response = {
        "factory_runtime_commit": FACTORY_COMMIT,
        "factory_candidate_sha256": FACTORY_CANDIDATE_SHA256,
        "factory_frozen_package_sha256": FACTORY_FROZEN_PACKAGE_SHA256,
        "artifact_path": str(artifact_path.resolve()),
        "artifact_sha256": artifact_sha,
        "evidence_path": str(evidence_path.resolve()),
        "reproducible": True,
    }
    response_path.write_text(json.dumps(response, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "PASS", **response}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
