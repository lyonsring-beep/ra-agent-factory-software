from __future__ import annotations

from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def test_fsa_b01_frontend_authoritative_mutations_converge_on_commands() -> None:
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')

    assert "return call('/commands','POST'" in app

    legacy_mutation_fragments=(
        "call('/modules','POST'",
        "call(`/modules/${",
        "call('/effects/compare','POST'",
        "call('/compositions','POST'",
        "call('/reviews','POST'",
        "call('/freezes','POST'",
        "call('/baselines','POST'",
        "call('/deployments','POST'",
    )
    for fragment in legacy_mutation_fragments:
        assert fragment not in app

    assert app.count(",'POST'") == 1


def test_fsa_b01_frontend_exposes_required_command_envelope_session_fields() -> None:
    index=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')

    for field in ('token','workspace','recovery-epoch'):
        assert f'id="{field}"' in index

    for envelope_field in (
        'command_id:',
        'operation_descriptor_id:',
        'exact_target_ref:',
        'workspace_ref:',
        'idempotency_key:',
        'expected_recovery_epoch:',
        'payload',
    ):
        assert envelope_field in app


def test_fsa_b01_frontend_delivery_uses_same_origin_api_proxy() -> None:
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    nginx=(ROOT/'web'/'nginx.conf').read_text(encoding='utf-8')
    compose=(ROOT/'compose.yaml').read_text(encoding='utf-8')

    assert "window.RA_STUDIO_API || '/api'" in app
    assert 'location /api/' in nginx
    assert 'proxy_pass http://api:8000/' in nginx
    assert './web/nginx.conf:/etc/nginx/conf.d/default.conf:ro' in compose
