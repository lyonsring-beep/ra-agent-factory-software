from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from uuid import uuid4

from ra_agent_studio.domain.auth import AuthorityRegistry, AuthorityScope
from ra_agent_studio.domain.candidate import CandidateRecord
from ra_agent_studio.domain.composition import ModuleBinding, RealizedAgentComposition, realize_composition
from ra_agent_studio.domain.effect import EffectFixture, TestDelta, TestObservation, compare_observations, evaluate_fixture
from ra_agent_studio.domain.evidence import BuildEvidence
from ra_agent_studio.domain.governance import BaselineRecord, FreezeRecord, approve_deployment, designate_baseline, freeze_candidate
from ra_agent_studio.domain.identity import BaselineId, CandidateId, ContentHash, DeploymentId, FrozenArtifactId, LineageId, ModuleId, RevisionId
from ra_agent_studio.domain.module import ModuleAuthorityClass, ModuleEditability, ModuleRevision, ModuleRevisionState, ModuleType
from ra_agent_studio.domain.review import ReviewBlocker, ReviewRecord, ReviewVerdict, create_review_record
from ra_agent_studio.infra.execution import IsolatedPythonProcessExecutor
from ra_agent_studio.infra.factory import FACTORY_V111_RUNTIME_IDENTITY, FactoryRuntime, SubprocessFactoryRuntime
from ra_agent_studio.infra.sqlite import SQLiteStateStore


