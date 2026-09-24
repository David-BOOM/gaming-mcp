"""Microsecond action chunk scheduler and high-frequency actuation dispatcher.

Mitigates remote cloud inference latency (500ms - 2500ms) by executing
compound macro action sequences locally with sub-millisecond precision.
Integrates with MCP cancellation tokens to sever motor actuation and release
held physical/virtual keys within 10ms of an abort signal.
"""

import asyncio
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.io.gamepad import BaseGamepadController, get_gamepad_controller
from gaming_mcp.io.input import Win32InputInjector

logger = logging.getLogger("gaming_mcp.io.timing")


class ActionChunkItem(BaseModel):
    """A discrete timed action within an action chunk."""

    offset_ms: int = Field(ge=0, description="Milliseconds from chunk start to execute this action")
    type: str = Field(
        description=(
            "Action type: key_down, key_up, key_press, mouse_move, mouse_down, "
            "mouse_up, mouse_click, gamepad_axis, gamepad_button_down, "
            "gamepad_button_up, sleep"
        )
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters (e.g. key, x, y, dx, dy, button)",
    )


class ActionChunk(BaseModel):
    """A compound high-frequency action chunk sequence."""

    actions: list[ActionChunkItem] = Field(
        ...,
        description="Chronological sequence of actions with relative millisecond offsets",
    )
    total_duration_ms: int = Field(
        ge=10,
        le=15000,
        default=200,
        description="Total duration allocated for chunk execution in milliseconds",
    )


class ActionChunkScheduler:
    """Executes action chunks locally with high-resolution timing and cancellation hooks."""

    def __init__(
        self,
        input_injector: Win32InputInjector | None = None,
        gamepad: BaseGamepadController | None = None,
        cancellation_manager: CancellationManager | None = None,
    ) -> None:
        self.input_injector = input_injector or Win32InputInjector()
        self.gamepad = gamepad or get_gamepad_controller()
        self.cancellation_manager = cancellation_manager

        if self.cancellation_manager is not None:
            self.cancellation_manager.register_callback(self.emergency_reset)

    def emergency_reset(self) -> None:
        """Immediately release all held keys, mouse buttons, and gamepad controls."""
        try:
            self.input_injector.release_all()
        except Exception as exc:
            logger.error("Error releasing keyboard/mouse during emergency reset: %s", exc)

        try:
            self.gamepad.reset()
        except Exception as exc:
            logger.error("Error resetting gamepad during emergency reset: %s", exc)

    async def execute_chunk(
        self,
        chunk: ActionChunk,
        cancellation_token: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """Execute a chunk of timed actions with high-resolution sleep and cancellation checks."""
        sorted_actions = sorted(chunk.actions, key=lambda a: a.offset_ms)
        start_time = time.perf_counter()
        executed_count = 0

        for item in sorted_actions:
            # 1. Check cancellation before sleeping
            if cancellation_token is not None and cancellation_token.is_set():
                self.emergency_reset()
                return {
                    "status": "cancelled",
                    "executed_count": executed_count,
                    "reason": "Cancellation token fired prior to action dispatch",
                    "duration_ms": round((time.perf_counter() - start_time) * 1000.0, 2),
                }

            # 2. Wait until target offset
            target_time = start_time + (item.offset_ms / 1000.0)
            now = time.perf_counter()
            remaining = target_time - now

            if remaining > 0.002:
                # Coarse async sleep to yield event loop
                await asyncio.sleep(remaining - 0.001)

            # Fine-grained spin wait for sub-millisecond precision
            while time.perf_counter() < target_time:
                pass

            # 3. Check cancellation again after wake-up
            if cancellation_token is not None and cancellation_token.is_set():
                self.emergency_reset()
                return {
                    "status": "cancelled",
                    "executed_count": executed_count,
                    "reason": "Cancellation token fired after sleep wait",
                    "duration_ms": round((time.perf_counter() - start_time) * 1000.0, 2),
                }

            # 4. Dispatch action
            try:
                self._dispatch_action(item)
                executed_count += 1
            except Exception as exc:
                logger.error("Action chunk execution failure on %s: %s", item, exc)
                self.emergency_reset()
                return {
                    "status": "failed",
                    "error": str(exc),
                    "executed_count": executed_count,
                    "duration_ms": round((time.perf_counter() - start_time) * 1000.0, 2),
                }

        # 5. Wait for remainder of total_duration_ms
        end_target = start_time + (chunk.total_duration_ms / 1000.0)
        remaining_total = end_target - time.perf_counter()
        if remaining_total > 0.002:
            await asyncio.sleep(remaining_total - 0.001)
        while time.perf_counter() < end_target:
            pass

        return {
            "status": "completed",
            "executed_count": executed_count,
            "duration_ms": round((time.perf_counter() - start_time) * 1000.0, 2),
            "total_duration_ms": chunk.total_duration_ms,
        }

    def _dispatch_action(self, item: ActionChunkItem) -> None:
        """Route an individual action item to the appropriate hardware injector."""
        action_type = item.type.lower()
        params = item.params

        if action_type == "key_down":
            key = str(params["key"])
            self.input_injector.key_down(key)
        elif action_type == "key_up":
            key = str(params["key"])
            self.input_injector.key_up(key)
        elif action_type == "key_press":
            key = str(params["key"])
            duration = float(params.get("duration_ms", 50.0))
            self.input_injector.press_key(key, hold_duration_ms=duration)
        elif action_type == "mouse_move":
            if "dx" in params and "dy" in params:
                self.input_injector.mouse_move_relative(int(params["dx"]), int(params["dy"]))
            elif "x" in params and "y" in params:
                self.input_injector.mouse_move_absolute(int(params["x"]), int(params["y"]))
        elif action_type == "mouse_down":
            btn = str(params.get("button", "left"))
            self.input_injector.mouse_down(btn)
        elif action_type == "mouse_up":
            btn = str(params.get("button", "left"))
            self.input_injector.mouse_up(btn)
        elif action_type == "mouse_click":
            x = int(params["x"]) if "x" in params else None
            y = int(params["y"]) if "y" in params else None
            btn = str(params.get("button", "left"))
            self.input_injector.mouse_click(x=x, y=y, button=btn)
        elif action_type == "gamepad_axis":
            if "left_stick" in params:
                ls = params["left_stick"]
                self.gamepad.set_left_stick(float(ls["x"]), float(ls["y"]))
            if "right_stick" in params:
                rs = params["right_stick"]
                self.gamepad.set_right_stick(float(rs["x"]), float(rs["y"]))
            if "left_trigger" in params:
                self.gamepad.set_left_trigger(float(params["left_trigger"]))
            if "right_trigger" in params:
                self.gamepad.set_right_trigger(float(params["right_trigger"]))
            self.gamepad.update()
        elif action_type == "gamepad_button_down":
            btn_name = str(params["button"])
            self.gamepad.press_button(btn_name)
            self.gamepad.update()
        elif action_type == "gamepad_button_up":
            btn_name = str(params["button"])
            self.gamepad.release_button(btn_name)
            self.gamepad.update()
        elif action_type == "sleep":
            pass
        else:
            logger.warning("Unrecognized action type in chunk: %s", action_type)
