"""Unit tests for MacroExecutor: execution, error interception, self-repair, and telemetry."""

import asyncio
from collections.abc import Generator
from typing import Any

import pytest

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.registries import ToolRegistry
from gaming_mcp.skills.models import (
    MacroStep,
    ParameterDefinition,
    SkillDefinition,
)
from gaming_mcp.skills.repair import MacroExecutor
from gaming_mcp.skills.store import SkillStore


@pytest.fixture
def memory_store() -> Generator[SkillStore, None, None]:
    """Fixture providing an in-memory SkillStore."""
    store = SkillStore(":memory:")
    yield store
    store.close()


@pytest.mark.asyncio
async def test_executor_sequential_success(memory_store: SkillStore) -> None:
    """Verify clean sequential execution of multiple steps without errors."""
    registry = ToolRegistry()
    call_log: list[str] = []

    async def _step1_handler(args: dict[str, Any]) -> str:
        call_log.append(f"step1:{args['target']}")
        return "step1_ok"

    async def _step2_handler(args: dict[str, Any]) -> str:
        call_log.append(f"step2:{args['count']}")
        return "step2_ok"

    registry.register("step1_tool", _step1_handler)
    registry.register("step2_tool", _step2_handler)

    step1 = MacroStep(tool_name="step1_tool", arguments={"target": "{block}"})
    step2 = MacroStep(tool_name="step2_tool", arguments={"count": "{amount}"})

    skill = SkillDefinition(
        name="test_sequence",
        description="Run two steps sequentially",
        parameters={
            "block": ParameterDefinition(type="str"),
            "amount": ParameterDefinition(type="int", default=10),
        },
        steps=[step1, step2],
    )
    memory_store.save_skill(skill)

    executor = MacroExecutor(tool_registry=registry, store=memory_store)
    record = await executor.execute_macro(skill=skill, parameters={"block": "stone"})

    assert record.status == "success"
    assert record.duration_ms > 0.0
    assert len(record.steps) == 2
    assert record.steps[0].status == "success"
    assert record.steps[1].status == "success"
    assert call_log == ["step1:stone", "step2:10"]

    # Verify history recorded in SkillStore
    history = memory_store.get_history(limit=10)
    assert len(history) == 1
    assert history[0].status == "success"


@pytest.mark.asyncio
async def test_executor_compilation_failure(memory_store: SkillStore) -> None:
    """Verify execution aborts gracefully and records failure when parameters are invalid."""
    registry = ToolRegistry()
    skill = SkillDefinition(
        name="needs_param",
        description="Requires parameter without default",
        parameters={"required_id": ParameterDefinition(type="int", required=True)},
        steps=[MacroStep(tool_name="dummy_tool", arguments={"id": "{required_id}"})],
    )
    memory_store.save_skill(skill)

    executor = MacroExecutor(tool_registry=registry, store=memory_store)
    record = await executor.execute_macro(skill=skill, parameters={})

    assert record.status == "failed"
    assert "Macro compilation error" in (record.error or "")
    assert record.diagnosis is not None
    assert len(record.steps) == 0

    # Verify failed count incremented in store
    saved = memory_store.get_skill("needs_param")
    assert saved is not None
    assert saved.failure_count == 1


@pytest.mark.asyncio
async def test_executor_self_repair_retry_success(memory_store: SkillStore) -> None:
    """Verify self-repair loop catches step failure and repairs via retry."""
    registry = ToolRegistry()
    attempts = 0

    async def _flaky_handler() -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"isError": True, "content": [{"type": "text", "text": "Transient lock error"}]}
        return {"isError": False, "content": [{"type": "text", "text": "Success on retry"}]}

    registry.register("flaky_tool", _flaky_handler)

    step = MacroStep(
        tool_name="flaky_tool",
        arguments={},
        max_retries=2,
        retry_delay_s=0.01,
        on_error="retry",
    )
    skill = SkillDefinition(
        name="flaky_macro",
        description="Fails once then succeeds",
        steps=[step],
    )
    memory_store.save_skill(skill)

    events: list[dict[str, Any]] = []

    async def _event_listener(event: dict[str, Any]) -> None:
        events.append(event)

    executor = MacroExecutor(
        tool_registry=registry,
        store=memory_store,
        on_repair_event=_event_listener,
    )
    record = await executor.execute_macro(skill=skill, auto_repair=True)

    assert record.status == "repaired"
    assert len(record.steps) == 1
    assert record.steps[0].status == "repaired"
    assert record.steps[0].retry_attempts == 1
    assert attempts == 2

    # Check event emission
    event_names = [e.get("event") for e in events]
    assert "step_failed" in event_names
    assert "step_repaired_retry" in event_names


