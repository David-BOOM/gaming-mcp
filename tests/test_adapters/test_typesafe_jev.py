"""Unit test suite for TypeSafe JEV System 1 discrete decision adapter."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from gaming_mcp.adapters.typesafe_jev import (
    TypeSafeJEVAdapter,
)
from gaming_mcp.config import GamingMCPConfig, TypeSafeJEVConfig
from gaming_mcp.core.exceptions import AdapterError
from gaming_mcp.io.typesafe import (
    ChoiceAnswer,
    ChoiceQuestion,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneRequest,
    SystemOneResponse,
    TypeSafeClient,
    pcm_to_base64_wav,
)
from gaming_mcp.server import GamingMCPServer


@pytest.fixture
def mock_config() -> GamingMCPConfig:
    """Fixture providing configuration with mock mode enabled."""
    cfg = GamingMCPConfig()
    cfg.adapters.typesafe_jev = TypeSafeJEVConfig(
        model="jev-1.13.0",
        mock_mode=True,
    )
    return cfg


# -----------------------------------------------------------------------------
# Metadata and Validation
# -----------------------------------------------------------------------------


def test_typesafe_adapter_metadata() -> None:
    """Verify TypeSafeJEVAdapter metadata conforms to SPI requirements."""
    adapter = TypeSafeJEVAdapter()
    meta = adapter.metadata
    assert meta.id == "typesafe_jev"
    assert "TypeSafe JEV" in meta.display_name
    assert meta.version == "0.1.0"
    assert meta.requires_display is False
    assert meta.requires_admin_privileges is False
    assert "win32" in meta.supported_platforms


def test_choice_question_validation() -> None:
    """Verify choice criteria requires between 1 and 255 options."""
    # Valid choice question
    q = ChoiceQuestion(
        instructions="Pick best move",
        criteria={"0": "Option A", "1": "Option B"},
    )
    assert q.type == "choice"
    assert len(q.criteria) == 2

    # Empty criteria raises validation error
    with pytest.raises(ValidationError):
        ChoiceQuestion(instructions="Pick move", criteria={})


def test_score_question_validation() -> None:
    """Verify score criteria requires between 2 and 10 levels."""
    # Valid score question
    q = ScoreQuestion(
        instructions="Rate threat",
        criteria=["Low", "Medium", "High"],
    )
    assert q.type == "score"
    assert len(q.criteria) == 3

    # Criteria with < 2 items raises validation error
    with pytest.raises(ValidationError):
        ScoreQuestion(instructions="Rate threat", criteria=["OnlyOne"])

    # Criteria with > 10 items raises validation error
    with pytest.raises(ValidationError):
        ScoreQuestion(
            instructions="Rate threat",
            criteria=[f"Level {i}" for i in range(11)],
        )


def test_systemone_request_validation() -> None:
    """Verify SystemOneRequest requires at least one question."""
    with pytest.raises(ValidationError):
        SystemOneRequest(questions={})


def test_discriminated_union_parsing() -> None:
    """Verify answers deserialize correctly into ChoiceAnswer and ScoreAnswer."""
    payload = {
        "model": "jev-1.13.0",
        "answers": {
            "q_choice": {
                "type": "choice",
                "choice": "attack",
                "confidence": 0.92,
                "probabilities": {"attack": 0.92, "retreat": 0.08},
            },
            "q_score": {
                "type": "score",
                "score": 1.5,
                "confidence": 0.88,
                "legend": {"0": "Safe", "1": "Threat", "2": "Danger"},
                "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6},
            },
        },
        "usage": {"input_tokens": 150, "output_tokens": 30},
        "extra_future_field": "resilience_check",
    }
    resp = SystemOneResponse.model_validate(payload)
    assert isinstance(resp.answers["q_choice"], ChoiceAnswer)
    assert resp.answers["q_choice"].choice == "attack"
    assert isinstance(resp.answers["q_score"], ScoreAnswer)
    assert resp.answers["q_score"].score == 1.5
    assert resp.answers["q_score"].legend["0"] == "Safe"


def test_pcm_to_base64_wav() -> None:
    """Verify PCM audio samples convert to valid data URL."""
    samples = [0.0, 0.5, -0.5, 0.2, -0.2]
    url = pcm_to_base64_wav(samples, sample_rate=44100)
    assert url.startswith("data:audio/wav;base64,")


# -----------------------------------------------------------------------------
# TypeSafeClient Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_mock_mode_evaluation(mock_config: GamingMCPConfig) -> None:
    """Verify client generates deterministic responses in mock mode."""
    client = TypeSafeClient(mock_config.adapters.typesafe_jev)
    req = SystemOneRequest(
        questions={
            "c1": ChoiceQuestion(instructions="Choose", criteria={"a": "Opt A", "b": "Opt B"}),
            "s1": ScoreQuestion(instructions="Rate", criteria=["Low", "High"]),
        }
    )
    resp = await client.evaluate(req)
    assert resp.model == "jev-1.13.0"
    assert "c1" in resp.answers
    assert "s1" in resp.answers
    assert isinstance(resp.answers["c1"], ChoiceAnswer)
    assert resp.answers["c1"].choice == "a"
    assert isinstance(resp.answers["s1"], ScoreAnswer)
    assert resp.answers["s1"].score == 0.0

    telemetry = client.get_telemetry()
    assert telemetry["requests_total"] == 1
    assert telemetry["requests_success"] == 1
    assert telemetry["mock_mode"] is True
    await client.close()


@pytest.mark.asyncio
async def test_client_httpx_mocked_network() -> None:
    """Verify client handles HTTP 200 responses when using httpx."""
    cfg = TypeSafeJEVConfig(mock_mode=False, base_url="https://mock.relayrouter.ai/v1")
    client = TypeSafeClient(cfg)

    mock_resp_data = {
        "model": "jev-1.13.0",
        "answers": {
            "q1": {
                "type": "choice",
                "choice": "opt1",
                "confidence": 0.99,
                "probabilities": {"opt1": 0.99},
            }
        },
        "usage": {"input_tokens": 80, "output_tokens": 15},
    }

    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.json.return_value = mock_resp_data

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_http_resp
        req = SystemOneRequest(
            questions={"q1": ChoiceQuestion(instructions="Test", criteria={"opt1": "Option 1"})}
        )
        resp = await client.evaluate(req)
        assert isinstance(resp.answers["q1"], ChoiceAnswer)
        assert resp.answers["q1"].choice == "opt1"
        assert resp.answers["q1"].confidence == 0.99

    await client.close()


@pytest.mark.asyncio
async def test_client_httpx_error_translation() -> None:
    """Verify client translates HTTP 400/500 errors to AdapterError."""
    cfg = TypeSafeJEVConfig(
        mock_mode=False, base_url="https://mock.relayrouter.ai/v1", max_retries=0
    )
    client = TypeSafeClient(cfg)

    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 400
    mock_http_resp.text = "Invalid choice criteria"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_http_resp
        req = SystemOneRequest(
            questions={"q1": ChoiceQuestion(instructions="Test", criteria={"opt1": "Option 1"})}
        )
        with pytest.raises(AdapterError) as exc_info:
            await client.evaluate(req)
        assert "HTTP 400" in str(exc_info.value)

    await client.close()


# -----------------------------------------------------------------------------
# Adapter Tool Execution Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_lifecycle_and_health(mock_config: GamingMCPConfig) -> None:
    """Verify initialization, health check, and clean shutdown."""
    adapter = TypeSafeJEVAdapter(mock_config)
    assert adapter.is_initialized is False

    initial_health = await adapter.health_check()
    assert initial_health["status"] == "uninitialized"

    await adapter.initialize()
    assert adapter.is_initialized is True

    health = await adapter.health_check()
    assert health["status"] == "healthy"
    assert health["model"] == "jev-1.13.0"
    assert health["mock_mode"] is True

    await adapter.shutdown()
    assert adapter.is_initialized is False


@pytest.mark.asyncio
async def test_tool_jev_evaluate_choice(mock_config: GamingMCPConfig) -> None:
    """Verify jev_evaluate_choice tool execution with dict and list options."""
    adapter = TypeSafeJEVAdapter(mock_config)
    await adapter.initialize()

    # Test with dict options
    args_dict = {
        "instructions": "Select next stance",
        "options": {"offensive": "Aggressive advance", "defensive": "Hold ground"},
        "context_text": "HP is 85%",
    }
    res_dict = await adapter._tool_evaluate_choice(args_dict)
    assert res_dict["isError"] is False
    assert res_dict["choice"] in ("offensive", "defensive")
    assert res_dict["confidence"] > 0.0

    # Test with list options
    args_list = {
        "instructions": "Pick direction",
        "options": ["North", "South", "East", "West"],
    }
    res_list = await adapter._tool_evaluate_choice(args_list)
    assert res_list["isError"] is False
    assert res_list["choice"] in ("0", "1", "2", "3")

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_tool_jev_evaluate_score(mock_config: GamingMCPConfig) -> None:
    """Verify jev_evaluate_score tool execution."""
    adapter = TypeSafeJEVAdapter(mock_config)
    await adapter.initialize()

    args = {
        "instructions": "Assess ambush danger",
        "criteria": ["Safe", "Caution", "Imminent Danger"],
        "context_text": "Enemy footsteps heard nearby",
    }
    res = await adapter._tool_evaluate_score(args)
    assert res["isError"] is False
    assert isinstance(res["score"], float)
    assert "legend" in res

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_tool_jev_decide_and_act_threshold_behavior(mock_config: GamingMCPConfig) -> None:
    """Verify decide_and_act respects confidence threshold."""
    adapter = TypeSafeJEVAdapter(mock_config)
    await adapter.initialize()

    actions = {
        "heal": "h",
        "attack": "space",
    }

    # High threshold aborts execution
    args_abort = {
        "instructions": "Choose emergency action",
        "actions": actions,
        "confidence_threshold": 0.999,
        "execute": True,
    }
    res_abort = await adapter._tool_decide_and_act(args_abort)
    assert res_abort["isError"] is False
    assert res_abort["status"] == "aborted_low_confidence"
    assert res_abort["action_executed"] is False

    # Low threshold executes winning action
    args_exec = {
        "instructions": "Choose emergency action",
        "actions": actions,
        "confidence_threshold": 0.1,
        "execute": True,
    }
    res_exec = await adapter._tool_decide_and_act(args_exec)
    assert res_exec["isError"] is False
    assert res_exec["status"] == "executed"
    assert res_exec["action_executed"] is True
    assert res_exec["selected_action"] in actions

    await adapter.shutdown()


# -----------------------------------------------------------------------------
# Resource and Prompt Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_telemetry(mock_config: GamingMCPConfig) -> None:
    """Verify jev://telemetry resource reading."""
    adapter = TypeSafeJEVAdapter(mock_config)
    await adapter.initialize()

    # Trigger one choice evaluation to populate telemetry
    await adapter._tool_evaluate_choice(
        {
            "instructions": "Test query",
            "options": {"a": "Option A"},
        }
    )

    res = await adapter._resource_telemetry()
    assert res["uri"] == "jev://telemetry"
    parsed_json = json.loads(res["contents"][0]["text"])
    assert parsed_json["requests_total"] == 1
    assert parsed_json["mock_mode"] is True

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_prompt_tactical_scaffold(mock_config: GamingMCPConfig) -> None:
    """Verify typesafe_tactical_scaffold prompt generation."""
    from gaming_mcp.core.registries import PromptRegistry

    adapter = TypeSafeJEVAdapter(mock_config)
    res = await adapter._prompt_tactical_scaffold(
        {
            "objective": "Clear dungeon floor 5",
            "game_title": "Elden Ring",
        }
    )
    assert "Elden Ring" in res["description"]
    prompt_content = res["messages"][0]["content"]["text"]
    assert "System 1" in prompt_content
    assert "System 2" in prompt_content

    # Also verify rendering through PromptRegistry
    registry = PromptRegistry()
    adapter.register_prompts(registry)
    rendered = await registry.render(
        "typesafe_tactical_scaffold",
        {"objective": "Clear dungeon floor 5", "game_title": "Elden Ring"},
    )
    assert "Elden Ring" in rendered["description"]
    assert "System 1" in rendered["messages"][0]["content"]["text"]