class StudioService:
    """Authoritative Studio application service.

    Durable SQLite records, server-owned authority grants and explicit transactional
    transitions are authoritative. API/UI/CLI are command/query surfaces only.
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        authority_registry: AuthorityRegistry | None = None,
        factory_runtime: FactoryRuntime | None = None,
        sandbox_executor: IsolatedPythonProcessExecutor | None = None,
    ) -> None:
        self.store = SQLiteStateStore(db_path or os.environ.get("RA_STUDIO_DB_PATH", "ra_agent_studio.db"))
        self.authority = authority_registry or AuthorityRegistry.from_environment()
        self.factory_runtime = factory_runtime
        self.sandbox_executor = sandbox_executor or IsolatedPythonProcessExecutor()

    @staticmethod
    def _module_payload(item: ModuleRevision) -> dict:
        return {
            "module_id": item.module_id.value,
            "revision_id": item.revision_id.value,
            "content_hash": item.content_hash.value,
            "name": item.name,
            "content": item.content,
            "author_principal_id": item.author_principal_id,
            "state": item.state.value,
            "predecessor_revision_id": item.predecessor_revision_id.value if item.predecessor_revision_id else None,
            "provided_capabilities": list(item.provided_capabilities),
            "required_capabilities": list(item.required_capabilities),
            "required_module_ids": [x.value for x in item.required_module_ids],
            "incompatible_module_ids": [x.value for x in item.incompatible_module_ids],
            "identity_domain": item.identity_domain,
            "config_json": item.config_json,
            "config_hash": item.config_hash.value if item.config_hash else None,
            "module_type": item.module_type.value,
            "authority_class": item.authority_class.value,
            "editability": item.editability.value,
            "agent_requirement_ref": item.agent_requirement_ref,
            "agent_authority_boundary_ref": item.agent_authority_boundary_ref,
            "shared_change_authorization_ref": item.shared_change_authorization_ref,
        }

    @staticmethod
    def _module_from(data: dict) -> ModuleRevision:
        return ModuleRevision(
            module_id=ModuleId(data["module_id"]),
            revision_id=RevisionId(data["revision_id"]),
            content_hash=ContentHash(data["content_hash"]),
            name=data["name"],
            content=data["content"],
            author_principal_id=data.get("author_principal_id", "system"),
            state=ModuleRevisionState(data["state"]),
            predecessor_revision_id=RevisionId(data["predecessor_revision_id"]) if data.get("predecessor_revision_id") else None,
            provided_capabilities=tuple(data.get("provided_capabilities", [])),
            required_capabilities=tuple(data.get("required_capabilities", [])),
            required_module_ids=tuple(ModuleId(x) for x in data.get("required_module_ids", [])),
            incompatible_module_ids=tuple(ModuleId(x) for x in data.get("incompatible_module_ids", [])),
            identity_domain=data.get("identity_domain", ""),
            config_json=data.get("config_json", "{}"),
            config_hash=ContentHash(data["config_hash"]) if data.get("config_hash") else None,
            module_type=ModuleType(data.get("module_type", ModuleType.AGENT_SPECIFIC_EXTENSION_MODULE.value)),
            authority_class=ModuleAuthorityClass(data.get("authority_class", ModuleAuthorityClass.FACTORY_AGENT_SPECIFIC.value)),
            editability=ModuleEditability(data.get("editability", ModuleEditability.AGENT_EDITABLE.value)),
            agent_requirement_ref=data.get("agent_requirement_ref", "ra-agent-studio:legacy-requirement"),
            agent_authority_boundary_ref=data.get("agent_authority_boundary_ref", "ra-agent-studio:legacy-boundary"),
            shared_change_authorization_ref=data.get("shared_change_authorization_ref", ""),
        )

    @staticmethod
    def _composition_payload(item: RealizedAgentComposition) -> dict:
        return {
            "composition_id": item.composition_id,
            "composition_hash": item.composition_hash.value,
            "agent_requirement_ref": item.agent_requirement_ref,
            "agent_authority_boundary_ref": item.agent_authority_boundary_ref,
            "bindings": [
                {
                    "module_id": b.module_id.value,
                    "revision_id": b.revision_id.value,
                    "content_hash": b.content_hash.value,
                    "provided_capabilities": list(b.provided_capabilities),
                    "required_capabilities": list(b.required_capabilities),
                    "required_module_ids": [x.value for x in b.required_module_ids],
                    "incompatible_module_ids": [x.value for x in b.incompatible_module_ids],
                    "identity_domain": b.identity_domain,
                    "config_hash": b.config_hash.value if b.config_hash else None,
                    "module_type": b.module_type.value,
                    "authority_class": b.authority_class.value,
                    "editability": b.editability.value,
                    "agent_requirement_ref": b.agent_requirement_ref,
                    "agent_authority_boundary_ref": b.agent_authority_boundary_ref,
                    "shared_change_authorization_ref": b.shared_change_authorization_ref,
                }
                for b in item.bindings
            ],
        }

    @staticmethod
    def _composition_from(data: dict) -> RealizedAgentComposition:
        bindings = tuple(
            ModuleBinding(
                module_id=ModuleId(b["module_id"]),
                revision_id=RevisionId(b["revision_id"]),
                content_hash=ContentHash(b["content_hash"]),
                provided_capabilities=tuple(b.get("provided_capabilities", [])),
                required_capabilities=tuple(b.get("required_capabilities", [])),
                required_module_ids=tuple(ModuleId(x) for x in b.get("required_module_ids", [])),
                incompatible_module_ids=tuple(ModuleId(x) for x in b.get("incompatible_module_ids", [])),
                identity_domain=b.get("identity_domain", ""),
                config_hash=ContentHash(b["config_hash"]) if b.get("config_hash") else None,
                module_type=ModuleType(b.get("module_type", ModuleType.AGENT_SPECIFIC_EXTENSION_MODULE.value)),
                authority_class=ModuleAuthorityClass(b.get("authority_class", ModuleAuthorityClass.FACTORY_AGENT_SPECIFIC.value)),
                editability=ModuleEditability(b.get("editability", ModuleEditability.AGENT_EDITABLE.value)),
                agent_requirement_ref=b.get("agent_requirement_ref", data.get("agent_requirement_ref", "")),
                agent_authority_boundary_ref=b.get("agent_authority_boundary_ref", data.get("agent_authority_boundary_ref", "")),
                shared_change_authorization_ref=b.get("shared_change_authorization_ref", ""),
            )
            for b in data["bindings"]
        )
        return RealizedAgentComposition(
            data["composition_id"], bindings, ContentHash(data["composition_hash"]),
            data.get("agent_requirement_ref", bindings[0].agent_requirement_ref if bindings else ""),
            data.get("agent_authority_boundary_ref", bindings[0].agent_authority_boundary_ref if bindings else ""),
        )

    @staticmethod
    def _candidate_payload(item: CandidateRecord) -> dict:
        return {
            "candidate_id": item.candidate_id.value,
            "candidate_hash": item.candidate_hash.value,
            "composition_id": item.composition_id,
            "composition_hash": item.composition_hash.value,
            "factory_evidence_id": item.factory_evidence_id,
            "factory_runtime_commit": item.factory_runtime_commit,
            "factory_candidate_sha256": item.factory_candidate_sha256,
            "author_principal_id": item.author_principal_id,
            "contributor_principal_ids": sorted(item.contributor_principal_ids),
            "contributor_workspace_ids": sorted(item.contributor_workspace_ids),
            "workspace_id": item.workspace_id,
            "artifact_blob_hash": item.artifact_blob_hash.value if item.artifact_blob_hash else None,
            "logical_payload_identity": item.logical_payload_identity.value if item.logical_payload_identity else None,
            "manifest_identity": item.manifest_identity.value if item.manifest_identity else None,
            "factory_candidate_revision_id": item.factory_candidate_revision_id,
            "lineage_id": item.lineage_id.value,
            "predecessor_baseline_id": item.predecessor_baseline_id.value if item.predecessor_baseline_id else None,
        }

    @staticmethod
    def _candidate_from(data: dict) -> CandidateRecord:
        return CandidateRecord(
            candidate_id=CandidateId(data["candidate_id"]),
            candidate_hash=ContentHash(data["candidate_hash"]),
            composition_id=data["composition_id"],
            composition_hash=ContentHash(data["composition_hash"]),
            factory_evidence_id=data["factory_evidence_id"],
            factory_runtime_commit=data["factory_runtime_commit"],
            factory_candidate_sha256=data["factory_candidate_sha256"],
            author_principal_id=data["author_principal_id"],
            contributor_principal_ids=frozenset(data["contributor_principal_ids"]),
            contributor_workspace_ids=frozenset(data.get("contributor_workspace_ids", [data["workspace_id"]])),
            workspace_id=data["workspace_id"],
            artifact_blob_hash=ContentHash(data["artifact_blob_hash"]) if data.get("artifact_blob_hash") else None,
            logical_payload_identity=ContentHash(data["logical_payload_identity"]) if data.get("logical_payload_identity") else None,
            manifest_identity=ContentHash(data["manifest_identity"]) if data.get("manifest_identity") else None,
            factory_candidate_revision_id=data.get("factory_candidate_revision_id", ""),
            lineage_id=LineageId(data["lineage_id"]),
            predecessor_baseline_id=BaselineId(data["predecessor_baseline_id"]) if data.get("predecessor_baseline_id") else None,
        )

    @staticmethod
    def _review_payload(item: ReviewRecord) -> dict:
        return {
            "review_id": item.review_id,
            "subject_candidate_id": item.subject_candidate_id.value,
            "subject_hash": item.subject_hash.value,
            "reviewer_principal_id": item.reviewer_principal_id,
            "reviewer_workspace_id": item.reviewer_workspace_id,
            "authority_grant_id": item.authority_grant_id,
            "authority_source": item.authority_source,
            "review_method": item.review_method,
            "scope": item.scope,
            "target_workspace_id": item.target_workspace_id,
            "verdict": item.verdict.value,
            "blockers": [{"blocker_id": b.blocker_id, "description": b.description, "closed": b.closed} for b in item.blockers],
        }

    @staticmethod
    def _review_from(data: dict) -> ReviewRecord:
        return ReviewRecord(
            review_id=data["review_id"],
            subject_candidate_id=CandidateId(data["subject_candidate_id"]),
            subject_hash=ContentHash(data["subject_hash"]),
            reviewer_principal_id=data["reviewer_principal_id"],
            reviewer_workspace_id=data.get("reviewer_workspace_id", "legacy-unknown"),
            authority_grant_id=data["authority_grant_id"],
            authority_source=data.get("authority_source", "legacy-unknown"),
            review_method=data["review_method"],
            scope=data["scope"],
            target_workspace_id=data.get("target_workspace_id", data.get("workspace_id", "")),
            verdict=ReviewVerdict(data["verdict"]),
            blockers=tuple(ReviewBlocker(**b) for b in data.get("blockers", [])),
        )

    @staticmethod
    def _freeze_payload(item: FreezeRecord) -> dict:
        return {
            "frozen_artifact_id": item.frozen_artifact.id.value,
            "source_candidate_id": item.frozen_artifact.source_candidate_id.value,
            "candidate_hash": item.candidate_hash.value,
            "review_id": item.review_id,
            "lineage_id": item.lineage_id.value,
            "predecessor_baseline_id": item.predecessor_baseline_id.value if item.predecessor_baseline_id else None,
            "authority_grant_id": item.authority_grant_id,
            "frozen_by_principal_id": item.frozen_by_principal_id,
            "frozen_at": item.frozen_at.isoformat(),
        }

    @staticmethod
    def _freeze_from(data: dict) -> FreezeRecord:
        from ra_agent_studio.domain.authority import FrozenArtifact
        return FreezeRecord(
            frozen_artifact=FrozenArtifact(FrozenArtifactId(data["frozen_artifact_id"]), CandidateId(data["source_candidate_id"])),
            candidate_hash=ContentHash(data["candidate_hash"]),
            review_id=data["review_id"],
            lineage_id=LineageId(data["lineage_id"]),
            predecessor_baseline_id=BaselineId(data["predecessor_baseline_id"]) if data.get("predecessor_baseline_id") else None,
            authority_grant_id=data["authority_grant_id"],
            frozen_by_principal_id=data["frozen_by_principal_id"],
            frozen_at=datetime.fromisoformat(data["frozen_at"]),
        )

    @staticmethod
    def _baseline_payload(item: BaselineRecord) -> dict:
        return {
            "baseline_id": item.baseline_id.value,
            "frozen_artifact_id": item.frozen_artifact_id.value,
            "lineage_id": item.lineage_id.value,
            "predecessor_baseline_id": item.predecessor_baseline_id.value if item.predecessor_baseline_id else None,
            "authority_grant_id": item.authority_grant_id,
            "promoted_by_principal_id": item.promoted_by_principal_id,
            "promoted_at": item.promoted_at.isoformat(),
        }

    @staticmethod
    def _baseline_from(data: dict) -> BaselineRecord:
        return BaselineRecord(
            baseline_id=BaselineId(data["baseline_id"]),
            frozen_artifact_id=FrozenArtifactId(data["frozen_artifact_id"]),
            lineage_id=LineageId(data["lineage_id"]),
            predecessor_baseline_id=BaselineId(data["predecessor_baseline_id"]) if data.get("predecessor_baseline_id") else None,
            authority_grant_id=data["authority_grant_id"],
            promoted_by_principal_id=data["promoted_by_principal_id"],
            promoted_at=datetime.fromisoformat(data["promoted_at"]),
        )

    def _audit(self, actor: str, action: str, kind: str, subject_id: str, metadata: dict) -> None:
        self.store.append_audit(
            event_id=f"audit-{uuid4().hex}",
            actor_principal_id=actor,
            action=action,
            subject_kind=kind,
            subject_id=subject_id,
            metadata=metadata,
            occurred_at=datetime.now(UTC),
        )

    def create_module_revision(
        self,
        *,
        module_id: str,
        revision_id: str,
        name: str,
        content: str,
        actor_principal_id: str = "system",
        predecessor_revision_id: str | None = None,
        provided_capabilities: tuple[str, ...] = (),
        required_capabilities: tuple[str, ...] = (),
        required_module_ids: tuple[str, ...] = (),
        incompatible_module_ids: tuple[str, ...] = (),
        identity_domain: str = "",
        config_json: str = "{}",
        module_type: str = ModuleType.AGENT_SPECIFIC_EXTENSION_MODULE.value,
        authority_class: str = ModuleAuthorityClass.FACTORY_AGENT_SPECIFIC.value,
        editability: str = ModuleEditability.AGENT_EDITABLE.value,
        agent_requirement_ref: str = "ra-agent-studio:default-requirement",
        agent_authority_boundary_ref: str = "ra-agent-studio:default-authority-boundary",
        shared_change_authorization_ref: str = "",
    ) -> ModuleRevision:
        revision = ModuleRevision.create(
            ModuleId(module_id),
            RevisionId(revision_id),
            name=name,
            content=content,
            author_principal_id=actor_principal_id,
            predecessor_revision_id=RevisionId(predecessor_revision_id) if predecessor_revision_id else None,
            provided_capabilities=provided_capabilities,
            required_capabilities=required_capabilities,
            required_module_ids=tuple(ModuleId(x) for x in required_module_ids),
            incompatible_module_ids=tuple(ModuleId(x) for x in incompatible_module_ids),
            identity_domain=identity_domain,
            config_json=config_json,
            module_type=ModuleType(module_type),
            authority_class=ModuleAuthorityClass(authority_class),
            editability=ModuleEditability(editability),
            agent_requirement_ref=agent_requirement_ref,
            agent_authority_boundary_ref=agent_authority_boundary_ref,
            shared_change_authorization_ref=shared_change_authorization_ref,
        )
        with self.store.transaction():
            if predecessor_revision_id:
                self.store.get("module", predecessor_revision_id)
            self.store.add("module", revision_id, self._module_payload(revision))
            self._audit(actor_principal_id, "module_revision_created", "module", revision_id, {"hash": revision.content_hash.value})
        return revision

    def get_module(self, revision_id: str) -> ModuleRevision:
        return self._module_from(self.store.get("module", revision_id))

    def list_modules(self) -> tuple[ModuleRevision, ...]:
        return tuple(self._module_from(x) for x in self.store.list("module"))

    def prepare_candidate(self, revision_id: str, *, actor_principal_id: str = "system") -> ModuleRevision:
        revision = self.get_module(revision_id)
        candidate = replace(revision, state=ModuleRevisionState.CANDIDATE)
        with self.store.transaction():
            self.store.put("module", revision_id, self._module_payload(candidate))
            self._audit(actor_principal_id, "module_candidate_prepared", "module", revision_id, {})
        return candidate

    def run_effect_fixture(self, revision_id: str, fixture: EffectFixture) -> TestObservation:
        revision = self.get_module(revision_id)
        result = self.sandbox_executor.execute(revision, fixture.input_text)
        return evaluate_fixture(
            fixture,
            revision.revision_id,
            result.output_text,
            executor_identity=result.executor_identity,
        )

    def compare_effect_fixture(self, before_revision_id: str, after_revision_id: str, fixture: EffectFixture) -> TestDelta:
        before = self.run_effect_fixture(before_revision_id, fixture)
        after = self.run_effect_fixture(after_revision_id, fixture)
        return compare_observations(before, after)

    def compose(self, composition_id: str, revision_ids: list[str], *, actor_principal_id: str = "system") -> RealizedAgentComposition:
        bindings: list[ModuleBinding] = []
        for revision_id in revision_ids:
            revision = self.get_module(revision_id)
            bindings.append(
                ModuleBinding(
                    revision.module_id,
                    revision.revision_id,
                    revision.content_hash,
                    revision.provided_capabilities,
                    revision.required_capabilities,
                    revision.required_module_ids,
                    revision.incompatible_module_ids,
                    revision.identity_domain,
                    revision.config_hash,
                    revision.module_type,
                    revision.authority_class,
                    revision.editability,
                    revision.agent_requirement_ref,
                    revision.agent_authority_boundary_ref,
                    revision.shared_change_authorization_ref,
                )
            )
        composition = realize_composition(composition_id, tuple(bindings))
        with self.store.transaction():
            self.store.add("composition", composition_id, self._composition_payload(composition))
            self._audit(actor_principal_id, "composition_realized", "composition", composition_id, {"hash": composition.composition_hash.value})
        return composition

    def build(
        self,
        composition_id: str,
        *,
        actor_principal_id: str,
        workspace_id: str,
        lineage_id: str,
        predecessor_baseline_id: str | None = None,
    ) -> tuple[BuildEvidence, CandidateRecord]:
        self.authority.require_grant(actor_principal_id, AuthorityScope.BUILD, workspace_id=workspace_id)
        composition = self._composition_from(self.store.get("composition", composition_id))
        runtime = self.factory_runtime or SubprocessFactoryRuntime.from_environment()
        result = runtime.realize(composition)
        evidence = BuildEvidence(
            evidence_id=f"evidence-{uuid4().hex}",
            composition_id=composition_id,
            composition_hash=composition.composition_hash,
            artifact_hash=result.artifact_hash,
            created_at=datetime.now(UTC),
            reproducible=result.reproducible,
            runtime_identity=FACTORY_V111_RUNTIME_IDENTITY,
            factory_runtime_commit=result.runtime_commit,
            factory_candidate_sha256=result.factory_candidate_sha256,
            factory_evidence_hash=result.factory_evidence_hash,
        )
        contributors = {actor_principal_id}
        contributor_workspaces = {self.authority.principal(actor_principal_id).workspace_id}
        for binding in composition.bindings:
            author_id = self.get_module(binding.revision_id.value).author_principal_id
            contributors.add(author_id)
            try:
                contributor_workspaces.add(self.authority.principal(author_id).workspace_id)
            except PermissionError:
                contributor_workspaces.add(workspace_id)
        candidate = CandidateRecord(
            candidate_id=CandidateId(f"candidate-{result.artifact_hash.value[:24]}"),
            candidate_hash=result.artifact_hash,
            composition_id=composition_id,
            composition_hash=composition.composition_hash,
            factory_evidence_id=evidence.evidence_id,
            factory_runtime_commit=result.runtime_commit,
            factory_candidate_sha256=result.factory_candidate_sha256,
            author_principal_id=actor_principal_id,
            contributor_principal_ids=frozenset(contributors),
            contributor_workspace_ids=frozenset(contributor_workspaces),
            workspace_id=workspace_id,
            lineage_id=LineageId(lineage_id),
            predecessor_baseline_id=BaselineId(predecessor_baseline_id) if predecessor_baseline_id else None,
            artifact_blob_hash=result.artifact_hash,
            logical_payload_identity=result.logical_payload_identity,
            manifest_identity=result.manifest_identity,
            factory_candidate_revision_id=result.factory_candidate_revision_id,
        )
        evidence_payload = {
            "evidence_id": evidence.evidence_id,
            "composition_id": evidence.composition_id,
            "composition_hash": evidence.composition_hash.value,
            "artifact_hash": evidence.artifact_hash.value,
            "created_at": evidence.created_at.isoformat(),
            "reproducible": evidence.reproducible,
            "runtime_identity": evidence.runtime_identity,
            "factory_runtime_commit": evidence.factory_runtime_commit,
            "factory_candidate_sha256": evidence.factory_candidate_sha256,
            "factory_evidence_hash": evidence.factory_evidence_hash.value,
        }
        with self.store.transaction():
            if predecessor_baseline_id:
                current = self.store.get_optional("current_baseline", lineage_id)
                if current is None or current.get("baseline_id") != predecessor_baseline_id:
                    raise PermissionError("build predecessor is not the current lineage baseline")
            published = self.store.publish_blob(result.artifact_bytes)
            if published != candidate.candidate_hash.value:
                raise RuntimeError("Factory candidate byte publication hash mismatch")
            self.store.add("evidence", evidence.evidence_id, evidence_payload)
            self.store.add("candidate", candidate.candidate_id.value, self._candidate_payload(candidate))
            self.store.add_immutable("candidate_closure", candidate.candidate_id.value, {
                "candidate_hash": candidate.candidate_hash.value,
                "artifact_blob_hash": published,
                "logical_payload_identity": candidate.logical_payload_identity.value,
                "manifest_identity": candidate.manifest_identity.value,
                "factory_candidate_revision_id": candidate.factory_candidate_revision_id,
                "factory_runtime_commit": candidate.factory_runtime_commit,
                "factory_candidate_sha256": candidate.factory_candidate_sha256,
            })
            self._audit(actor_principal_id, "factory_build_completed", "candidate", candidate.candidate_id.value, {"candidate_hash": candidate.candidate_hash.value, "factory_commit": result.runtime_commit})
        return evidence, candidate

    def review(
        self,
        *,
        candidate_id: str,
        reviewer_principal_id: str,
        review_method: str,
        passed: bool,
        blockers: tuple[ReviewBlocker, ...] = (),
    ) -> ReviewRecord:
        candidate = self._candidate_from(self.store.get("candidate", candidate_id))
        grant = self.authority.require_grant(
            reviewer_principal_id,
            AuthorityScope.REVIEW,
            workspace_id=candidate.workspace_id,
            review_method=review_method,
        )
        reviewer = self.authority.principal(reviewer_principal_id)
        record = create_review_record(
            review_id=f"review-{uuid4().hex}",
            candidate=candidate,
            reviewer=reviewer,
            authority_grant=grant,
            review_method=review_method,
            verdict=ReviewVerdict.PASS if passed else ReviewVerdict.FAIL,
            blockers=blockers,
        )
        with self.store.transaction():
            self.store.add("review", record.review_id, self._review_payload(record))
            self._audit(reviewer_principal_id, "review_recorded", "candidate", candidate_id, {"review_id": record.review_id, "verdict": record.verdict.value, "grant_id": grant.grant_id})
        return record

    def freeze(self, *, candidate_id: str, review_id: str, actor_principal_id: str) -> FreezeRecord:
        candidate = self._candidate_from(self.store.get("candidate", candidate_id))
        review = self._review_from(self.store.get("review", review_id))
        if not candidate.artifact_blob_hash or not candidate.logical_payload_identity or not candidate.manifest_identity:
            raise PermissionError("candidate lacks exact B09 closure identities")
        immutable = self.store.get_immutable("candidate_closure", candidate.candidate_id.value)
        artifact_bytes = self.store.get_blob(candidate.artifact_blob_hash.value)
        if ContentHash.from_bytes(artifact_bytes) != candidate.candidate_hash:
            raise PermissionError("immutable candidate bytes no longer match reviewed candidate hash")
        if immutable["logical_payload_identity"] != candidate.logical_payload_identity.value or immutable["manifest_identity"] != candidate.manifest_identity.value:
            raise PermissionError("candidate closure identity drift")
        grant = self.authority.require_grant(actor_principal_id, AuthorityScope.FREEZE, workspace_id=candidate.workspace_id)
        frozen_id = FrozenArtifactId(f"frozen-{candidate.candidate_hash.value[:24]}")
        record = freeze_candidate(
            candidate=candidate,
            frozen_artifact_id=frozen_id,
            review=review,
            authority_grant_id=grant.grant_id,
            frozen_by_principal_id=actor_principal_id,
            frozen_at=datetime.now(UTC),
        )
        with self.store.transaction():
            self.store.add("freeze", frozen_id.value, self._freeze_payload(record))
            self.store.add_immutable("freeze_closure", frozen_id.value, {
                "candidate_id": candidate_id,
                "candidate_hash": candidate.candidate_hash.value,
                "artifact_blob_hash": candidate.artifact_blob_hash.value,
                "logical_payload_identity": candidate.logical_payload_identity.value,
                "manifest_identity": candidate.manifest_identity.value,
                "review_id": review_id,
            })
            self._audit(actor_principal_id, "candidate_frozen", "freeze", frozen_id.value, {"candidate_id": candidate_id, "candidate_hash": candidate.candidate_hash.value, "review_id": review_id, "grant_id": grant.grant_id})
        return record

    def create_baseline(
        self,
        *,
        baseline_id: str,
        lineage_id: str,
        frozen_artifact_id: str,
        expected_predecessor_baseline_id: str | None,
        actor_principal_id: str,
    ) -> BaselineRecord:
        freeze = self._freeze_from(self.store.get("freeze", frozen_artifact_id))
        candidate = self._candidate_from(self.store.get("candidate", freeze.frozen_artifact.source_candidate_id.value))
        grant = self.authority.require_grant(actor_principal_id, AuthorityScope.PROMOTE_BASELINE, workspace_id=candidate.workspace_id)
        with self.store.transaction():
            token = self.store.acquire_fencing_token(lineage_id, actor_principal_id)
            pointer = self.store.get_pointer("current_baseline", lineage_id)
            actual_baseline_id = pointer["value"] if pointer else None
            current = self._baseline_from(self.store.get("baseline", actual_baseline_id)) if actual_baseline_id else None
            record = designate_baseline(
                baseline_id=BaselineId(baseline_id),
                lineage_id=LineageId(lineage_id),
                freeze=freeze,
                current_baseline=current,
                expected_predecessor_baseline_id=BaselineId(expected_predecessor_baseline_id) if expected_predecessor_baseline_id else None,
                authority_grant_id=grant.grant_id,
                promoted_by_principal_id=actor_principal_id,
                promoted_at=datetime.now(UTC),
            )
            self.store.add("baseline", baseline_id, self._baseline_payload(record))
            version = self.store.compare_and_set_pointer(
                "current_baseline", lineage_id,
                expected_value=expected_predecessor_baseline_id,
                new_value=baseline_id,
                expected_version=int(pointer["version"]) if pointer else 0,
                fencing_token=token,
            )
            self.store.put("current_baseline", lineage_id, {"baseline_id": baseline_id, "version": version, "fencing_token": token})
            self.store.add_immutable("promotion_closure", baseline_id, {
                "lineage_id": lineage_id,
                "frozen_artifact_id": frozen_artifact_id,
                "predecessor_baseline_id": expected_predecessor_baseline_id,
                "fencing_token": token,
                "pointer_version": version,
                "recovery_epoch": self.store.recovery_epoch(),
            })
            self._audit(actor_principal_id, "baseline_promoted", "baseline", baseline_id, {"lineage_id": lineage_id, "frozen_artifact_id": frozen_artifact_id, "predecessor": expected_predecessor_baseline_id, "grant_id": grant.grant_id, "fencing_token": token, "pointer_version": version})
        return record

    def deploy(self, *, deployment_id: str, frozen_artifact_id: str, actor_principal_id: str):
        freeze = self._freeze_from(self.store.get("freeze", frozen_artifact_id))
        candidate = self._candidate_from(self.store.get("candidate", freeze.frozen_artifact.source_candidate_id.value))
        grant = self.authority.require_grant(actor_principal_id, AuthorityScope.DEPLOY, workspace_id=candidate.workspace_id)
        with self.store.transaction():
            pointer = self.store.get_pointer("current_baseline", freeze.lineage_id.value)
            if pointer is None:
                raise PermissionError("lineage has no current baseline")
            current = self._baseline_from(self.store.get("baseline", pointer["value"]))
            record = approve_deployment(
                deployment_id=DeploymentId(deployment_id),
                freeze=freeze,
                current_baseline=current,
                authority_grant_id=grant.grant_id,
                activated_by_principal_id=actor_principal_id,
                activated_at=datetime.now(UTC),
            )
            payload = {
                "deployment_id": record.id.value,
                "artifact_id": record.artifact_id.value,
                "lineage_id": record.lineage_id.value,
                "baseline_id": record.baseline_id.value,
                "authority_grant_id": record.authority_grant_id,
                "activated_by_principal_id": record.activated_by_principal_id,
                "activated_at": record.activated_at.isoformat(),
            }
            self.store.add("deployment", deployment_id, payload)
            self._audit(actor_principal_id, "deployment_activated", "deployment", deployment_id, {"frozen_artifact_id": frozen_artifact_id, "baseline_id": current.baseline_id.value, "grant_id": grant.grant_id})
        return record

    def snapshot(self) -> dict:
        return {
            "modules": self.store.list("module"),
            "compositions": self.store.list("composition"),
            "evidence": self.store.list("evidence"),
            "candidates": self.store.list("candidate"),
            "reviews": self.store.list("review"),
            "freezes": self.store.list("freeze"),
            "baselines": self.store.list("baseline"),
            "deployments": self.store.list("deployment"),
            "audit": self.store.list_audit(),
        }
