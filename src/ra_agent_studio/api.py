from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .application.studio import StudioService
from .domain.effect import EffectFixture
from .domain.review import ReviewBlocker


app = FastAPI(title="RA Agent Studio", version="0.1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
studio = StudioService()


class ModuleCreate(BaseModel):
    module_id: str
    revision_id: str
    name: str
    content: str
    predecessor_revision_id: str | None = None
    provided_capabilities: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    required_module_ids: list[str] = Field(default_factory=list)
    incompatible_module_ids: list[str] = Field(default_factory=list)
    identity_domain: str = ""
    config_json: str = "{}"


class FixtureRun(BaseModel):
    fixture_id: str
    input_text: str
    expected_contains: list[str] = Field(default_factory=list)


class EffectCompare(BaseModel):
    before_revision_id: str
    after_revision_id: str
    fixture_id: str
    input_text: str
    expected_contains: list[str] = Field(default_factory=list)


class CompositionCreate(BaseModel):
    composition_id: str
    revision_ids: list[str]


class BuildCreate(BaseModel):
    workspace_id: str
    lineage_id: str
    predecessor_baseline_id: str | None = None


class ReviewBlockerInput(BaseModel):
    blocker_id: str
    description: str
    closed: bool = False


class ReviewCreate(BaseModel):
    candidate_id: str
    review_method: str
    passed: bool
    blockers: list[ReviewBlockerInput] = Field(default_factory=list)


class FreezeCreate(BaseModel):
    candidate_id: str
    review_id: str


class BaselineCreate(BaseModel):
    baseline_id: str
    lineage_id: str
    frozen_artifact_id: str
    expected_predecessor_baseline_id: str | None = None


class DeploymentCreate(BaseModel):
    deployment_id: str
    frozen_artifact_id: str


def invoke(fn, *args, **kwargs):
    try:
        return jsonable_encoder(fn(*args, **kwargs))
    except (ValueError, KeyError, PermissionError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


def authenticated_principal(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer credential required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return studio.authority.authenticate_bearer(token)
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/modules")
def list_modules():
    return jsonable_encoder(studio.list_modules())


@app.post("/modules")
def create_module(body: ModuleCreate, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    data = body.model_dump()
    data["provided_capabilities"] = tuple(data["provided_capabilities"])
    data["required_capabilities"] = tuple(data["required_capabilities"])
    data["required_module_ids"] = tuple(data["required_module_ids"])
    data["incompatible_module_ids"] = tuple(data["incompatible_module_ids"])
    return invoke(studio.create_module_revision, actor_principal_id=principal.principal_id, **data)


@app.post("/modules/{revision_id}/candidate")
def prepare_candidate(revision_id: str, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    return invoke(studio.prepare_candidate, revision_id, actor_principal_id=principal.principal_id)


@app.post("/modules/{revision_id}/sandbox")
def sandbox(revision_id: str, body: FixtureRun):
    fixture = EffectFixture(body.fixture_id, body.input_text, tuple(body.expected_contains))
    return invoke(studio.run_effect_fixture, revision_id, fixture)


@app.post("/effects/compare")
def compare_effects(body: EffectCompare):
    fixture = EffectFixture(body.fixture_id, body.input_text, tuple(body.expected_contains))
    return invoke(studio.compare_effect_fixture, body.before_revision_id, body.after_revision_id, fixture)


@app.post("/compositions")
def compose(body: CompositionCreate, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    return invoke(studio.compose, body.composition_id, body.revision_ids, actor_principal_id=principal.principal_id)


@app.post("/compositions/{composition_id}/build")
def build(composition_id: str, body: BuildCreate, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    try:
        evidence, candidate = studio.build(
            composition_id,
            actor_principal_id=principal.principal_id,
            workspace_id=body.workspace_id,
            lineage_id=body.lineage_id,
            predecessor_baseline_id=body.predecessor_baseline_id,
        )
        return {"evidence": jsonable_encoder(evidence), "candidate": jsonable_encoder(candidate)}
    except (ValueError, KeyError, PermissionError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/reviews")
def review(body: ReviewCreate, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    blockers = tuple(ReviewBlocker(x.blocker_id, x.description, x.closed) for x in body.blockers)
    return invoke(
        studio.review,
        candidate_id=body.candidate_id,
        reviewer_principal_id=principal.principal_id,
        review_method=body.review_method,
        passed=body.passed,
        blockers=blockers,
    )


@app.post("/freezes")
def freeze(body: FreezeCreate, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    return invoke(
        studio.freeze,
        candidate_id=body.candidate_id,
        review_id=body.review_id,
        actor_principal_id=principal.principal_id,
    )


@app.post("/baselines")
def baseline(body: BaselineCreate, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    return invoke(studio.create_baseline, actor_principal_id=principal.principal_id, **body.model_dump())


@app.post("/deployments")
def deployment(body: DeploymentCreate, authorization: str | None = Header(default=None)):
    principal = authenticated_principal(authorization)
    return invoke(studio.deploy, actor_principal_id=principal.principal_id, **body.model_dump())


@app.get("/snapshot")
def snapshot():
    return studio.snapshot()
