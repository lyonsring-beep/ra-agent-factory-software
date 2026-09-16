from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .application.studio import StudioService
from .domain.effect import EffectFixture


app = FastAPI(title="RA Agent Studio", version="0.1.0")
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


class FixtureRun(BaseModel):
    fixture_id: str
    input_text: str
    expected_contains: list[str] = Field(default_factory=list)


class CompositionCreate(BaseModel):
    composition_id: str
    revision_ids: list[str]


class ReviewCreate(BaseModel):
    subject_id: str
    author_id: str
    reviewer_id: str
    passed: bool


class FreezeCreate(BaseModel):
    candidate_id: str
    candidate_hash: str
    review_id: str


class BaselineCreate(BaseModel):
    baseline_id: str
    lineage_id: str
    frozen_artifact_id: str


class DeploymentCreate(BaseModel):
    deployment_id: str
    frozen_artifact_id: str


def invoke(fn, *args, **kwargs):
    try:
        return asdict(fn(*args, **kwargs))
    except (ValueError, KeyError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/modules")
def list_modules():
    return [asdict(item) for item in studio.modules.list()]


@app.post("/modules")
def create_module(body: ModuleCreate):
    return invoke(studio.create_module_revision, **body.model_dump())


@app.post("/modules/{revision_id}/candidate")
def prepare_candidate(revision_id: str):
    return invoke(studio.prepare_candidate, revision_id)


@app.post("/modules/{revision_id}/sandbox")
def sandbox(revision_id: str, body: FixtureRun):
    fixture = EffectFixture(body.fixture_id, body.input_text, tuple(body.expected_contains))
    return invoke(studio.run_effect_fixture, revision_id, fixture)


@app.post("/compositions")
def compose(body: CompositionCreate):
    return invoke(studio.compose, body.composition_id, body.revision_ids)


@app.post("/compositions/{composition_id}/build")
def build(composition_id: str):
    return invoke(studio.build, composition_id)


@app.post("/reviews")
def review(body: ReviewCreate):
    return invoke(studio.review, **body.model_dump())


@app.post("/freezes")
def freeze(body: FreezeCreate):
    return invoke(studio.freeze, **body.model_dump())


@app.post("/baselines")
def baseline(body: BaselineCreate):
    return invoke(studio.create_baseline, **body.model_dump())


@app.post("/deployments")
def deployment(body: DeploymentCreate):
    return invoke(studio.deploy, **body.model_dump())


@app.get("/snapshot")
def snapshot():
    return {
        "modules": [asdict(x) for x in studio.modules.list()],
        "compositions": [asdict(x) for x in studio.compositions.values()],
        "evidence": [asdict(x) for x in studio.evidence.values()],
        "reviews": [asdict(x) for x in studio.reviews.values()],
        "freezes": [asdict(x) for x in studio.freezes.values()],
        "baselines": [asdict(x) for x in studio.baselines.values()],
        "deployments": [asdict(x) for x in studio.deployments.values()],
    }
