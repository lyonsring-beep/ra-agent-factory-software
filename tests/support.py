from __future__ import annotations

from ra_agent_studio.domain.auth import AuthorityGrant, AuthorityRegistry, AuthorityScope, Principal
from ra_agent_studio.domain.identity import ContentHash
from ra_agent_studio.infra.factory import (
    FACTORY_V111_CANDIDATE_SHA256,
    FACTORY_V111_COMMIT,
    FactoryBuildResult,
)
from ra_agent_studio.infra.runtime import ExternalRuntimeResult


class ContractTestRuntimeLauncher:
    def launch(self, *, deployment_id: str, activation_attempt_id: str, realization: dict) -> ExternalRuntimeResult:
        return ExternalRuntimeResult("ACTIVATED", f"test-runtime:{deployment_id}", f"test provider confirmed launch:{activation_attempt_id}")

    def stop(self, *, deployment_id: str, stop_attempt_id: str, external_runtime_identity: str) -> ExternalRuntimeResult:
        return ExternalRuntimeResult("STOPPED", external_runtime_identity, "test provider confirmed stop")


class AmbiguousTestRuntimeLauncher:
    def launch(self, *, deployment_id: str, activation_attempt_id: str, realization: dict) -> ExternalRuntimeResult:
        return ExternalRuntimeResult("AMBIGUOUS", "", "provider response lost")

    def stop(self, *, deployment_id: str, stop_attempt_id: str, external_runtime_identity: str) -> ExternalRuntimeResult:
        return ExternalRuntimeResult("AMBIGUOUS", external_runtime_identity, "provider response lost")


class ContractTestFactoryRuntime:
    """Test-only Factory adapter; production Studio never selects this adapter implicitly."""

    def realize(self, composition):
        artifact = (
            f"factory-v1.11-test-artifact:{composition.composition_id}:{composition.composition_hash.value}"
        ).encode()
        evidence = (
            f"factory-v1.11-test-evidence:{composition.composition_hash.value}"
        ).encode()
        return FactoryBuildResult(
            artifact_hash=ContentHash.from_bytes(artifact),
            factory_evidence_hash=ContentHash.from_bytes(evidence),
            runtime_commit=FACTORY_V111_COMMIT,
            factory_candidate_sha256=FACTORY_V111_CANDIDATE_SHA256,
            reproducible=True,
            artifact_path="test-only://artifact",
            evidence_path="test-only://evidence",
            artifact_bytes=artifact,
            logical_payload_identity=ContentHash.from_bytes(b"logical:"+artifact),
            manifest_identity=ContentHash.from_bytes(b"manifest:"+artifact),
            factory_candidate_revision_id="factory-test-revision",
        )


def authority_registry() -> AuthorityRegistry:
    registry = AuthorityRegistry()
    principals = {
        "builder": "builder-token",
        "reviewer": "reviewer-token",
        "freezer": "freezer-token",
        "promoter": "promoter-token",
        "deployer": "deployer-token",
    }
    for principal_id, token in principals.items():
        principal_workspace = "review-ws" if principal_id == "reviewer" else "ws"
        registry.add_principal(Principal(principal_id, principal_workspace), bearer_token=token)
    registry.add_grant(
        AuthorityGrant(
            "grant-build",
            "builder",
            frozenset({
                AuthorityScope.DESIGN_AUTHORING,
                AuthorityScope.IMPLEMENTATION_AUTHORING,
                AuthorityScope.BUILD,
            }),
            "ws",
        )
    )
    registry.add_grant(
        AuthorityGrant(
            "grant-review",
            "reviewer",
            frozenset({AuthorityScope.REVIEW}),
            "ws",
            review_methods=frozenset({"external_ai"}),
            independent_of_principals=frozenset({"builder"}),
            independent_of_workspaces=frozenset({"ws"}),
            authority_source="external-review-authority",
            target_scope="exact_candidate_in_workspace",
        )
    )
    registry.add_grant(
        AuthorityGrant("grant-freeze", "freezer", frozenset({AuthorityScope.FREEZE}), "ws")
    )
    registry.add_grant(
        AuthorityGrant(
            "grant-promote",
            "promoter",
            frozenset({AuthorityScope.PROMOTE_BASELINE}),
            "ws",
        )
    )
    registry.add_grant(
        AuthorityGrant("grant-deploy", "deployer", frozenset({AuthorityScope.DEPLOY, AuthorityScope.HOLD_DEPLOYMENT, AuthorityScope.REVOKE_DEPLOYMENT}), "ws")
    )
    return registry
