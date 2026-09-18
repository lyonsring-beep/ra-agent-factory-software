from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest
import json
import os


class AuthorityScope(StrEnum):
    DESIGN_AUTHORING = "design_authoring"
    IMPLEMENTATION_AUTHORING = "implementation_authoring"
    REVIEW = "review"
    FREEZE = "freeze"
    PROMOTE_BASELINE = "promote_baseline"
    DEPLOY = "deploy"
    BUILD = "build"
    HOLD_DEPLOYMENT = "hold_deployment"
    REVOKE_DEPLOYMENT = "revoke_deployment"


class GrantStanding(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    workspace_id: str
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class AuthorityGrant:
    grant_id: str
    principal_id: str
    scopes: frozenset[AuthorityScope]
    workspace_id: str
    review_methods: frozenset[str] = frozenset()
    independent_of_principals: frozenset[str] = frozenset()
    independent_of_workspaces: frozenset[str] = frozenset()
    authority_source: str = "server-governance"
    target_scope: str = "exact_workspace"
    constraints: frozenset[str] = frozenset()
    standing: GrantStanding = GrantStanding.ACTIVE
    expires_at: datetime | None = None

    def allows(self, scope: AuthorityScope, *, workspace_id: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        if self.standing is not GrantStanding.ACTIVE:
            return False
        if self.workspace_id != workspace_id or scope not in self.scopes:
            return False
        if not self.authority_source or not self.target_scope:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return True


class AuthorityRegistry:
    """Server-owned principal/grant registry; request bodies cannot mint authority."""

    def __init__(self) -> None:
        self._principals: dict[str, Principal] = {}
        self._token_hash_to_principal: dict[str, str] = {}
        self._grants: dict[str, AuthorityGrant] = {}

    def add_principal(self, principal: Principal, *, bearer_token: str | None = None) -> None:
        self._principals[principal.principal_id] = principal
        if bearer_token is not None:
            self._token_hash_to_principal[sha256(bearer_token.encode()).hexdigest()] = principal.principal_id

    def add_grant(self, grant: AuthorityGrant) -> None:
        if grant.principal_id not in self._principals:
            raise ValueError(f"grant principal is unknown: {grant.principal_id}")
        self._grants[grant.grant_id] = grant

    def principal(self, principal_id: str) -> Principal:
        try:
            return self._principals[principal_id]
        except KeyError as exc:
            raise PermissionError(f"unknown principal: {principal_id}") from exc

    def authenticate_bearer(self, token: str) -> Principal:
        token_hash = sha256(token.encode()).hexdigest()
        for known_hash, principal_id in self._token_hash_to_principal.items():
            if compare_digest(known_hash, token_hash):
                return self.principal(principal_id)
        raise PermissionError("invalid bearer credential")

    def require_grant(
        self,
        principal_id: str,
        scope: AuthorityScope,
        *,
        workspace_id: str,
        review_method: str | None = None,
        now: datetime | None = None,
    ) -> AuthorityGrant:
        self.principal(principal_id)
        matches = [
            grant for grant in self._grants.values()
            if grant.principal_id == principal_id and grant.allows(scope, workspace_id=workspace_id, now=now)
        ]
        if review_method is not None:
            matches = [grant for grant in matches if review_method in grant.review_methods]
        if not matches:
            raise PermissionError(
                f"principal {principal_id} lacks {scope.value} authority for workspace {workspace_id}"
            )
        matches.sort(key=lambda x: x.grant_id)
        return matches[0]

    @classmethod
    def from_environment(cls) -> "AuthorityRegistry":
        registry = cls()
        raw = os.environ.get("RA_STUDIO_AUTHORITY_CONFIG_JSON", "")
        if not raw:
            return registry
        data = json.loads(raw)
        for item in data.get("principals", []):
            registry.add_principal(
                Principal(item["principal_id"], item["workspace_id"], item.get("display_name", "")),
                bearer_token=item.get("bearer_token"),
            )
        for item in data.get("grants", []):
            expires = datetime.fromisoformat(item["expires_at"]) if item.get("expires_at") else None
            registry.add_grant(
                AuthorityGrant(
                    grant_id=item["grant_id"],
                    principal_id=item["principal_id"],
                    scopes=frozenset(AuthorityScope(scope) for scope in item.get("scopes", [])),
                    workspace_id=item["workspace_id"],
                    review_methods=frozenset(item.get("review_methods", [])),
                    independent_of_principals=frozenset(item.get("independent_of_principals", [])),
                    independent_of_workspaces=frozenset(item.get("independent_of_workspaces", [])),
                    authority_source=item.get("authority_source", "server-governance"),
                    target_scope=item.get("target_scope", "exact_workspace"),
                    constraints=frozenset(item.get("constraints", [])),
                    standing=GrantStanding(item.get("standing", "active")),
                    expires_at=expires,
                )
            )
        return registry
