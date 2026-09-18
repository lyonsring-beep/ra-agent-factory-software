from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx


BASE=os.environ.get("RA_STUDIO_INTEGRATION_BASE","http://127.0.0.1:8000")
FROZEN_STUDIO_CANDIDATE_SHA256=os.environ.get("RA_STUDIO_FROZEN_CANDIDATE_SHA256","").strip().lower()
if len(FROZEN_STUDIO_CANDIDATE_SHA256) != 64 or any(ch not in "0123456789abcdef" for ch in FROZEN_STUDIO_CANDIDATE_SHA256):
    raise RuntimeError("RA_STUDIO_FROZEN_CANDIDATE_SHA256 must be an exact verified SHA-256 identity")
TOKENS={
    "builder":"builder-token",
    "reviewer":"reviewer-token",
    "freezer":"freezer-token",
    "promoter":"promoter-token",
    "deployer":"deployer-token",
}


def get(path: str):
    r=httpx.get(BASE+path,timeout=30)
    r.raise_for_status()
    return r.json()


def command(actor: str, *, command_id: str, op: str, target: str, idem: str, payload: dict):
    body={
        "command_id":command_id,
        "operation_descriptor_id":op,
        "exact_target_ref":target,
        "workspace_ref":"integration-ws",
        "idempotency_key":idem,
        "expected_recovery_epoch":1,
        "payload":payload,
    }
    r=httpx.post(
        BASE+"/commands",
        headers={"Authorization":f"Bearer {TOKENS[actor]}"},
        json=body,timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"{op} failed {r.status_code}: {r.text}")
    return r.json()


def wait_health():
    deadline=time.time()+60
    while time.time() < deadline:
        try:
            if get("/health") == {"status":"ok"}:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("API health timeout")


def main() -> int:
    wait_health()
    health=get("/health")
    assert health["status"] == "ok"

    module=command(
        "builder",command_id="int-cmd-module",op="op:factory:module-revision-create",
        target="int-r1",idem="int-idem-module",
        payload={
            "module_id":"int-m1","name":"Integration Module",
            "content":"import sys\nprint('integration:' + sys.stdin.read())\n",
            "provided_capabilities":["answer"],"identity_domain":"integration-module",
            "config_json":"{\"mode\":\"integration\"}",
            "agent_requirement_ref":"agent-requirement:integration-v104",
            "agent_authority_boundary_ref":"agent-authority-boundary:integration-v104",
        },
    )
    assert module["standing"] == "COMMITTED"

    composition=command(
        "builder",command_id="int-cmd-compose",op="op:factory:composition-realize",
        target="int-composition",idem="int-idem-compose",
        payload={"revision_ids":["int-r1"]},
    )
    assert composition["standing"] == "COMMITTED"

    sandbox=command(
        "builder",command_id="int-cmd-sandbox",op="op:factory:controlled-execution-run",
        target="int-r1",idem="int-idem-sandbox",
        payload={
            "fixture_id":"int-fixture","input_text":"hello",
            "expected_contains":["integration:hello"],
        },
    )
    assert sandbox["standing"] == "COMMITTED"
    assert sandbox["payload"]["passed"] is True

    build=command(
        "builder",command_id="int-cmd-build",op="op:factory:candidate-build",
        target="int-composition",idem="int-idem-build",
        payload={"lineage_id":"integration-lineage","predecessor_baseline_id":None},
    )
    candidate_id=build["result_ref"]
    assert candidate_id

    review=command(
        "reviewer",command_id="int-cmd-review",op="op:factory:review-decision-ingest",
        target=candidate_id,idem="int-idem-review",
        payload={"review_method":"external_ai","passed":True,"blockers":[]},
    )
    review_id=review["result_ref"]

    freeze=command(
        "freezer",command_id="int-cmd-freeze",op="op:factory:exact-freeze",
        target=candidate_id,idem="int-idem-freeze",
        payload={"review_id":review_id},
    )
    frozen_id=freeze["result_ref"]

    baseline=command(
        "promoter",command_id="int-cmd-promote",op="op:factory:canonical-promote",
        target=frozen_id,idem="int-idem-promote",
        payload={
            "baseline_id":"integration-baseline-v1",
            "lineage_id":"integration-lineage",
            "expected_predecessor_baseline_id":None,
        },
    )
    assert baseline["result_ref"] == "integration-baseline-v1"

    deployment=command(
        "deployer",command_id="int-cmd-deploy-auth",op="op:deployment:authorize-deployment",
        target=frozen_id,idem="int-idem-deploy-auth",
        payload={
            "deployment_id":"integration-deployment-v1",
            "runtime_profile":{"runtime":"python-3.14","mode":"integration"},
            "environment":{"name":"github-actions-integration"},
            "provider_binding":{"provider":"subprocess-integration-provider"},
            "secret_scope":{},
            "permission_scope":{"permissions":[]},
            "policy":{"authority_boundary":{"network":False,"tools":[]}},
            "runtime_boundary":{"network":False,"tools":[]},
        },
    )
    assert deployment["result_ref"] == "integration-deployment-v1"

    activation=command(
        "deployer",command_id="int-cmd-activate",op="op:deployment:activate-runtime",
        target="integration-deployment-v1",idem="int-idem-activate",payload={},
    )
    assert activation["payload"]["runtime_standing"] == "ACTIVE"

    stop=command(
        "deployer",command_id="int-cmd-stop",op="op:deployment:stop-runtime",
        target="integration-deployment-v1",idem="int-idem-stop",payload={},
    )
    assert stop["payload"]["runtime_standing"] == "STOPPED"

    replay=command(
        "deployer",command_id="int-cmd-stop-retry",op="op:deployment:stop-runtime",
        target="integration-deployment-v1",idem="int-idem-stop",payload={},
    )
    assert replay["standing"] == "REPLAYED"

    snapshot=get("/snapshot")
    assert any(x["baseline_id"] == "integration-baseline-v1" for x in snapshot["baselines"])
    dep=[x for x in snapshot["deployments"] if x["deployment_id"] == "integration-deployment-v1"][0]
    assert dep["runtime_standing"] == "STOPPED"
    assert any(x["current_state"] == "PR-17_RUN_COMPLETE" for x in snapshot["production_runs"])

    Path("integration-evidence").mkdir(exist_ok=True)
    Path("integration-evidence/E2E_RESULT.json").write_text(json.dumps({
        "standing":"INTEGRATION_E2E_PASS",
        "candidate_id":candidate_id,
        "review_id":review_id,
        "frozen_artifact_id":frozen_id,
        "baseline_id":"integration-baseline-v1",
        "deployment_id":"integration-deployment-v1",
        "runtime_standing":"STOPPED",
        "factory_runtime_commit":"bc0568926ef70ea6fa7e5e6cc8287c09e041fb4f",
        "factory_frozen_artifact_id":10334979844,
        "studio_frozen_candidate_sha256":FROZEN_STUDIO_CANDIDATE_SHA256,
    },indent=2,sort_keys=True),encoding="utf-8")
    print("INTEGRATION_E2E_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
