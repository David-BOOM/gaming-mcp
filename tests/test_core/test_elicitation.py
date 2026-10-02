"""Unit and integration tests for MCP Human Elicitation authorization gates."""

import asyncio

import pytest

from gaming_mcp.core.elicitation import (
    ElicitationGate,
    ElicitationRequest,
    ElicitationResponse,
)
from gaming_mcp.core.exceptions import ElicitationDeniedError


@pytest.mark.asyncio
async def test_elicitation_gate_critical_action_registry() -> None:
    """Gate must recognize standard critical actions and support dynamic registration."""
    gate = ElicitationGate()
    assert gate.is_critical_action("delete_save") is True
    assert gate.is_critical_action("DELETE_SAVE") is True
    assert gate.is_critical_action("delete_world_save") is True
    assert gate.is_critical_action("in_game_purchase") is True
    assert gate.is_critical_action("look_around") is False

    gate.register_critical_action("nuke_database")
    assert gate.is_critical_action("nuke_database") is True

    gate.unregister_critical_action("nuke_database")
    assert gate.is_critical_action("nuke_database") is False


@pytest.mark.asyncio
async def test_elicitation_gate_auto_approve_mode() -> None:
    """When auto_approve is True, gate authorizes without requiring human handler."""
    gate = ElicitationGate(auto_approve=True)
    resp = await gate.request_authorization(
        action="delete_world_save",
        prompt="Delete world?",
        risk_level="critical",
    )
    assert resp.approved is True
    assert resp.responder == "auto_approver"
    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["action"] == "delete_world_save"
    assert history[0]["approved"] is True


@pytest.mark.asyncio
async def test_elicitation_gate_denied_without_handler() -> None:
    """Requesting authorization without a registered handler must raise ElicitationDeniedError."""
    gate = ElicitationGate(auto_approve=False)
    with pytest.raises(ElicitationDeniedError) as exc_info:
        await gate.request_authorization(
            action="overwrite_save",
            prompt="Overwrite slot 1?",
        )
    assert "overwrite_save" in str(exc_info.value)
    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["approved"] is False


@pytest.mark.asyncio
async def test_elicitation_gate_approval_handler() -> None:
    """Registered handler returning approved=True must return ElicitationResponse."""
    gate = ElicitationGate()

    async def mock_handler(req: ElicitationRequest) -> ElicitationResponse:
        assert req.action == "format_storage"
        assert req.risk_level == "critical"
        return ElicitationResponse(
            action=req.action,
            approved=True,
            reason="Authorized by test administrator",
            responder="test_user",
        )

    gate.set_handler(mock_handler)
    resp = await gate.request_authorization(
        action="format_storage",
        risk_level="critical",
    )
    assert resp.approved is True
    assert resp.responder == "test_user"


@pytest.mark.asyncio
async def test_elicitation_gate_denial_handler() -> None:
    """Registered handler returning approved=False must raise ElicitationDeniedError."""
    gate = ElicitationGate()

    async def mock_reject_handler(req: ElicitationRequest) -> ElicitationResponse:
        return ElicitationResponse(
            action=req.action,
            approved=False,
            reason="User denied action in modal dialog",
            responder="user",
        )

    gate.set_handler(mock_reject_handler)
    with pytest.raises(ElicitationDeniedError) as exc_info:
        await gate.request_authorization(
            action="in_game_purchase",
            risk_level="high",
        )
    assert "in_game_purchase" in str(exc_info.value)
    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["approved"] is False


@pytest.mark.asyncio
async def test_elicitation_gate_timeout() -> None:
    """Handler exceeding timeout_sec must raise ElicitationDeniedError."""
    gate = ElicitationGate(default_timeout_sec=0.05)

    async def slow_handler(req: ElicitationRequest) -> ElicitationResponse:
        await asyncio.sleep(0.5)
        return ElicitationResponse(action=req.action, approved=True)

    gate.set_handler(slow_handler)
    with pytest.raises(ElicitationDeniedError):
        await gate.request_authorization(
            action="reset_all_settings",
            timeout_sec=0.05,
        )
