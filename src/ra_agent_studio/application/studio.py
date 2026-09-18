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
from ra_agent_studio.domain.production import ProductionEvent, ProductionRunRecord, ProductionState, transition as transition_production
from ra_agent_studio.domain.deployment import DeploymentAuthorityRecord, DeploymentGrantStanding, GrantEvent, RuntimeDeploymentStanding, RuntimeEvent, RuntimeRealizationSnapshot, grant_next, runtime_next
from ra_agent_studio.domain.failure_routing import CandidateMutationStanding, FailureClass, ProductionStage, route_failure
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
            "capability_bindings": [
                {"capability": capability, "revision_id": revision_id.value}
                for capability, revision_id in item.capability_bindings
            ],
            "capability_binding_identity": item.capability_binding_identity.value if item.capability_binding_identity else None,
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
            tuple(
                (entry["capability"], RevisionId(entry["revision_id"]))
                for entry in data.get("capability_bindings", [])
            ),
            ContentHash(data["capability_binding_identity"]) if data.get("capability_binding_identity") else None,
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
    def _production_payload(item: ProductionRunRecord) -> dict:
        return {
            "production_run_id": item.production_run_id,
            "current_state": item.current_state.value,
            "consistency_version": item.consistency_version,
            "recovery_epoch": item.recovery_epoch,
            "exact_candidate_id": item.exact_candidate_id,
            "upstream_handoff_ref": item.upstream_handoff_ref,
            "last_transition_ref": item.last_transition_ref,
        }

    @staticmethod
    def _production_from(data: dict) -> ProductionRunRecord:
        return ProductionRunRecord(
            production_run_id=data["production_run_id"],
            current_state=ProductionState(data["current_state"]),
            consistency_version=int(data["consistency_version"]),
            recovery_epoch=int(data["recovery_epoch"]),
            exact_candidate_id=data["exact_candidate_id"],
            upstream_handoff_ref=data["upstream_handoff_ref"],
            last_transition_ref=data.get("last_transition_ref", ""),
        )

    def _transition_production(self, run: ProductionRunRecord, event: ProductionEvent, actor: str) -> ProductionRunRecord:
        if run.recovery_epoch != self.store.recovery_epoch():
            raise PermissionError("STALE_RECOVERY_EPOCH")
        transition_ref=f"production-transition-{uuid4().hex}"
        updated=transition_production(run,event,transition_ref=transition_ref)
        self.store.put("production_run",run.production_run_id,self._production_payload(updated))
        self.store.add_immutable("production_transition",transition_ref,{
            "production_run_id":run.production_run_id,
            "from_state":run.current_state.value,
            "event":event.value,
            "to_state":updated.current_state.value,
            "prior_transition_ref":run.last_transition_ref,
            "consistency_version":updated.consistency_version,
            "recovery_epoch":updated.recovery_epoch,
        })
        self._audit(actor,"production_transition","production_run",run.production_run_id,{
            "from_state":run.current_state.value,"event":event.value,"to_state":updated.current_state.value,
            "transition_ref":transition_ref,"consistency_version":updated.consistency_version,
        })
        return updated

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
        event_id=f"audit-{uuid4().hex}"
        occurred_at=datetime.now(UTC)
        audit=self.store.append_audit(
            event_id=event_id,
            actor_principal_id=actor,
            action=action,
            subject_kind=kind,
            subject_id=subject_id,
            metadata=metadata,
            occurred_at=occurred_at,
        )
        self.store.add_immutable("authority_commit_set",event_id,{
            "action":action,
            "actor_principal_id":actor,
            "subject_kind":kind,
            "subject_id":subject_id,
            "metadata":metadata,
            "audit_event_hash":audit["event_hash"],
            "prior_audit_event_hash":audit["prior_event_hash"],
            "recovery_epoch":self.store.recovery_epoch(),
            "committed_at":occurred_at.isoformat(),
        })

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
        observation=evaluate_fixture(
            fixture,
            revision.revision_id,
            result.output_text,
            executor_identity=result.executor_identity,
            environment_identity=result.environment_identity,
            execution_policy_identity=result.execution_policy_identity,
            termination_reason=result.termination_reason,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
        with self.store.transaction():
            self.store.add_immutable("controlled_execution_observation",f"{revision_id}:{fixture.fixture_identity}",{
                "revision_id":revision_id,
                "module_content_hash":revision.content_hash.value,
                "fixture_id":fixture.fixture_id,
                "fixture_identity":fixture.fixture_identity,
                "input_identity":observation.metadata["input_identity"],
                "executor_identity":result.executor_identity,
                "environment_identity":result.environment_identity,
                "execution_policy_identity":result.execution_policy_identity,
                "termination_reason":result.termination_reason,
                "exit_code":result.exit_code,
                "duration_ms":result.duration_ms,
                "passed":observation.passed,
            })
        return observation

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
        upstream_handoff_ref: str = "RA_AGENT_STUDIO_FORMAL_SOFTWARE_DESIGN_FROZEN_HANDOFF",
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
        contributor_workspace_by_principal = {
            actor_principal_id: self.authority.principal(actor_principal_id).workspace_id
        }
        for binding in composition.bindings:
            author_id = self.get_module(binding.revision_id.value).author_principal_id
            contributors.add(author_id)
            try:
                contributor_workspace_by_principal[author_id] = self.authority.principal(author_id).workspace_id
            except PermissionError:
                contributor_workspace_by_principal[author_id] = workspace_id
        contributor_workspaces = set(contributor_workspace_by_principal.values())
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
            for contributor_id in sorted(candidate.contributor_principal_ids):
                contributor_workspace=contributor_workspace_by_principal[contributor_id]
                self.store.add_immutable("contribution_record",f"{candidate.candidate_id.value}:{contributor_id}",{
                    "exact_candidate_id":candidate.candidate_id.value,
                    "exact_candidate_hash":candidate.candidate_hash.value,
                    "principal_id":contributor_id,
                    "workspace_id":contributor_workspace,
                    "contribution_kind":"BUILD_OR_MODULE_AUTHORSHIP",
                })
            self.store.add_immutable("cross_store_publication",candidate.candidate_id.value,{
                "object_kind":"implementation_candidate",
                "object_id":candidate.candidate_id.value,
                "content_id":published,
                "content_sha256":published,
                "publication_standing":"AUTHORITATIVELY_PUBLISHED",
                "integrity_standing":"VERIFIED",
                "recovery_epoch":self.store.recovery_epoch(),
            })
            self.store.add_immutable("candidate_closure", candidate.candidate_id.value, {
                "candidate_hash": candidate.candidate_hash.value,
                "container_identity": candidate.candidate_hash.value,
                "artifact_blob_hash": published,
                "logical_payload_identity": candidate.logical_payload_identity.value,
                "manifest_identity": candidate.manifest_identity.value,
                "factory_candidate_revision_id": candidate.factory_candidate_revision_id,
                "factory_runtime_commit": candidate.factory_runtime_commit,
                "factory_candidate_sha256": candidate.factory_candidate_sha256,
            })
            production_run_id=f"production-run:{candidate.candidate_id.value}"
            initial=ProductionRunRecord(
                production_run_id=production_run_id,
                current_state=ProductionState.PR_08_IMPLEMENTATION_IN_PROGRESS,
                consistency_version=0,
                recovery_epoch=self.store.recovery_epoch(),
                exact_candidate_id=candidate.candidate_id.value,
                upstream_handoff_ref=upstream_handoff_ref,
            )
            self.store.add("production_run",production_run_id,self._production_payload(initial))
            self.store.add_immutable("production_prerequisite",f"{production_run_id}:handoff",{
                "kind":"IMPLEMENTATION_HANDOFF",
                "upstream_handoff_ref":upstream_handoff_ref,
                "standing":"VALID",
                "authority_basis":"Frozen Studio Formal Software Design / Implementation Handoff",
            })
            self._transition_production(initial,ProductionEvent.IMPLEMENTATION_CANDIDATE_READY,actor_principal_id)
            self._audit(actor_principal_id, "factory_build_completed", "candidate", candidate.candidate_id.value, {"candidate_hash": candidate.candidate_hash.value, "factory_commit": result.runtime_commit, "production_run_id": production_run_id})
        return evidence, candidate

    def review(
        self,
        *,
        candidate_id: str,
        reviewer_principal_id: str,
        review_method: str,
        passed: bool | None = None,
        verdict: str | None = None,
        blockers: tuple[ReviewBlocker, ...] = (),
        failure_class: str | None = None,
        mutation_standing: str = CandidateMutationStanding.UNCHANGED.value,
        authorized_reopen_scope: tuple[str, ...] = (),
    ) -> ReviewRecord:
        candidate = self._candidate_from(self.store.get("candidate", candidate_id))
        production_run_id=f"production-run:{candidate_id}"
        run=self._production_from(self.store.get("production_run",production_run_id))
        if run.current_state is not ProductionState.PR_09_IMPLEMENTATION_CANDIDATE:
            raise PermissionError(f"review submission requires PR-09, got {run.current_state.value}")
        grant = self.authority.require_grant(
            reviewer_principal_id,
            AuthorityScope.REVIEW,
            workspace_id=candidate.workspace_id,
            review_method=review_method,
        )
        reviewer = self.authority.principal(reviewer_principal_id)
        if verdict is None:
            verdict_value=ReviewVerdict.PASS if passed else ReviewVerdict.FAIL
        else:
            verdict_value=ReviewVerdict(verdict.lower())
        route=None
        if verdict_value in {ReviewVerdict.FAIL, ReviewVerdict.INCONCLUSIVE}:
            if not failure_class or not authorized_reopen_scope:
                raise PermissionError("FAIL/INCONCLUSIVE requires canonical FailureClassification and AuthorizedReopenScope")
            route=route_failure(
                FailureClass(failure_class),
                stage=ProductionStage.IMPLEMENTATION,
                mutation_standing=CandidateMutationStanding(mutation_standing),
            )
        record = create_review_record(
            review_id=f"review-{uuid4().hex}",
            candidate=candidate,
            reviewer=reviewer,
            authority_grant=grant,
            review_method=review_method,
            verdict=verdict_value,
            blockers=blockers,
        )
        with self.store.transaction():
            run=self._production_from(self.store.get("production_run",production_run_id))
            run=self._transition_production(run,ProductionEvent.IMPLEMENTATION_REVIEW_SUBMITTED,reviewer_principal_id)
            self.store.add_immutable("review_submission",record.review_id,{
                "exact_target_ref":candidate.factory_candidate_revision_id or candidate.candidate_id.value,
                "studio_candidate_id":candidate.candidate_id.value,
                "candidate_hash":candidate.candidate_hash.value,
                "review_method_ref":review_method,
                "review_authority_ref":grant.grant_id,
                "reviewer_principal_id":reviewer.principal_id,
                "reviewer_workspace_id":reviewer.workspace_id,
                "verification_package_ref":candidate.factory_evidence_id,
                "submitted_at_state":run.current_state.value,
            })
            self.store.add("review", record.review_id, self._review_payload(record))
            self.store.add_immutable("review_admission",record.review_id,{
                "exact_target_ref":candidate.factory_candidate_revision_id or candidate.candidate_id.value,
                "studio_candidate_id":candidate.candidate_id.value,
                "subject_hash":candidate.candidate_hash.value,
                "reviewer_principal_id":record.reviewer_principal_id,
                "reviewer_workspace_id":record.reviewer_workspace_id,
                "standing":"REVIEW_ADMISSIBLE",
                "independence_standing":"INDEPENDENT",
                "review_scope_ref":candidate.factory_candidate_revision_id or candidate.candidate_id.value,
                "authority_grant_id":record.authority_grant_id,
                "authority_source":record.authority_source,
            })
            if record.verdict is ReviewVerdict.PASS:
                run=self._transition_production(run,ProductionEvent.IMPLEMENTATION_REVIEW_PASS,reviewer_principal_id)
                self.store.add_immutable("b09_closure_eligibility", candidate.candidate_id.value, {
                    "standing":"ELIGIBLE",
                    "production_run_id":production_run_id,
                    "candidate_id":candidate.candidate_id.value,
                    "candidate_hash":candidate.candidate_hash.value,
                    "logical_payload_identity":candidate.logical_payload_identity.value if candidate.logical_payload_identity else "",
                    "manifest_identity":candidate.manifest_identity.value if candidate.manifest_identity else "",
                    "review_id":record.review_id,
                    "review_accepted_transport_basis":{
                        "container_identity":candidate.candidate_hash.value,
                        "logical_payload_identity":candidate.logical_payload_identity.value if candidate.logical_payload_identity else "",
                        "manifest_identity":candidate.manifest_identity.value if candidate.manifest_identity else "",
                    },
                    "review_independence":"INDEPENDENT",
                    "production_state":run.current_state.value,
                })
            else:
                failure_ref=f"failure-classification:{uuid4().hex}"
                reopen_ref=f"authorized-reopen-scope:{uuid4().hex}"
                self.store.add_immutable("failure_classification",failure_ref,{
                    "production_run_id":production_run_id,
                    "review_decision_ref":record.review_id,
                    "exact_target_ref":candidate.candidate_id.value,
                    "failure_class":route.failure_class.value,
                    "production_stage":route.stage.value,
                    "candidate_mutation_standing":route.mutation_standing.value,
                    "route_basis":route.route_basis,
                    "routed_state":route.routed_state.value,
                    "candidate_bytes_may_change":route.candidate_bytes_may_change,
                })
                self.store.add_immutable("authorized_reopen_scope",reopen_ref,{
                    "production_run_id":production_run_id,
                    "review_decision_ref":record.review_id,
                    "exact_target_ref":candidate.candidate_id.value,
                    "scope_items":list(authorized_reopen_scope),
                    "route_basis":route.route_basis,
                    "failure_classification_ref":failure_ref,
                })
                run=self._transition_production(run,route.authorization_event,reviewer_principal_id)
            self._audit(reviewer_principal_id, "review_recorded", "candidate", candidate_id, {
                "review_id": record.review_id, "verdict": record.verdict.value, "grant_id": grant.grant_id,
                "production_state":run.current_state.value,
                "failure_route":route.route_basis if route else None,
            })
        return record

    def freeze(self, *, candidate_id: str, review_id: str, actor_principal_id: str) -> FreezeRecord:
        candidate = self._candidate_from(self.store.get("candidate", candidate_id))
        review = self._review_from(self.store.get("review", review_id))
        if review.subject_candidate_id != candidate.candidate_id or review.subject_hash != candidate.candidate_hash:
            raise PermissionError("review is not bound to this exact candidate/hash")
        production_run_id=f"production-run:{candidate_id}"
        run=self._production_from(self.store.get("production_run",production_run_id))
        if run.current_state is not ProductionState.PR_15_IMPLEMENTATION_APPROVED:
            raise PermissionError(f"freeze requires PR-15 implementation approved, got {run.current_state.value}")
        pointer=self.store.get_pointer("current_baseline",candidate.lineage_id.value)
        current_baseline_id=pointer["value"] if pointer else None
        expected_predecessor=candidate.predecessor_baseline_id.value if candidate.predecessor_baseline_id else None
        if current_baseline_id != expected_predecessor:
            with self.store.transaction():
                run=self._production_from(self.store.get("production_run",production_run_id))
                if run.current_state is ProductionState.PR_15_IMPLEMENTATION_APPROVED:
                    run=self._transition_production(run,ProductionEvent.STALE_BASELINE_DETECTED,actor_principal_id)
                    self._audit(actor_principal_id,"stale_baseline_detected","candidate",candidate_id,{
                        "locked_predecessor":expected_predecessor,
                        "current_predecessor":current_baseline_id,
                        "production_state":run.current_state.value,
                    })
            raise PermissionError("STALE_BASELINE: B09 closure eligibility invalid until reconciliation")
        eligibility=self.store.get_immutable("b09_closure_eligibility",candidate.candidate_id.value)
        if eligibility.get("standing") != "ELIGIBLE" or eligibility.get("review_id") != review_id:
            raise PermissionError("B09ClosureEligibility is not ELIGIBLE for this exact review/candidate")
        if eligibility.get("candidate_hash") != candidate.candidate_hash.value:
            raise PermissionError("B09ClosureEligibility candidate identity mismatch")
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
            promotion_holder=production_run_id
            promotion_token=self.store.acquire_fencing_token(candidate.lineage_id.value,promotion_holder)
            self.store.add("freeze", frozen_id.value, self._freeze_payload(record))
            self.store.add_immutable("freeze_closure", frozen_id.value, {
                "production_run_id": production_run_id,
                "canonical_promotion_lock_holder": promotion_holder,
                "canonical_promotion_fencing_token": promotion_token,
                "locked_predecessor_baseline_id": expected_predecessor,
                "candidate_id": candidate_id,
                "candidate_hash": candidate.candidate_hash.value,
                "artifact_blob_hash": candidate.artifact_blob_hash.value,
                "logical_payload_identity": candidate.logical_payload_identity.value,
                "manifest_identity": candidate.manifest_identity.value,
                "review_id": review_id,
                "freeze_custody_workspace": candidate.workspace_id,
            })
            run=self._production_from(self.store.get("production_run",production_run_id))
            run=self._transition_production(run,ProductionEvent.IMPLEMENTATION_FROZEN_ACCEPTED,actor_principal_id)
            self._audit(actor_principal_id, "candidate_frozen", "freeze", frozen_id.value, {"candidate_id": candidate_id, "candidate_hash": candidate.candidate_hash.value, "review_id": review_id, "grant_id": grant.grant_id, "production_state":run.current_state.value})
        return record

    def reconcile_stale_baseline(
        self, *, candidate_id: str, actor_principal_id: str, no_design_change: bool,
    ) -> ProductionRunRecord:
        candidate=self._candidate_from(self.store.get("candidate",candidate_id))
        self.authority.require_grant(actor_principal_id,AuthorityScope.BUILD,workspace_id=candidate.workspace_id)
        production_run_id=f"production-run:{candidate_id}"
        with self.store.transaction():
            run=self._production_from(self.store.get("production_run",production_run_id))
            if run.current_state is not ProductionState.PR_15R_BASELINE_RECONCILIATION_REQUIRED:
                raise PermissionError(f"baseline reconciliation requires PR-15R, got {run.current_state.value}")
            event=(
                ProductionEvent.STALE_RECONCILED_NO_DESIGN_CHANGE
                if no_design_change else
                ProductionEvent.STALE_RECONCILIATION_INVALIDATES_DESIGN
            )
            run=self._transition_production(run,event,actor_principal_id)
            self.store.add_immutable("baseline_reconciliation",f"{production_run_id}:{run.consistency_version}",{
                "candidate_id":candidate_id,
                "locked_predecessor":candidate.predecessor_baseline_id.value if candidate.predecessor_baseline_id else None,
                "current_predecessor":(
                    self.store.get_pointer("current_baseline",candidate.lineage_id.value) or {}
                ).get("value"),
                "outcome":"NO_DESIGN_CHANGE" if no_design_change else "DESIGN_INVALIDATED",
                "to_state":run.current_state.value,
                "recovery_epoch":self.store.recovery_epoch(),
            })
            self._audit(actor_principal_id,"baseline_reconciled","candidate",candidate_id,{
                "outcome":"NO_DESIGN_CHANGE" if no_design_change else "DESIGN_INVALIDATED",
                "production_state":run.current_state.value,
            })
            return run

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
            freeze_closure=self.store.get_immutable("freeze_closure",frozen_artifact_id)
            promotion_holder=str(freeze_closure["canonical_promotion_lock_holder"])
            token=int(freeze_closure["canonical_promotion_fencing_token"])
            if promotion_holder != f"production-run:{freeze.frozen_artifact.source_candidate_id.value}":
                raise PermissionError("freeze/promotion lock holder binding mismatch")
            lock=self.store.promotion_lock(lineage_id)
            if lock is None or lock["holder"] != promotion_holder or int(lock["fencing_token"]) != token:
                raise PermissionError("continuous B09 canonical promotion lock is not held")
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
            for dep_payload in self.store.list("deployment"):
                if dep_payload.get("lineage_id") != lineage_id or dep_payload.get("baseline_id") == baseline_id:
                    continue
                dep=self._deployment_from(dep_payload)
                if dep.grant_standing is DeploymentGrantStanding.ACTIVE:
                    dep=replace(
                        dep,
                        grant_standing=grant_next(dep.grant_standing,GrantEvent.TARGET_SUPERSEDED,"REVALIDATION_REQUIRED"),
                        runtime_standing=(
                            runtime_next(dep.runtime_standing,RuntimeEvent.TARGET_SUPERSEDED,"REVALIDATION_REQUIRED")
                            if dep.runtime_standing is RuntimeDeploymentStanding.ACTIVE else dep.runtime_standing
                        ),
                    )
                    self._save_deployment(dep)
                    self._audit(actor_principal_id,"deployment_target_superseded","deployment",dep.deployment_id,{
                        "new_baseline_id":baseline_id,"new_pointer_version":version,
                    })
            self.store.add_immutable("promotion_closure", baseline_id, {
                "lineage_id": lineage_id,
                "frozen_artifact_id": frozen_artifact_id,
                "predecessor_baseline_id": expected_predecessor_baseline_id,
                "fencing_token": token,
                "canonical_promotion_lock_holder": promotion_holder,
                "pointer_version": version,
                "recovery_epoch": self.store.recovery_epoch(),
            })
            production_run_id=f"production-run:{freeze.frozen_artifact.source_candidate_id.value}"
            run=self._production_from(self.store.get("production_run",production_run_id))
            if run.current_state is not ProductionState.PR_16_IMPLEMENTATION_FROZEN:
                raise PermissionError(f"canonical closure requires PR-16, got {run.current_state.value}")
            run=self._transition_production(run,ProductionEvent.CANONICAL_CLOSURE_COMPLETE,actor_principal_id)
            self.store.release_promotion_lock(lineage_id,holder=promotion_holder,fencing_token=token)
            self._audit(actor_principal_id, "baseline_promoted", "baseline", baseline_id, {"lineage_id": lineage_id, "frozen_artifact_id": frozen_artifact_id, "predecessor": expected_predecessor_baseline_id, "grant_id": grant.grant_id, "fencing_token": token, "pointer_version": version, "production_state":run.current_state.value})
        return record

    def authorize_deployment(
        self, *, deployment_id: str, frozen_artifact_id: str, actor_principal_id: str,
        runtime_profile: dict, environment: dict, provider_binding: dict,
        secret_scope: dict, permission_scope: dict, policy: dict, runtime_boundary: dict,
    ) -> DeploymentAuthorityRecord:
        freeze=self._freeze_from(self.store.get("freeze",frozen_artifact_id))
        candidate=self._candidate_from(self.store.get("candidate",freeze.frozen_artifact.source_candidate_id.value))
        grant=self.authority.require_grant(actor_principal_id,AuthorityScope.DEPLOY,workspace_id=candidate.workspace_id)
        with self.store.transaction():
            pointer=self.store.get_pointer("current_baseline",freeze.lineage_id.value)
            if pointer is None: raise PermissionError("lineage has no current baseline")
            current=self._baseline_from(self.store.get("baseline",pointer["value"]))
            if current.frozen_artifact_id != freeze.frozen_artifact.id:
                raise PermissionError("deployment target is not canonical current baseline")
            if not all(isinstance(x,dict) and x for x in (runtime_profile,environment,provider_binding,policy,runtime_boundary)):
                raise PermissionError("runtime profile/environment/provider/policy/boundary snapshots must be explicit and non-empty")
            realization=RuntimeRealizationSnapshot(
                snapshot_id=f"runtime-realization:{uuid4().hex}",target_ref=frozen_artifact_id,
                runtime_profile=runtime_profile,environment=environment,provider_binding=provider_binding,
                secret_scope=secret_scope,permission_scope=permission_scope,policy=policy,runtime_boundary=runtime_boundary,
            )
            # Conservative runtime-boundary subset: requested true/list capabilities must be admitted by policy.
            allowed=dict(policy.get("authority_boundary",{}))
            for key,value in runtime_boundary.items():
                if key not in allowed or (isinstance(value,bool) and value and not bool(allowed[key])):
                    raise PermissionError(f"runtime boundary exceeds deployment policy: {key}")
                if isinstance(value,list) and not set(value).issubset(set(allowed.get(key,[]))):
                    raise PermissionError(f"runtime boundary exceeds deployment policy: {key}")
            grant_standing=grant_next(DeploymentGrantStanding.NONE,GrantEvent.GRANT_CREATED)
            runtime_standing=runtime_next(RuntimeDeploymentStanding.NONE,RuntimeEvent.RUNTIME_DEPLOYMENT_CONSTITUTED)
            rec=DeploymentAuthorityRecord(
                deployment_id=deployment_id,frozen_artifact_id=frozen_artifact_id,
                lineage_id=freeze.lineage_id.value,baseline_id=current.baseline_id.value,
                grant_id=grant.grant_id,grant_standing=grant_standing,runtime_standing=runtime_standing,
                realization_snapshot_id=realization.snapshot_id,realization_identity=realization.identity,
                recovery_epoch=self.store.recovery_epoch(),current_baseline_version=int(pointer["version"]),
            )
            payload={
                "deployment_id":rec.deployment_id,"frozen_artifact_id":rec.frozen_artifact_id,
                "lineage_id":rec.lineage_id,"baseline_id":rec.baseline_id,"grant_id":rec.grant_id,
                "grant_standing":rec.grant_standing.value,"runtime_standing":rec.runtime_standing.value,
                "realization_snapshot_id":rec.realization_snapshot_id,"realization_identity":rec.realization_identity,
                "recovery_epoch":rec.recovery_epoch,"current_baseline_version":rec.current_baseline_version,
                "activation_result_ref":"","safety_hold":False,"revocation_reason":"",
            }
            self.store.add("deployment",deployment_id,payload)
            self.store.add_immutable("runtime_realization",realization.snapshot_id,{
                "identity":realization.identity,"target_ref":frozen_artifact_id,
                "runtime_profile":runtime_profile,"environment":environment,"provider_binding":provider_binding,
                "secret_scope":secret_scope,"permission_scope":permission_scope,"policy":policy,
                "runtime_boundary":runtime_boundary,
            })
            self._audit(actor_principal_id,"deployment_authorized","deployment",deployment_id,{
                "target":frozen_artifact_id,"baseline":current.baseline_id.value,
                "realization_identity":realization.identity,"grant_id":grant.grant_id,
            })
        return rec

    @staticmethod
    def _deployment_from(data: dict) -> DeploymentAuthorityRecord:
        return DeploymentAuthorityRecord(
            deployment_id=data["deployment_id"],frozen_artifact_id=data["frozen_artifact_id"],
            lineage_id=data["lineage_id"],baseline_id=data["baseline_id"],grant_id=data["grant_id"],
            grant_standing=DeploymentGrantStanding(data["grant_standing"]),
            runtime_standing=RuntimeDeploymentStanding(data["runtime_standing"]),
            realization_snapshot_id=data["realization_snapshot_id"],realization_identity=data["realization_identity"],
            recovery_epoch=int(data["recovery_epoch"]),current_baseline_version=int(data["current_baseline_version"]),
            activation_result_ref=data.get("activation_result_ref",""),safety_hold=bool(data.get("safety_hold",False)),
            revocation_reason=data.get("revocation_reason",""),
        )

    def _save_deployment(self, rec: DeploymentAuthorityRecord) -> None:
        self.store.put("deployment",rec.deployment_id,{
            "deployment_id":rec.deployment_id,"frozen_artifact_id":rec.frozen_artifact_id,
            "lineage_id":rec.lineage_id,"baseline_id":rec.baseline_id,"grant_id":rec.grant_id,
            "grant_standing":rec.grant_standing.value,"runtime_standing":rec.runtime_standing.value,
            "realization_snapshot_id":rec.realization_snapshot_id,"realization_identity":rec.realization_identity,
            "recovery_epoch":rec.recovery_epoch,"current_baseline_version":rec.current_baseline_version,
            "activation_result_ref":rec.activation_result_ref,"safety_hold":rec.safety_hold,
            "revocation_reason":rec.revocation_reason,
        })

    def begin_activation(self, *, deployment_id: str, actor_principal_id: str) -> str:
        rec=self._deployment_from(self.store.get("deployment",deployment_id))
        freeze=self._freeze_from(self.store.get("freeze",rec.frozen_artifact_id))
        candidate=self._candidate_from(self.store.get("candidate",freeze.frozen_artifact.source_candidate_id.value))
        self.authority.require_grant(actor_principal_id,AuthorityScope.DEPLOY,workspace_id=candidate.workspace_id)
        with self.store.transaction():
            rec=self._deployment_from(self.store.get("deployment",deployment_id))
            if rec.recovery_epoch != self.store.recovery_epoch():
                raise PermissionError("STALE_RECOVERY_EPOCH")
            pointer=self.store.get_pointer("current_baseline",rec.lineage_id)
            if pointer is None or pointer["value"] != rec.baseline_id or int(pointer["version"]) != rec.current_baseline_version:
                raise PermissionError("activation-time target currentness assessment failed")
            if rec.grant_standing is not DeploymentGrantStanding.ACTIVE or rec.safety_hold:
                raise PermissionError("activation-time grant/safety standing invalid")
            realization=self.store.get_immutable("runtime_realization",rec.realization_snapshot_id)
            if realization["identity"] != rec.realization_identity:
                raise PermissionError("runtime realization drift")
            activating=runtime_next(rec.runtime_standing,RuntimeEvent.ACTIVATION_REQUESTED,"ACTIVATION_ADMISSIBLE")
            attempt_id=f"activation-attempt:{uuid4().hex}"
            rec=replace(rec,runtime_standing=activating)
            self._save_deployment(rec)
            self.store.add("activation_attempt",attempt_id,{
                "activation_attempt_id":attempt_id,
                "deployment_id":deployment_id,
                "standing":"PENDING_EXTERNAL_RESULT",
                "realization_identity":rec.realization_identity,
                "recovery_epoch":rec.recovery_epoch,
                "external_runtime_identity":"",
                "failure_reason":"",
            })
            self.store.add_immutable("activation_assessment",attempt_id,{
                "deployment_id":deployment_id,
                "standing":"ACTIVATION_ADMISSIBLE",
                "grant_standing":rec.grant_standing.value,
                "runtime_standing_before":"AUTHORIZED_NOT_ACTIVE",
                "current_baseline":rec.baseline_id,
                "baseline_version":rec.current_baseline_version,
                "realization_identity":rec.realization_identity,
                "recovery_epoch":rec.recovery_epoch,
            })
            self._audit(actor_principal_id,"activation_requested","deployment",deployment_id,{"activation_attempt_id":attempt_id})
        return attempt_id

    def reconcile_activation(
        self, *, activation_attempt_id: str, actor_principal_id: str,
        outcome: str, external_runtime_identity: str = "", failure_reason: str = "",
    ) -> DeploymentAuthorityRecord:
        attempt=self.store.get("activation_attempt",activation_attempt_id)
        deployment_id=attempt["deployment_id"]
        rec=self._deployment_from(self.store.get("deployment",deployment_id))
        freeze=self._freeze_from(self.store.get("freeze",rec.frozen_artifact_id))
        candidate=self._candidate_from(self.store.get("candidate",freeze.frozen_artifact.source_candidate_id.value))
        self.authority.require_grant(actor_principal_id,AuthorityScope.DEPLOY,workspace_id=candidate.workspace_id)
        outcome=outcome.upper()
        with self.store.transaction():
            attempt=self.store.get("activation_attempt",activation_attempt_id)
            rec=self._deployment_from(self.store.get("deployment",deployment_id))
            if attempt["standing"] not in {"PENDING_EXTERNAL_RESULT","AMBIGUOUS"}:
                if attempt["standing"] == outcome:
                    return rec
                raise PermissionError("activation attempt is already terminal")
            if attempt["recovery_epoch"] != self.store.recovery_epoch():
                raise PermissionError("STALE_RECOVERY_EPOCH")
            if attempt["realization_identity"] != rec.realization_identity:
                raise PermissionError("activation realization identity drift")
            if outcome == "AMBIGUOUS":
                self.store.put("activation_attempt",activation_attempt_id,{
                    **attempt,"standing":"AMBIGUOUS","external_runtime_identity":external_runtime_identity,
                    "failure_reason":failure_reason or "external side effect standing unresolved",
                })
                self._audit(actor_principal_id,"activation_ambiguous","deployment",deployment_id,{"activation_attempt_id":activation_attempt_id})
                return rec
            if outcome == "ACTIVATED":
                if not external_runtime_identity:
                    raise PermissionError("activated reconciliation requires external runtime identity")
                active=runtime_next(rec.runtime_standing,RuntimeEvent.ACTIVATED)
                result_ref=f"activation-result:{uuid4().hex}"
                self.store.add_immutable("activation_result",result_ref,{
                    "activation_attempt_id":activation_attempt_id,"deployment_id":deployment_id,
                    "standing":"ACTIVATED","external_runtime_identity":external_runtime_identity,
                    "realization_identity":rec.realization_identity,"recovery_epoch":rec.recovery_epoch,
                })
                rec=replace(rec,runtime_standing=active,activation_result_ref=result_ref)
                self._save_deployment(rec)
                self.store.put("activation_attempt",activation_attempt_id,{
                    **attempt,"standing":"ACTIVATED","external_runtime_identity":external_runtime_identity,
                    "failure_reason":"",
                })
                self._audit(actor_principal_id,"runtime_activated","deployment",deployment_id,{
                    "activation_attempt_id":activation_attempt_id,"activation_result_ref":result_ref,
                    "external_runtime_identity":external_runtime_identity,
                })
                return rec
            if outcome == "FAILED":
                failed=runtime_next(rec.runtime_standing,RuntimeEvent.ACTIVATION_FAILED)
                result_ref=f"activation-result:{uuid4().hex}"
                self.store.add_immutable("activation_result",result_ref,{
                    "activation_attempt_id":activation_attempt_id,"deployment_id":deployment_id,
                    "standing":"ACTIVATION_FAILED","failure_reason":failure_reason,
                    "realization_identity":rec.realization_identity,"recovery_epoch":rec.recovery_epoch,
                })
                rec=replace(rec,runtime_standing=failed,activation_result_ref=result_ref)
                self._save_deployment(rec)
                self.store.put("activation_attempt",activation_attempt_id,{
                    **attempt,"standing":"FAILED","external_runtime_identity":"",
                    "failure_reason":failure_reason,
                })
                self._audit(actor_principal_id,"activation_failed","deployment",deployment_id,{
                    "activation_attempt_id":activation_attempt_id,"failure_reason":failure_reason,
                })
                return rec
            raise ValueError("activation outcome must be ACTIVATED, FAILED, or AMBIGUOUS")

    def activate_runtime(self, *, deployment_id: str, actor_principal_id: str) -> DeploymentAuthorityRecord:
        attempt_id=self.begin_activation(deployment_id=deployment_id,actor_principal_id=actor_principal_id)
        return self.reconcile_activation(
            activation_attempt_id=attempt_id,actor_principal_id=actor_principal_id,
            outcome="ACTIVATED",external_runtime_identity=f"studio-runtime:{uuid4().hex}",
        )

    def place_safety_hold(self, *, deployment_id: str, actor_principal_id: str) -> DeploymentAuthorityRecord:
        rec=self._deployment_from(self.store.get("deployment",deployment_id))
        freeze=self._freeze_from(self.store.get("freeze",rec.frozen_artifact_id))
        candidate=self._candidate_from(self.store.get("candidate",freeze.frozen_artifact.source_candidate_id.value))
        self.authority.require_grant(actor_principal_id,AuthorityScope.HOLD_DEPLOYMENT,workspace_id=candidate.workspace_id)
        with self.store.transaction():
            rec=self._deployment_from(self.store.get("deployment",deployment_id))
            grant=grant_next(rec.grant_standing,GrantEvent.SAFETY_HOLD_PLACED)
            runtime=runtime_next(rec.runtime_standing,RuntimeEvent.SAFETY_HOLD_PLACED)
            rec=replace(rec,grant_standing=grant,runtime_standing=runtime,safety_hold=True)
            self._save_deployment(rec)
            self._audit(actor_principal_id,"deployment_safety_hold","deployment",deployment_id,{})
        return rec

    def revalidate_deployment(
        self, *, deployment_id: str, actor_principal_id: str, continue_active: bool = False,
    ) -> DeploymentAuthorityRecord:
        rec=self._deployment_from(self.store.get("deployment",deployment_id))
        freeze=self._freeze_from(self.store.get("freeze",rec.frozen_artifact_id))
        candidate=self._candidate_from(self.store.get("candidate",freeze.frozen_artifact.source_candidate_id.value))
        self.authority.require_grant(actor_principal_id,AuthorityScope.DEPLOY,workspace_id=candidate.workspace_id)
        with self.store.transaction():
            rec=self._deployment_from(self.store.get("deployment",deployment_id))
            realization=self.store.get_immutable("runtime_realization",rec.realization_snapshot_id)
            pointer=self.store.get_pointer("current_baseline",rec.lineage_id)
            policy=dict(realization.get("policy",{}))
            target_current=pointer is not None and pointer["value"] == rec.baseline_id
            allow_superseded=bool(policy.get("allow_superseded_target",False))
            checks={
                "recovery_epoch_current":rec.recovery_epoch == self.store.recovery_epoch(),
                "realization_identity_current":realization.get("identity") == rec.realization_identity,
                "grant_not_revoked":rec.grant_standing not in {DeploymentGrantStanding.REVOKED,DeploymentGrantStanding.EXPIRED},
                "target_currentness_allowed":target_current or allow_superseded,
            }
            assessment_ref=f"deployment-revalidation:{uuid4().hex}"
            outcome="REVALIDATED_CONTINUE_ALLOWED" if all(checks.values()) else "REVALIDATION_DENIED"
            self.store.add_immutable("deployment_revalidation",assessment_ref,{
                "deployment_id":deployment_id,"checks":checks,"outcome":outcome,
                "pointer_value":pointer["value"] if pointer else None,
                "pointer_version":int(pointer["version"]) if pointer else None,
                "recovery_epoch":self.store.recovery_epoch(),
            })
            if outcome == "REVALIDATION_DENIED":
                if rec.grant_standing in {DeploymentGrantStanding.SUSPENDED,DeploymentGrantStanding.SUPERSEDED_TARGET_REVALIDATION_REQUIRED}:
                    rec=replace(rec,grant_standing=grant_next(rec.grant_standing,GrantEvent.REVALIDATION_DENIED))
                if rec.runtime_standing in {RuntimeDeploymentStanding.SAFETY_HELD,RuntimeDeploymentStanding.REVALIDATION_REQUIRED}:
                    rec=replace(rec,runtime_standing=runtime_next(rec.runtime_standing,RuntimeEvent.REVALIDATION_DENIED))
                self._save_deployment(rec)
                self._audit(actor_principal_id,"deployment_revalidation_denied","deployment",deployment_id,{"assessment_ref":assessment_ref})
                return rec
            if rec.safety_hold and rec.grant_standing is DeploymentGrantStanding.SUSPENDED:
                rec=replace(
                    rec,
                    grant_standing=grant_next(rec.grant_standing,GrantEvent.SAFETY_HOLD_REMOVED_AND_REVALIDATED,"REVALIDATED_CONTINUE_ALLOWED"),
                    runtime_standing=runtime_next(rec.runtime_standing,RuntimeEvent.SAFETY_HOLD_REMOVED),
                    safety_hold=False,
                )
            elif rec.grant_standing is DeploymentGrantStanding.SUPERSEDED_TARGET_REVALIDATION_REQUIRED:
                rec=replace(
                    rec,
                    grant_standing=grant_next(rec.grant_standing,GrantEvent.REVALIDATED,"REVALIDATED_CONTINUE_ALLOWED"),
                )
            if rec.runtime_standing is RuntimeDeploymentStanding.REVALIDATION_REQUIRED:
                condition="CONTINUE_ACTIVE" if continue_active else "CONTINUE_INACTIVE"
                rec=replace(rec,runtime_standing=runtime_next(rec.runtime_standing,RuntimeEvent.REVALIDATED,condition))
            self._save_deployment(rec)
            self._audit(actor_principal_id,"deployment_revalidated","deployment",deployment_id,{
                "assessment_ref":assessment_ref,"continue_active":continue_active,
            })
            return rec

    def revoke_deployment(self, *, deployment_id: str, actor_principal_id: str, reason: str) -> DeploymentAuthorityRecord:
        rec=self._deployment_from(self.store.get("deployment",deployment_id))
        freeze=self._freeze_from(self.store.get("freeze",rec.frozen_artifact_id))
        candidate=self._candidate_from(self.store.get("candidate",freeze.frozen_artifact.source_candidate_id.value))
        self.authority.require_grant(actor_principal_id,AuthorityScope.REVOKE_DEPLOYMENT,workspace_id=candidate.workspace_id)
        with self.store.transaction():
            rec=self._deployment_from(self.store.get("deployment",deployment_id))
            grant=grant_next(rec.grant_standing,GrantEvent.GRANT_REVOKED)
            condition="REVOKE_RUNNING" if rec.runtime_standing is RuntimeDeploymentStanding.ACTIVE else "DEFAULT"
            runtime=runtime_next(rec.runtime_standing,RuntimeEvent.GRANT_REVOKED,condition)
            rec=replace(rec,grant_standing=grant,runtime_standing=runtime,revocation_reason=reason)
            self._save_deployment(rec)
            self._audit(actor_principal_id,"deployment_revoked","deployment",deployment_id,{"reason":reason})
        return rec

    def stop_runtime(self, *, deployment_id: str, actor_principal_id: str) -> DeploymentAuthorityRecord:
        rec=self._deployment_from(self.store.get("deployment",deployment_id))
        freeze=self._freeze_from(self.store.get("freeze",rec.frozen_artifact_id))
        candidate=self._candidate_from(self.store.get("candidate",freeze.frozen_artifact.source_candidate_id.value))
        self.authority.require_grant(actor_principal_id,AuthorityScope.DEPLOY,workspace_id=candidate.workspace_id)
        with self.store.transaction():
            rec=self._deployment_from(self.store.get("deployment",deployment_id))
            stopping=runtime_next(rec.runtime_standing,RuntimeEvent.STOP_REQUESTED)
            rec=replace(rec,runtime_standing=stopping)
            self._save_deployment(rec)
            stopped=runtime_next(rec.runtime_standing,RuntimeEvent.STOPPED)
            rec=replace(rec,runtime_standing=stopped)
            self._save_deployment(rec)
            self._audit(actor_principal_id,"runtime_stopped","deployment",deployment_id,{})
        return rec

    def deploy(self, *, deployment_id: str, frozen_artifact_id: str, actor_principal_id: str):
        raise PermissionError("direct deploy/activate is disabled; authorize deployment with exact runtime snapshots then activate separately")

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
            "production_runs": self.store.list("production_run"),
            "audit": self.store.list_audit(),
        }
