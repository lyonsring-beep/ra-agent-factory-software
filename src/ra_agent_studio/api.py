from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .application.studio import StudioService
from .domain.effect import EffectFixture


app = FastAPI(title="RA Agent Studio", version="0.1.0")
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
    expected_contains: list[str] = []


class CompositionCreate(BaseModel):
    composition_id: str
    revision_ids: list[str]


class ReviewCreate(BaseModel):
    subject_id: str
    author_id: str
    reviewer_id: str
    passed: bool


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/modules")
def list_modules():
    return [asdict(item) for item in studio.modules.list()]


@app.post("/modules")
def create_module(body: ModuleCreate):
    try:
        return asdict(studio.create_module_revision(**body.model_dump()))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/modules/{revision_id}/candidate")
def prepare_candidate(revision_id: str):
    try:
        return asdict(studio.prepare_candidate(revision_id))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/modules/{revision_id}/sandbox")
def sandbox(revision_id: str, body: FixtureRun):
    try:
        fixture = EffectFixture(body.fixture_id, body.input_text, tuple(body.expected_contains))
        return asdict(studio.run_effect_fixture(revision_id, fixture))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/compositions")
def compose(body: CompositionCreate):
    try:
        return asdict(studio.compose(body.composition_id, body.revision_ids))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/compositions/{composition_id}/build")
def build(composition_id: str):
    try:
        return asdict(studio.build(composition_id))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/reviews")
def review(body: ReviewCreate):
    try:
        return asdict(studio.review(**body.model_dump()))
    except (ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc