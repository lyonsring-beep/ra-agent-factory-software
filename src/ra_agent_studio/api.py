from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .application.control_contracts import CommandEnvelope
from .application.control_plane import StudioControlPlane
from .application.operation_catalog import APPLICATION_OPERATION_CATALOG
from .application.studio import StudioService


app=FastAPI(title="RA Agent Studio")
studio=StudioService()
control_plane=StudioControlPlane(studio)


class CommandSubmit(BaseModel):
    command_id: str
    operation_descriptor_id: str
    exact_target_ref: str
    workspace_ref: str
    idempotency_key: str
    expected_recovery_epoch: int
    payload: dict = Field(default_factory=dict)


def authenticated_principal(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401,"Bearer token required")
    try:
        return studio.authority.authenticate_bearer(authorization.removeprefix("Bearer ").strip())
    except PermissionError as exc:
        raise HTTPException(401,str(exc)) from exc


@app.get("/health")
def health():
    return {"status":"ok"}


@app.get("/operations")
def operations():
    return {
        key:{
            "descriptor_id":value.descriptor_id,
            "intent":value.intent,
            "authority_changing":value.authority_changing,
        }
        for key,value in APPLICATION_OPERATION_CATALOG.items()
    }


@app.get("/modules")
def modules():
    return jsonable_encoder(studio.list_modules())


@app.get("/snapshot")
def snapshot():
    return studio.snapshot()


@app.post("/commands")
def submit_command(body: CommandSubmit, authorization: str | None = Header(default=None)):
    principal=authenticated_principal(authorization)
    command=CommandEnvelope(
        command_id=body.command_id,
        operation_descriptor_id=body.operation_descriptor_id,
        exact_target_ref=body.exact_target_ref,
        principal_ref=principal.principal_id,
        workspace_ref=body.workspace_ref,
        idempotency_key=body.idempotency_key,
        expected_recovery_epoch=body.expected_recovery_epoch,
        payload=body.payload,
    )
    result=control_plane.execute(command)
    if result.standing == "REJECTED":
        raise HTTPException(400,result.rejection_reason or "command rejected")
    return jsonable_encoder(result)
