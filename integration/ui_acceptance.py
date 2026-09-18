from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE=os.environ.get("RA_STUDIO_UI_BASE","http://127.0.0.1:8080")


def main() -> int:
    evidence=Path("acceptance-evidence")
    evidence.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        requests=[]
        page.on("request",lambda request: requests.append({
            "method":request.method,
            "url":request.url,
        }))
        page.goto(BASE,wait_until="networkidle")
        assert page.title() == "RA Agent Studio"
        page.fill("#token","builder-token")
        page.fill("#workspace","integration-ws")
        page.fill("#recovery-epoch","1")
        page.click("#save-session")

        page.click('button[data-view="lab"]')
        page.fill('#module-form input[name="module_id"]',"ui-accept-m")
        page.fill('#module-form input[name="revision_id"]',"ui-accept-r1")
        page.fill('#module-form input[name="name"]',"UI Acceptance")
        page.fill('#module-form textarea[name="content"]',"print('ui-accept')")
        page.fill('#module-form input[name="identity_domain"]',"ui-accept-domain")
        page.fill('#module-form input[name="agent_requirement_ref"]',"agent-requirement:ui-accept")
        page.fill('#module-form input[name="agent_authority_boundary_ref"]',"agent-authority-boundary:ui-accept")
        page.click('#module-form button[type="submit"], #module-form button')
        page.wait_for_function(
            "() => document.querySelector('#lab-result').textContent.includes('COMMITTED')",
            timeout=30000,
        )

        page.click('button[data-view="library"]')
        page.wait_for_function(
            "() => document.querySelector('#module-list').textContent.includes('ui-accept-r1')",
            timeout=30000,
        )

        mutation_requests=[
            x for x in requests
            if x["method"] != "GET" and "/api/" in x["url"]
        ]
        assert mutation_requests
        assert all(x["url"].endswith("/api/commands") for x in mutation_requests)
        assert not any(
            any(legacy in x["url"] for legacy in [
                "/api/modules/","/api/reviews","/api/freezes",
                "/api/baselines","/api/deployments"
            ])
            for x in mutation_requests
        )

        page.screenshot(path=str(evidence/"ui-acceptance.png"),full_page=True)
        (evidence/"UI_ACCEPTANCE_RESULT.json").write_text(json.dumps({
            "standing":"UI_API_INTEGRATION_PASS",
            "title":page.title(),
            "module_revision":"ui-accept-r1",
            "mutation_requests":mutation_requests,
            "single_mutation_endpoint":"/api/commands",
        },indent=2,sort_keys=True),encoding="utf-8")
        browser.close()
    print("UI_API_INTEGRATION_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
