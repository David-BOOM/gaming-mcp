"""Macro execution engine with autonomous failure interception and self-repair loops."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.registries import ToolRegistry
from gaming_mcp.skills.compiler import MacroCompiler
from gaming_mcp.skills.models import (
    ExecutionRecord,
    MacroStep,
    SkillDefinition,
    StepExecutionResult,
)
from gaming_mcp.skills.store import SkillStore

logger = logging.getLogger("gaming_mcp.skills.repair")


class MacroExecutor:
    """Sequential macro executor featuring error interception and self-repair strategies."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        store: SkillStore | None = None,
        compiler: MacroCompiler | None = None,
        on_repair_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the macro executor.

        Args:
            tool_registry: Target ToolRegistry to execute compiled atomic steps against.
            store: Optional SkillStore to record execution traces and update statistics.
            compiler: Optional MacroCompiler instance for parameter interpolation.
            on_repair_event: Optional callback for diagnostic telemetry and repair events.
        """
        self._registry = tool_registry
        self._store = store
        self._compiler = compiler or MacroCompiler()
        self._on_repair_event = on_repair_event

    @property
    def tool_registry(self) -> ToolRegistry:
        """Return the target tool registry."""
        return self._registry

    @property
    def store(self) -> SkillStore | None:
        """Return the backing skill store if configured."""
        return self._store

    async def _emit_event(self, event_data: dict[str, Any]) -> None:
        """Emit a self-repair event to callback and logger."""
        logger.debug("Self-repair event: %s", event_data)
        if self._on_repair_event is not None:
            try:
                await self._on_repair_event(event_data)
            except Exception as exc:
                logger.warning("Error in self-repair event callback: %s", exc)

    def diagnose_failure(
        self,
        step: MacroStep,
        step_index: int,
        error_code: int,
        error_message: str,
        retry_attempts: int,
    ) -> str:
        """Generate a structured diagnostic assessment for an unrecoverable step failure."""
        causes: list[str] = []
        recommendations: list[str] = []

        if error_code == -32601:
            causes.append(f"Tool '{step.tool_name}' is not registered in the active ToolRegistry.")
            recommendations.append("Ensure the corresponding game adapter is activated.")
        elif error_code == -32602:
            causes.append(
                f"Arguments for tool '{step.tool_name}' failed validation against its input schema."
            )
            recommendations.append(
                "Review the macro parameter templates and input argument definitions."
            )
        elif error_code == -32002:
            causes.append(
                f"Tool '{step.tool_name}' failed due to missing adapter hardware or driver support."
            )
            recommendations.append("Verify host drivers or check adapter capability requirements.")
        else:
            causes.append(f"Tool execution encountered runtime error: {error_message}")
            recommendations.append("Inspect game state preconditions or inject compensation steps.")

        diagnosis = (
            f"Step {step_index} ('{step.tool_name}') failed "
            f"after {retry_attempts} retry attempt(s).\n"
            f"Error Code: {error_code}\n"
            f"Error Message: {error_message}\n"
            f"Probable Cause: {' '.join(causes)}\n"
            f"Recommended Self-Repair Action: {' '.join(recommendations)}"
        )
        return diagnosis

    def _is_cancelled(
        self,
        cancellation_manager: CancellationManager | None,
        request_id: str | None,
    ) -> bool:
        """Check if execution task has been marked cancelled."""
        current_task = asyncio.current_task()
        if current_task is not None:
            if hasattr(current_task, "cancelling") and current_task.cancelling():
                return True
            if current_task.cancelled():
                return True
        return False

    async def _execute_single_step(
        self,
        step: MacroStep,
        cancellation_manager: CancellationManager | None,
        request_id: str | None,
    ) -> tuple[dict[str, Any], float]:
        """Execute a single step against the tool registry and measure latency."""
        t0 = time.perf_counter()
        result = await self._registry.execute(
            name=step.tool_name,
            arguments=step.arguments,
            cancellation_manager=cancellation_manager,
            request_id=request_id,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return result, latency_ms

    async def execute_macro(
        self,
        skill: SkillDefinition,
        parameters: dict[str, Any] | None = None,
        auto_repair: bool = True,
        cancellation_manager: CancellationManager | None = None,
        request_id: str | None = None,
    ) -> ExecutionRecord:
        """Execute a composite skill sequentially with failure interception and self-repair.

        Args:
            skill: The SkillDefinition to execute.
            parameters: Runtime parameters to bind to macro step templates.
            auto_repair: Whether to activate autonomous retries and compensation strategies.
            cancellation_manager: Optional cancellation manager to halt execution on client request.
            request_id: Optional request identifier for tracking cancellation tokens.

        Returns:
            ExecutionRecord containing status, duration, step results, and diagnosis.
        """
        start_iso = datetime.now(UTC).isoformat()
        start_time = time.perf_counter()
        raw_params = parameters or {}

        # 1. Compile skill steps
        try:
            compiled_steps = self._compiler.compile_skill(
                skill=skill,
                parameters=raw_params,
                tool_registry=self._registry,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            now_iso = datetime.now(UTC).isoformat()
            record = ExecutionRecord(
                skill_name=skill.name,
                status="failed",
                duration_ms=duration_ms,
                start_time=start_iso,
                end_time=now_iso,
                parameters=raw_params,
                steps=[],
                error=f"Macro compilation error: {exc}",
                diagnosis="Compilation failed during parameter resolution or schema validation.",
            )
            if self._store:
                try:
                    self._store.record_execution(record)
                except Exception as store_exc:
                    logger.warning("Failed to record compilation failure: %s", store_exc)
            return record

        step_results: list[StepExecutionResult] = []
        overall_status: str = "success"
        overall_error: str | None = None
        diagnosis: str | None = None
        has_repaired = False

        try:
            # 2. Sequential execution loop
            for idx, step in enumerate(compiled_steps):
                # Check for cancellation between steps
                if self._is_cancelled(cancellation_manager, request_id):
                    overall_status = "failed"
                    overall_error = "Macro execution cancelled by client request."
                    diagnosis = "Execution stopped midway due to cancellation notification."
                    for remaining_idx in range(idx, len(compiled_steps)):
                        step_results.append(
                            StepExecutionResult(
                                step_index=remaining_idx,
                                tool_name=compiled_steps[remaining_idx].tool_name,
                                status="skipped",
                            )
                        )
                    break

                result, latency_ms = await self._execute_single_step(
                    step, cancellation_manager, request_id
                )
                is_error = result.get("isError", False)

                if not is_error:
                    # Step succeeded
                    step_results.append(
                        StepExecutionResult(
                            step_index=idx,
                            tool_name=step.tool_name,
                            status="success",
                            latency_ms=latency_ms,
                            output=result,
                            retry_attempts=0,
                            compensated=False,
                        )
                    )
                    continue

                # Step failed - intercept failure
                err_code = result.get("error_code", -32000)
                err_msg = ""
                for item in result.get("content", []):
                    if isinstance(item, dict) and item.get("type") == "text":
                        err_msg = item.get("text", "")
                        break

                await self._emit_event(
                    {
                        "event": "step_failed",
                        "step_index": idx,
                        "tool": step.tool_name,
                        "error_code": err_code,
                        "error_message": err_msg,
                    }
                )

                if step.on_error == "ignore":
                    # Step error ignored per configuration
                    step_results.append(
                        StepExecutionResult(
                            step_index=idx,
                            tool_name=step.tool_name,
                            status="skipped",
                            latency_ms=latency_ms,
                            error=err_msg,
                        )
                    )
                    continue

                # Check self-repair strategies
                step_repaired = False
                retries_attempted = 0

                max_retries = step.max_retries
                if auto_repair and max_retries == 0 and step.on_error in ("retry", "compensate"):
                    max_retries = 1

                # Strategy A: Retry with delay
                for attempt in range(1, max_retries + 1):
                    retries_attempted = attempt
                    if step.retry_delay_s > 0:
                        await asyncio.sleep(step.retry_delay_s)

                    if self._is_cancelled(cancellation_manager, request_id):
                        break

                    retry_result, retry_latency = await self._execute_single_step(
                        step, cancellation_manager, request_id
                    )
                    latency_ms += retry_latency

                    if not retry_result.get("isError", False):
                        step_repaired = True
                        has_repaired = True
                        step_results.append(
                            StepExecutionResult(
                                step_index=idx,
                                tool_name=step.tool_name,
                                status="repaired",
                                latency_ms=latency_ms,
                                output=retry_result,
                                retry_attempts=retries_attempted,
                                compensated=False,
                            )
                        )
                        await self._emit_event(
                            {
                                "event": "step_repaired_retry",
                                "step_index": idx,
                                "tool": step.tool_name,
                                "attempt": attempt,
                            }
                        )
                        break

                if step_repaired:
                    continue

                # Strategy B: Compensation steps
                if auto_repair and step.compensation_steps:
                    await self._emit_event(
                        {
                            "event": "executing_compensation",
                            "step_index": idx,
                            "tool": step.tool_name,
                            "compensation_count": len(step.compensation_steps),
                        }
                    )
                    comp_all_success = True
                    for comp_step in step.compensation_steps:
                        c_res, c_lat = await self._execute_single_step(
                            comp_step, cancellation_manager, request_id
                        )
                        latency_ms += c_lat
                        if c_res.get("isError", False):
                            comp_all_success = False
                            break

                    if comp_all_success:
                        step_repaired = True
                        has_repaired = True
                        step_results.append(
                            StepExecutionResult(
                                step_index=idx,
                                tool_name=step.tool_name,
                                status="repaired",
                                latency_ms=latency_ms,
                                output="Repaired via compensation steps",
                                retry_attempts=retries_attempted,
                                compensated=True,
                            )
                        )
                        await self._emit_event(
                            {
                                "event": "step_repaired_compensation",
                                "step_index": idx,
                                "tool": step.tool_name,
                            }
                        )
                        continue

                # If all repair strategies exhausted, mark failed and abort macro
                step_results.append(
                    StepExecutionResult(
                        step_index=idx,
                        tool_name=step.tool_name,
                        status="failed",
                        latency_ms=latency_ms,
                        error=err_msg,
                        retry_attempts=retries_attempted,
                        compensated=False,
                    )
                )
                overall_status = "failed"
                overall_error = f"Step {idx} ('{step.tool_name}') failed: {err_msg}"
                diagnosis = self.diagnose_failure(
                    step=step,
                    step_index=idx,
                    error_code=err_code,
                    error_message=err_msg,
                    retry_attempts=retries_attempted,
                )

                # Skip remaining steps
                for remaining_idx in range(idx + 1, len(compiled_steps)):
                    step_results.append(
                        StepExecutionResult(
                            step_index=remaining_idx,
                            tool_name=compiled_steps[remaining_idx].tool_name,
                            status="skipped",
                        )
                    )
                break
        except asyncio.CancelledError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            end_iso = datetime.now(UTC).isoformat()
            cancel_record = ExecutionRecord(
                skill_name=skill.name,
                status="failed",
                duration_ms=duration_ms,
                start_time=start_iso,
                end_time=end_iso,
                parameters=raw_params,
                steps=step_results,
                error="Macro execution cancelled by client request.",
                diagnosis="Execution stopped midway due to cancellation notification.",
            )
            if self._store:
                try:
                    self._store.record_execution(cancel_record)
                except Exception as store_exc:
                    logger.warning("Failed to record cancellation trace: %s", store_exc)
            raise

        if overall_status != "failed" and has_repaired:
            overall_status = "repaired"

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        end_iso = datetime.now(UTC).isoformat()

        record = ExecutionRecord(
            skill_name=skill.name,
            status=overall_status,  # type: ignore[arg-type]
            duration_ms=duration_ms,
            start_time=start_iso,
            end_time=end_iso,
            parameters=raw_params,
            steps=step_results,
            error=overall_error,
            diagnosis=diagnosis,
        )

        if self._store:
            try:
                self._store.record_execution(record)
            except Exception as store_exc:
                logger.warning("Failed to record execution trace: %s", store_exc)

        return record