# -----------------------------------------------------------------------------
# Server Hot-Swapping Integration Test
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_switch_to_typesafe_jev() -> None:
    """Verify switching to typesafe_jev adapter on the server and executing tool."""
    cfg = GamingMCPConfig()
    cfg.adapters.typesafe_jev.mock_mode = True
    server = GamingMCPServer(cfg)
    await server.initialize()

    # Initial adapter is computer_use
    assert server.router.active_adapter_id == "computer_use"
    assert "typesafe_jev" in server.get_health()["adapters_available"]

    # Switch adapter to typesafe_jev
    switch_res = await server.tools.execute(
        "switch_adapter",
        {"adapter_id": "typesafe_jev"},
    )
    assert switch_res["isError"] is False
    assert server.router.active_adapter_id == "typesafe_jev"

    # Check JEV tools are bound
    assert server.tools.get("jev_evaluate_choice") is not None
    assert server.tools.get("jev_evaluate_score") is not None
    assert server.tools.get("jev_decide_and_act") is not None

    # Execute jev_evaluate_choice through server tool dispatcher
    tool_res = await server.tools.execute(
        "jev_evaluate_choice",
        {
            "instructions": "Pick defensive stance",
            "options": {"parry": "Parry enemy attack", "dodge": "Roll backward"},
        },
    )
    assert tool_res["isError"] is False
    tool_data = json.loads(tool_res["content"][0]["text"])
    assert tool_data["choice"] in ("parry", "dodge")