@pytest.mark.asyncio
async def test_executor_self_repair_compensation_success(memory_store: SkillStore) -> None:
    """Verify self-repair triggers compensation steps when main step fails."""
    registry = ToolRegistry()
    compensation_called = False

    async def _failing_handler() -> dict[str, Any]:
        return {"isError": True, "content": [{"type": "text", "text": "Primary tool broke"}]}

    async def _compensation_handler() -> str:
        nonlocal compensation_called
        compensation_called = True
        return "compensation_ok"

    registry.register("broken_tool", _failing_handler)
    registry.register("cleanup_tool", _compensation_handler)

    comp_step = MacroStep(tool_name="cleanup_tool", arguments={})
    main_step = MacroStep(
        tool_name="broken_tool",
        arguments={},
        max_retries=0,
        compensation_steps=[comp_step],
        on_error="compensate",
    )

    skill = SkillDefinition(
        name="compensation_macro",
        description="Test fallback compensation",
        steps=[main_step],
    )
    memory_store.save_skill(skill)

    executor = MacroExecutor(tool_registry=registry, store=memory_store)
    record = await executor.execute_macro(skill=skill, auto_repair=True)

    assert record.status == "repaired"
    assert compensation_called is True
    assert record.steps[0].status == "repaired"
    assert record.steps[0].compensated is True


@pytest.mark.asyncio
async def test_executor_unrecoverable_failure_and_diagnosis(memory_store: SkillStore) -> None:
    """Verify unrecoverable step failure aborts macro and generates diagnosis."""
    registry = ToolRegistry()
    second_step_called = False

    async def _broken_handler() -> dict[str, Any]:
        return {
            "isError": True,
            "error_code": -32602,
            "content": [{"type": "text", "text": "Invalid schema for broken_tool"}],
        }

    async def _never_called_handler() -> str:
        nonlocal second_step_called
        second_step_called = True
        return "unreachable"

    registry.register("step1_broken", _broken_handler)
    registry.register("step2_unreachable", _never_called_handler)

    step1 = MacroStep(tool_name="step1_broken", arguments={}, max_retries=1, retry_delay_s=0.01)
    step2 = MacroStep(tool_name="step2_unreachable", arguments={})

    skill = SkillDefinition(
        name="abort_macro",
        description="Fails and aborts",
        steps=[step1, step2],
    )
    memory_store.save_skill(skill)

    executor = MacroExecutor(tool_registry=registry, store=memory_store)
    record = await executor.execute_macro(skill=skill, auto_repair=True)

    assert record.status == "failed"
    assert second_step_called is False
    assert len(record.steps) == 2
    assert record.steps[0].status == "failed"
    assert record.steps[1].status == "skipped"

    assert record.diagnosis is not None
    assert "Error Code: -32602" in record.diagnosis
    assert "Probable Cause" in record.diagnosis
    assert "Recommended Self-Repair Action" in record.diagnosis


@pytest.mark.asyncio
async def test_executor_on_error_ignore(memory_store: SkillStore) -> None:
    """Verify steps configured with on_error='ignore' do not abort the macro."""
    registry = ToolRegistry()
    step2_executed = False

    async def _failing_handler() -> dict[str, Any]:
        return {"isError": True, "content": [{"type": "text", "text": "Ignorable failure"}]}

    async def _step2_handler() -> str:
        nonlocal step2_executed
        step2_executed = True
        return "step2_done"

    registry.register("failing_tool", _failing_handler)
    registry.register("step2_tool", _step2_handler)

    step1 = MacroStep(tool_name="failing_tool", arguments={}, on_error="ignore")
    step2 = MacroStep(tool_name="step2_tool", arguments={})

    skill = SkillDefinition(
        name="ignore_error_skill",
        description="Ignore step 1",
        steps=[step1, step2],
    )
    memory_store.save_skill(skill)

    executor = MacroExecutor(tool_registry=registry, store=memory_store)
    record = await executor.execute_macro(skill=skill)

    assert record.status == "success"
    assert step2_executed is True
    assert record.steps[0].status == "skipped"
    assert record.steps[1].status == "success"


@pytest.mark.asyncio
async def test_executor_cancellation(memory_store: SkillStore) -> None:
    """Verify execution halts immediately when cancellation is requested."""
    registry = ToolRegistry()
    canceller = CancellationManager()

    step2_ran = False

    async def _slow_handler() -> str:
        # Simulate cancellation during step execution
        await canceller.cancel_request("req_cancel", reason="Aborted by user")
        return "step1_done"

    async def _step2_handler() -> str:
        nonlocal step2_ran
        step2_ran = True
        return "step2_done"

    registry.register("slow_tool", _slow_handler)
    registry.register("step2_tool", _step2_handler)

    step1 = MacroStep(tool_name="slow_tool", arguments={})
    step2 = MacroStep(tool_name="step2_tool", arguments={})

    skill = SkillDefinition(name="cancel_skill", description="Cancels midway", steps=[step1, step2])
    memory_store.save_skill(skill)

    executor = MacroExecutor(tool_registry=registry, store=memory_store)

    macro_task = asyncio.create_task(
        executor.execute_macro(
            skill=skill,
            cancellation_manager=canceller,
            request_id="req_cancel",
        )
    )
    canceller.register_task("req_cancel", macro_task)

    with pytest.raises(asyncio.CancelledError):
        await macro_task

    assert step2_ran is False

    history = memory_store.get_history(limit=5)
    assert len(history) == 1
    assert history[0].status == "failed"
