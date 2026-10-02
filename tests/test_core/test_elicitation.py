"""Unit and integration tests for MCP Human Elicitation authorization gates.

Zero Emojis Policy strictly enforced across all docstrings, assertions, and logs.
"""

import asyncio

import pytest
from mcp.server.elicitation import render_elicitation_schema
from pydantic import BaseModel, Field

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
    assert gate.is_critical_action("  delete_world_save  ") is True
    assert gate.is_critical_action("in_game_purchase") is True
    assert gate.is_critical_action("wipe_inventory") is True
    assert gate.is_critical_action("look_around") is False
    assert gate.is_critical_action("press_key") is False

    gate.register_critical_action("nuke_database")
    assert gate.is_critical_action("nuke_database") is True
    assert gate.is_critical_action("NUKE_DATABASE") is True

    gate.unregister_critical_action("nuke_database")
    assert gate.is_critical_action("nuke_database") is False


@pytest.mark.asyncio
async def test_elicitation_gate_constructor_normalization() -> None:
    """Gate initialized with mixed-case and padded actions must normalize entries."""
    custom_actions = {"  Format_Storage  ", "PURCHASE_COINS", "drop_items"}
    gate = ElicitationGate(critical_actions=custom_actions)
    assert gate.is_critical_action("format_storage") is True
    assert gate.is_critical_action("FORMAT_STORAGE") is True
    assert gate.is_critical_action("purchase_coins") is True
    assert gate.is_critical_action("drop_items") is True
    assert gate.is_critical_action("delete_save") is False


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
    assert resp.decision == "accept"
    assert resp.responder == "auto_approver"
    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["action"] == "delete_world_save"
    assert history[0]["approved"] is True
    assert history[0]["responder"] == "auto_approver"


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
    assert exc_info.value.error_code == -32006
    assert exc_info.value.data == {"action": "overwrite_save"}

    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["approved"] is False
    assert history[0]["responder"] == "system"


@pytest.mark.asyncio
async def test_elicitation_gate_approval_handler() -> None:
    """Registered handler returning approved=True must return approved ElicitationResponse."""
    gate = ElicitationGate()

    async def mock_handler(req: ElicitationRequest) -> ElicitationResponse:
        assert req.action == "format_storage"
        assert req.risk_level == "critical"
        assert req.metadata.get("drive") == "slot_0"
        return ElicitationResponse(
            action=req.action,
            approved=True,
            decision="accept",
            reason="Authorized by test administrator",
            responder="test_user",
        )

    gate.set_handler(mock_handler)
    resp = await gate.request_authorization(
        action="format_storage",
        risk_level="critical",
        metadata={"drive": "slot_0"},
    )
    assert resp.approved is True
    assert resp.decision == "accept"
    assert resp.responder == "test_user"
    assert resp.reason == "Authorized by test administrator"

    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["approved"] is True
    assert history[0]["decision"] == "accept"


@pytest.mark.asyncio
async def test_elicitation_gate_denial_handler() -> None:
    """Registered handler returning approved=False must raise ElicitationDeniedError."""
    gate = ElicitationGate()

    async def mock_reject_handler(req: ElicitationRequest) -> ElicitationResponse:
        return ElicitationResponse(
            action=req.action,
            approved=False,
            decision="decline",
            reason="User denied action in confirmation modal",
            responder="user",
        )

    gate.set_handler(mock_reject_handler)
    with pytest.raises(ElicitationDeniedError) as exc_info:
        await gate.request_authorization(
            action="in_game_purchase",
            risk_level="high",
        )
    assert "in_game_purchase" in str(exc_info.value)
    assert exc_info.value.error_code == -32006

    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["approved"] is False
    assert history[0]["decision"] == "decline"
    assert "User denied action" in history[0]["reason"]


@pytest.mark.asyncio
async def test_elicitation_gate_timeout() -> None:
    """Handler exceeding timeout_sec must raise ElicitationDeniedError."""
    gate = ElicitationGate(default_timeout_sec=0.05)

    async def slow_handler(req: ElicitationRequest) -> ElicitationResponse:
        await asyncio.sleep(0.5)
        return ElicitationResponse(action=req.action, approved=True, decision="accept")

    gate.set_handler(slow_handler)
    with pytest.raises(ElicitationDeniedError) as exc_info:
        await gate.request_authorization(
            action="reset_all_settings",
            timeout_sec=0.05,
        )
    assert "reset_all_settings" in str(exc_info.value)
    assert exc_info.value.error_code == -32006

    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["approved"] is False
    assert history[0]["decision"] == "cancel"
    assert "timed out" in history[0]["reason"]


@pytest.mark.asyncio
async def test_elicitation_gate_handler_exception() -> None:
    """Handler raising unexpected exception must be trapped and raise ElicitationDeniedError."""
    gate = ElicitationGate()

    async def faulty_handler(req: ElicitationRequest) -> ElicitationResponse:
        raise ConnectionResetError("Remote UI transport disconnected")

    gate.set_handler(faulty_handler)
    with pytest.raises(ElicitationDeniedError) as exc_info:
        await gate.request_authorization(action="wipe_inventory")
    assert "wipe_inventory" in str(exc_info.value)
    assert exc_info.value.error_code == -32006

    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["approved"] is False
    assert history[0]["decision"] == "cancel"
    assert "Handler exception" in history[0]["reason"]


@pytest.mark.asyncio
async def test_elicitation_gate_audit_history_immutability() -> None:
    """Audit history returns deep copies preventing external corruption of records."""
    gate = ElicitationGate(auto_approve=True)
    await gate.request_authorization(action="delete_save")

    history_1 = gate.get_history()
    assert len(history_1) == 1

    # Modifying outer list must not affect internal history
    history_1.clear()
    assert len(gate.get_history()) == 1

    # Modifying inner dictionary must not mutate internal record
    history_2 = gate.get_history()
    history_2[0]["approved"] = False
    history_2[0]["action"] = "tampered"

    internal_record = gate.get_history()[0]
    assert internal_record["approved"] is True
    assert internal_record["action"] == "delete_save"


@pytest.mark.asyncio
async def test_elicitation_gate_three_state_decision_model() -> None:
    """Gate must handle MCP 3-state wire outcomes: accept, decline, and cancel."""
    gate = ElicitationGate()

    async def cancel_handler(req: ElicitationRequest) -> ElicitationResponse:
        return ElicitationResponse(
            action=req.action,
            approved=False,
            decision="cancel",
            reason="User closed modal prompt without answering",
            responder="user",
        )

    gate.set_handler(cancel_handler)
    with pytest.raises(ElicitationDeniedError) as exc_info:
        await gate.request_authorization(action="delete_save")
    assert exc_info.value.error_code == -32006

    history = gate.get_history()
    assert len(history) == 1
    assert history[0]["decision"] == "cancel"
    assert history[0]["approved"] is False


def test_elicitation_primitive_schema_validation() -> None:
    """MCP specification dictates that elicitation form schemas contain only primitive types."""

    class ValidConfirmationSchema(BaseModel):
        confirmed: bool = Field(description="Confirmation status")
        reason: str = Field(default="", description="User justification")
        retry_count: int = Field(default=0, description="Attempt count")

    # Primitive schema must validate cleanly
    render_elicitation_schema(ValidConfirmationSchema)

    class InvalidNestedSchema(BaseModel):
        nested_field: ValidConfirmationSchema

    # Nested non-primitive models must be rejected with TypeError per MCP spec
    with pytest.raises(TypeError) as exc_info:
        render_elicitation_schema(InvalidNestedSchema)
    assert "not a valid PrimitiveSchemaDefinition" in str(exc_info.value)
