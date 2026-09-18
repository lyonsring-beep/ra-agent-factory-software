from __future__ import annotations

import json
import sys
from hashlib import sha256


def main() -> int:
    request=json.loads(sys.stdin.read() or "{}")
    operation=request.get("operation")
    deployment_id=str(request.get("deployment_id",""))
    provider_key=str(request.get("provider_idempotency_key",""))
    if not deployment_id or not provider_key:
        print(json.dumps({"standing":"FAILED","detail":"missing deployment/provider idempotency identity"}))
        return 0
    if operation == "launch":
        realization=request.get("realization",{})
        identity="integration-runtime:"+sha256(
            json.dumps(
                {"deployment_id":deployment_id,"provider_key":provider_key,"realization":realization},
                sort_keys=True,separators=(",",":")
            ).encode()
        ).hexdigest()[:24]
        print(json.dumps({
            "standing":"ACTIVATED",
            "external_runtime_identity":identity,
            "detail":"integration provider confirmed launch"
        }))
        return 0
    if operation == "stop":
        external=str(request.get("external_runtime_identity",""))
        if not external:
            print(json.dumps({"standing":"FAILED","detail":"missing external runtime identity"}))
            return 0
        print(json.dumps({
            "standing":"STOPPED",
            "external_runtime_identity":external,
            "detail":"integration provider confirmed stop"
        }))
        return 0
    print(json.dumps({"standing":"FAILED","detail":f"unsupported operation:{operation}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
