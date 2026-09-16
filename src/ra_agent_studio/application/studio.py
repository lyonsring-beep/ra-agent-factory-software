from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from ra_agent_studio.domain.composition import ModuleBinding, RealizedAgentComposition, realize_composition
from ra_agent_studio.domain.effect import EffectFixture, TestObservation, evaluate_fixture
from ra_agent_studio.domain.evidence import BuildEvidence
from ra_agent_studio.domain.governance import BaselineRecord, FreezeRecord, approve_deployment, designate_baseline, freeze_candidate
from ra_agent_studio.domain.identity import BaselineId, CandidateId, ContentHash, DeploymentId, FrozenArtifactId, LineageId, ModuleId, RevisionId
from ra_agent_studio.domain.module import ModuleRevision, ModuleRevisionState
from ra_agent_studio.domain.review import ReviewRecord, ReviewVerdict, require_independent_reviewer
from ra_agent_studio.infra.memory import InMemoryModuleRepository


class StudioService:
    """Coherent application facade for the Studio implementation blocks.

    Backend state remains authoritative. UI/CLI/API are only command/query surfaces.
    """

    def __init__(self, modules: InMemoryModuleRepository | None = None) -> None:
        self.modules = modules or InMemoryModuleRepository()
        self.compositions: dict[str, RealizedAgentComposition] = {}
        self.evidence: dict[str, BuildEvidence] = {}
        self.reviews: dict[str, ReviewRecord] = {}
        self.freezes: dict[str, FreezeRecord] = {}
        self.baselines: dict[str, BaselineRecord] = {}
        self.deployments: dict[str, object] = {}

    def create_module_revision(self, *, module_id: str, revision_id: str, name: str, content: str, predecessor_revision_id: str | None = None) -> ModuleRevision:
        revision = ModuleRevision.create(
            ModuleId(module_id), RevisionId(revision_id), name=name, content=content,
            predecessor_revision_id=RevisionId(predecessor_revision_id) if predecessor_revision_id else None,
        )
        self.modules.add(revision)
        return revision

    def prepare_candidate(self, revision_id: str) -> ModuleRevision:
        revision = self.modules.get(RevisionId(revision_id))
        candidate = replace(revision, state=ModuleRevisionState.CANDIDATE)
        self.modules.replace(candidate)
        return candidate

    def run_effect_fixture(self, revision_id: str, fixture: EffectFixture) -> TestObservation:
        revision = self.modules.get(RevisionId(revision_id))
        # The sandbox runner is deliberately authority-free. This deterministic reference
        # runner makes the module text and fixture input observable for acceptance testing.
        output = f"{revision.content}\n{fixture.input_text}"
        return evaluate_fixture(fixture, revision.revision_id, output)

    def compose(self, composition_id: str, revision_ids: list[str]) -> RealizedAgentComposition:
        bindings = []
        for revision_id in revision_ids:
            revision = self.modules.get(RevisionId(revision_id))
            bindings.append(ModuleBinding(revision.module_id, revision.revision_id, revision.content_hash))
        composition = realize_composition(composition_id, tuple(bindings))
        self.compositions[composition_id] = composition
        return composition

    def build(self, composition_id: str, *, runtime_identity: str = "ra-agent-factory-v1.11") -> BuildEvidence:
        composition = self.compositions[composition_id]
        artifact_hash = ContentHash.from_bytes((composition.composition_hash.value + runtime_identity).encode())
        evidence = BuildEvidence(
            evidence_id=f"evidence-{uuid4().hex}",
            composition_id=composition_id,
            composition_hash=composition.composition_hash,
            artifact_hash=artifact_hash,
            created_at=datetime.now(UTC),
            reproducible=True,
            runtime_identity=runtime_identity,
        )
        self.evidence[evidence.evidence_id] = evidence
        return evidence

    def review(self, *, subject_id: str, author_id: str, reviewer_id: str, passed: bool) -> ReviewRecord:
        require_independent_reviewer(author_id, reviewer_id)
        record = ReviewRecord(
            review_id=f"review-{uuid4().hex}",
            subject_id=subject_id,
            reviewer_id=reviewer_id,
            verdict=ReviewVerdict.PASS if passed else ReviewVerdict.FAIL,
        )
        self.reviews[record.review_id] = record
        return record

    def freeze(self, *, candidate_id: str, candidate_hash: str, review_id: str) -> FreezeRecord:
        frozen_id = FrozenArtifactId(f"frozen-{uuid4().hex}")
        record = freeze_candidate(
            candidate_id=CandidateId(candidate_id),
            candidate_hash=ContentHash(candidate_hash),
            frozen_artifact_id=frozen_id,
            review=self.reviews[review_id],
            frozen_at=datetime.now(UTC),
        )
        self.freezes[frozen_id.value] = record
        return record

    def create_baseline(self, *, baseline_id: str, lineage_id: str, frozen_artifact_id: str) -> BaselineRecord:
        record = designate_baseline(
            BaselineId(baseline_id), LineageId(lineage_id), self.freezes[frozen_artifact_id]
        )
        self.baselines[baseline_id] = record
        return record

    def deploy(self, *, deployment_id: str, frozen_artifact_id: str):
        frozen = self.freezes[frozen_artifact_id].frozen_artifact
        record = approve_deployment(DeploymentId(deployment_id), frozen)
        self.deployments[deployment_id] = record
        return record