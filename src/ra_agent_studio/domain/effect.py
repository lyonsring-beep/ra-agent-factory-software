from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .identity import RevisionId


@dataclass(frozen=True, slots=True)
class EffectFixture:
    fixture_id: str
    input_text: str
    expected_contains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TestObservation:
    fixture_id: str
    revision_id: RevisionId
    output_text: str
    passed: bool
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class TestDelta:
    fixture_id: str
    before_revision_id: RevisionId
    after_revision_id: RevisionId
    before_output: str
    after_output: str
    changed: bool
    before_passed: bool
    after_passed: bool


def evaluate_fixture(
    fixture: EffectFixture,
    revision_id: RevisionId,
    output_text: str,
    *,
    executor_identity: str,
) -> TestObservation:
    passed = all(token in output_text for token in fixture.expected_contains)
    return TestObservation(
        fixture_id=fixture.fixture_id,
        revision_id=revision_id,
        output_text=output_text,
        passed=passed,
        metadata={"authority": "observation_only", "executor_identity": executor_identity},
    )


def compare_observations(before: TestObservation, after: TestObservation) -> TestDelta:
    if before.fixture_id != after.fixture_id:
        raise ValueError("effect comparison requires the same fixture")
    return TestDelta(
        fixture_id=before.fixture_id,
        before_revision_id=before.revision_id,
        after_revision_id=after.revision_id,
        before_output=before.output_text,
        after_output=after.output_text,
        changed=before.output_text != after.output_text,
        before_passed=before.passed,
        after_passed=after.passed,
    )
