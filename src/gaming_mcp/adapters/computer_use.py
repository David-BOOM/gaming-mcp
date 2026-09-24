"""Universal VLA Computer Use Adapter for video games.

Provides complete compatibility with Anthropic Claude Computer Use and standard
Vision-Language Models (GPT-4o, Gemini 2.0, Grok Vision) through DXGI zero-copy
screen capture, Win32 hardware scan codes, ViGEmBus virtual gamepad, WASAPI audio,
action chunking, and multi-layered safety guardrails.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.core.exceptions import (
    AdapterError,
)
from gaming_mcp.io.audio import WASAPIAudioCapturer
from gaming_mcp.io.gamepad import BaseGamepadController, get_gamepad_controller
from gaming_mcp.io.input import Win32InputInjector
from gaming_mcp.io.process import Win32WindowManager
from gaming_mcp.io.screen import CompositeScreenCapturer
from gaming_mcp.io.security import (
    EmergencyKillSwitch,
    ProcessBlacklistGuard,
    WindowBoundaryGuard,
)
from gaming_mcp.io.timing import ActionChunk, ActionChunkItem, ActionChunkScheduler
from gaming_mcp.io.vision import PerceptualGater
from gaming_mcp.utils.image import draw_set_of_marks_grid, encode_image, image_to_base64

if TYPE_CHECKING:
    from gaming_mcp.config import GamingMCPConfig
    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry

logger = logging.getLogger("gaming_mcp.adapters.computer_use")


class CropRegion(BaseModel):
    """Bounding box rectangle to crop within the captured display."""

    x: int = Field(..., ge=0, description="Left coordinate in pixels")
    y: int = Field(..., ge=0, description="Top coordinate in pixels")
    width: int = Field(..., ge=1, description="Width in pixels")
    height: int = Field(..., ge=1, description="Height in pixels")


class ScreenshotInput(BaseModel):
    """Input parameters for the screenshot tool."""

    annotate_grid: bool = Field(
        default=False,
        description="Overlay coordinate grid with alphanumeric markers for spatial grounding.",
    )
    region: CropRegion | None = Field(
        default=None,
        description="Bounding box rectangle to crop. If null, captures entire focused display.",
    )
    target_window: str | None = Field(
        default=None,
        description=(
            "Substring title of specific game window to capture. Auto-crops to window rect."
        ),
    )
    format: Literal["png", "jpeg"] = Field(
        default="jpeg",
        description="Image compression format. JPEG reduces network transport payload by ~85%.",
    )
    quality: int = Field(
        default=85,
        ge=1,
        le=100,
        description="Compression quality when format is jpeg.",
    )
    skip_if_static: bool = Field(
        default=False,
        description=(
            "If true, utilizes dHash comparison and returns text confirmation if the "
            "scene has changed less than 2.5%, saving token bandwidth."
        ),
    )


class MouseClickInput(BaseModel):
    """Input parameters for the mouse_click tool."""

    x: int = Field(..., description="Absolute X pixel coordinate")
    y: int = Field(..., description="Absolute Y pixel coordinate")
    button: Literal["left", "right", "middle"] = Field(
        default="left",
        description="Mouse button to click",
    )
    modifiers: list[Literal["ctrl", "shift", "alt", "win"]] | None = Field(
        default=None,
        description="Optional keyboard keys held during click (e.g. Shift+Click).",
    )


class MouseDragInput(BaseModel):
    """Input parameters for the mouse_drag tool."""

    start_x: int = Field(..., description="Starting X coordinate")
    start_y: int = Field(..., description="Starting Y coordinate")
    end_x: int = Field(..., description="Ending X coordinate")
    end_y: int = Field(..., description="Ending Y coordinate")
    button: Literal["left", "right", "middle"] = Field(
        default="left",
        description="Mouse button to drag with",
    )
    duration_ms: int = Field(
        default=300,
        ge=50,
        le=5000,
        description="Interpolation duration in milliseconds.",
    )
    steps: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Number of intermediate mouse move events emitted along the Bezier curve.",
    )


class SendKeysInput(BaseModel):
    """Input parameters for the send_keys tool."""

    keys: list[str] = Field(
        ...,
        description="List of key identifiers (e.g. ['w'], ['space'], ['ctrl', 'c'], ['escape']).",
    )
    hold_duration_ms: int = Field(
        default=100,
        ge=10,
        le=15000,
        description="Duration the key is depressed in milliseconds.",
    )
    repeat_count: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Number of times to repeat the keystroke sequence.",
    )


class ExecuteActionChunkInput(BaseModel):
    """Input parameters for the execute_action_chunk tool."""

    actions: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Compound list of timed actions (key_down, key_up, mouse_move, "
            "mouse_down, mouse_up, gamepad_axis)."
        ),
    )
    total_duration_ms: int = Field(
        ...,
        ge=50,
        le=10000,
        description="Total duration window in milliseconds for the scheduled chunk.",
    )


class StickCoordinates(BaseModel):
    """Analog stick deflection coordinates."""

    x: float = Field(..., ge=-1.0, le=1.0, description="Horizontal axis (-1.0 Left, 1.0 Right)")
    y: float = Field(..., ge=-1.0, le=1.0, description="Vertical axis (-1.0 Down, 1.0 Up)")


class GamepadControlInput(BaseModel):
    """Input parameters for the gamepad_control tool."""

    left_stick: StickCoordinates | None = Field(
        default=None,
        description="Left analog stick deflection (-1.0 to 1.0)",
    )
    right_stick: StickCoordinates | None = Field(
        default=None,
        description="Right analog stick deflection (-1.0 to 1.0)",
    )
    left_trigger: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Left analog trigger pressure (0.0 to 1.0)",
    )
    right_trigger: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Right analog trigger pressure (0.0 to 1.0)",
    )
    buttons_pressed: list[str] | None = Field(
        default=None,
        description="List of gamepad buttons to depress (e.g. ['A', 'X', 'LEFT_SHOULDER'])",
    )
    duration_ms: int = Field(
        default=200,
        ge=20,
        le=10000,
        description="Duration in ms to hold gamepad state before releasing to neutral.",
    )


class WindowFocusInput(BaseModel):
    """Input parameters for the window_focus tool."""

    title_pattern: str = Field(
        ...,
        description="Regex pattern matching the window title.",
    )
    bring_to_front: bool = Field(
        default=True,
        description=(
            "Whether to bring the matched window to the top of the z-order and set "
            "foreground focus."
        ),
    )


class ComputerUseAdapter(GameAdapter):
    """Universal VLA Computer Use Adapter for video games.

    Provides OS-level screen capture, hardware scan code input injection,
    virtual gamepad emulation, audio capture, and window management.
    """

    def __init__(
        self,
        config: GamingMCPConfig,
        screen_capturer: CompositeScreenCapturer | Any | None = None,
        input_injector: Win32InputInjector | None = None,
        gamepad_controller: BaseGamepadController | None = None,
        audio_capturer: WASAPIAudioCapturer | None = None,
        window_manager: Win32WindowManager | None = None,
        action_scheduler: ActionChunkScheduler | None = None,
    ) -> None:
        super().__init__(config)
        self._custom_capturer = screen_capturer
        self._custom_injector = input_injector
        self._custom_gamepad = gamepad_controller
        self._custom_audio = audio_capturer
        self._custom_window_mgr = window_manager
        self._custom_scheduler = action_scheduler

        self.screen_capturer: CompositeScreenCapturer | Any | None = None
        self.input_injector: Win32InputInjector | None = None
        self.gamepad: BaseGamepadController | None = None
        self.audio_capturer: WASAPIAudioCapturer | None = None
        self.window_manager: Win32WindowManager | None = None
        self.action_scheduler: ActionChunkScheduler | None = None

        self.boundary_guard: WindowBoundaryGuard | None = None
        self.blacklist_guard: ProcessBlacklistGuard | None = None
        self.kill_switch: EmergencyKillSwitch | None = None
        self.perceptual_gater: PerceptualGater | None = None

        self.bound_window_rect: tuple[int, int, int, int] | None = None

    @property
    def metadata(self) -> AdapterMetadata:
        """Return adapter capability and requirement metadata."""
        return AdapterMetadata(
            id="computer_use",
            display_name="Universal VLA Computer Use",
            version="0.1.0",
            description=(
                "Universal OS-level computer use adapter for video games via DXGI zero-copy "
                "screen capture, Win32 hardware scan codes, and ViGEmBus virtual gamepad."
            ),
            supported_platforms=["win32", "linux", "darwin"],
            requires_display=True,
            requires_admin_privileges=False,
        )

    async def initialize(self) -> None:
        """Initialize all capture, actuation, audio, and safety subsystems."""
        if self.is_initialized:
            return

        # 1. Screen Capturer
        if self._custom_capturer:
            self.screen_capturer = self._custom_capturer
        else:
            prefer_dxgi = self.config.screen.preferred_backend in ("auto", "dxgi")
            self.screen_capturer = CompositeScreenCapturer(
                prefer_dxgi=prefer_dxgi,
                monitor_index=self.config.screen.monitor_index,
                dhash_threshold=self.config.screen.dhash_threshold,
            )

        # 2. Input Injector
        if self._custom_injector:
            self.input_injector = self._custom_injector
        else:
            self.input_injector = Win32InputInjector()

        # 3. Gamepad Controller
        if self._custom_gamepad:
            self.gamepad = self._custom_gamepad
        else:
            self.gamepad = get_gamepad_controller(prefer_mock=self.config.input.prefer_mock_gamepad)

        # 4. Audio Capturer
        if self._custom_audio:
            self.audio_capturer = self._custom_audio
        elif self.config.audio.enabled:
            self.audio_capturer = WASAPIAudioCapturer(
                sample_rate=self.config.audio.sample_rate,
                buffer_duration_sec=self.config.audio.buffer_duration_sec,
            )
            try:
                self.audio_capturer.start()
            except Exception as exc:
                logger.warning("Could not start WASAPI audio capture: %s", exc)

        # 5. Window Manager
        if self._custom_window_mgr:
            self.window_manager = self._custom_window_mgr
        else:
            self.window_manager = Win32WindowManager()

        # 6. Action Chunk Scheduler
        if self._custom_scheduler:
            self.action_scheduler = self._custom_scheduler
        else:
            self.action_scheduler = ActionChunkScheduler(
                input_injector=self.input_injector,
                gamepad=self.gamepad,
            )

        # 7. Safety Guards
        self.boundary_guard = WindowBoundaryGuard()
        additional_bl = (
            set(self.config.security.blacklisted_processes)
            if self.config.security.blacklisted_processes
            else None
        )
        self.blacklist_guard = ProcessBlacklistGuard(additional_blacklist=additional_bl)

        if self.config.security.enable_kill_switch:
            self.kill_switch = EmergencyKillSwitch()
            self.kill_switch.add_callback(self._on_kill_switch)
            self.kill_switch.start()

        # 8. Perceptual Gater
        self.perceptual_gater = PerceptualGater(threshold=self.config.screen.dhash_threshold)

        self.is_initialized = True
        logger.info("ComputerUseAdapter initialized successfully")

    async def shutdown(self) -> None:
        """Gracefully release hardware inputs, stop audio, and release captures."""
        if not self.is_initialized:
            return

        # Stop emergency kill switch
        if self.kill_switch:
            self.kill_switch.stop()
            self.kill_switch = None

        # Reset motor inputs
        if self.input_injector:
            self.input_injector.release_all()

        if self.gamepad:
            self.gamepad.reset()

        # Stop audio capture
        if self.audio_capturer:
            try:
                self.audio_capturer.stop()
            except Exception as exc:
                logger.warning("Error stopping audio capturer: %s", exc)

        # Close screen capturer
        if self.screen_capturer:
            self.screen_capturer.close()

        self.bound_window_rect = None
        self.is_initialized = False
        logger.info("ComputerUseAdapter shut down cleanly")

    def _on_kill_switch(self) -> None:
        """Emergency kill-switch trigger callback."""
        logger.critical("Emergency hardware kill-switch triggered! Resetting all motor outputs.")
        if self.input_injector:
            self.input_injector.release_all()
        if self.gamepad:
            self.gamepad.reset()

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register all universal computer use tools."""
        registry.register(
            name="screenshot",
            handler=self._tool_screenshot,
            description=(
                "Capture visual display of active game window or desktop. Supports dynamic dHash "
                "delta gating, downscaling, and Set-of-Marks visual grid annotations."
            ),
            input_model=ScreenshotInput,
        )
        registry.register(
            name="mouse_click",
            handler=self._tool_mouse_click,
            description="Move mouse cursor to screen coordinates and execute click.",
            input_model=MouseClickInput,
        )
        registry.register(
            name="mouse_drag",
            handler=self._tool_mouse_drag,
            description=(
                "Execute smooth mouse drag interpolation between two screen coordinates for "
                "inventory item dragging or camera rotation."
            ),
            input_model=MouseDragInput,
        )
        registry.register(
            name="send_keys",
            handler=self._tool_send_keys,
            description=(
                "Inject discrete keyboard strokes or hold down movement/action keys for continuous "
                "durations with hardware scan codes."
            ),
            input_model=SendKeysInput,
        )
        registry.register(
            name="execute_action_chunk",
            handler=self._tool_execute_action_chunk,
            description=(
                "Execute a high-frequency timed sequence of keyboard, mouse, and gamepad actions "
                "locally to overcome cloud inference latency."
            ),
            input_model=ExecuteActionChunkInput,
        )
        registry.register(
            name="gamepad_control",
            handler=self._tool_gamepad_control,
            description=(
                "Directly manipulate a virtual Xbox 360 controller via ViGEmBus. Provides analog "
                "stick precision and trigger controls for modern 3D games."
            ),
            input_model=GamepadControlInput,
        )
        registry.register(
            name="window_focus",
            handler=self._tool_window_focus,
            description=(
                "Locate game window by title regex, bring to foreground, and lock cursor capture."
            ),
            input_model=WindowFocusInput,
        )

    def register_resources(self, registry: ResourceRegistry) -> None:
        """Register live reactive resources for audio events and display telemetry."""
        registry.register(
            uri="game://audio/events",
            reader=self._resource_audio_events,
            name="Game Audio Tactical Events",
            description=(
                "Stream of tactical acoustic cues (loudness spikes, gunfire, footsteps) detected "
                "via WASAPI loopback"
            ),
            mime_type="application/json",
        )
        registry.register(
            uri="game://screen/info",
            reader=self._resource_screen_info,
            name="Display & Window Info",
            description="Real-time display resolution and foreground window status",
            mime_type="application/json",
        )

    def register_prompts(self, registry: PromptRegistry) -> None:
        """Register strategic game-playing scaffolding prompts."""
        registry.register(
            name="gameplay_strategy",
            generator=self._prompt_gameplay_strategy,
            description="Scaffolding prompt for autonomous game strategy and visual grounding",
            arguments=[
                {
                    "name": "game_title",
                    "description": "Name of the game being played",
                    "required": False,
                },
                {
                    "name": "objective",
                    "description": "Current high-level objective",
                    "required": False,
                },
            ],
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify subsystem health and driver availability."""
        return {
            "adapter_id": self.metadata.id,
            "status": "healthy" if self.is_initialized else "uninitialized",
            "screen_capturer_backend": (
                self.screen_capturer.active_backend if self.screen_capturer else None
            ),
            "audio_recording": (self.audio_capturer.is_recording if self.audio_capturer else False),
            "gamepad_type": type(self.gamepad).__name__ if self.gamepad else None,
            "kill_switch_armed": self.kill_switch.is_running if self.kill_switch else False,
            "bound_window": self.bound_window_rect,
        }

    # -------------------------------------------------------------------------
    # Tool Handlers
    # -------------------------------------------------------------------------

    async def _tool_screenshot(
        self,
        annotate_grid: bool = False,
        region: CropRegion | dict[str, int] | None = None,
        target_window: str | None = None,
        format: str = "jpeg",  # noqa: A002
        quality: int = 85,
        skip_if_static: bool = False,
    ) -> dict[str, Any]:
        if not self.screen_capturer:
            raise AdapterError("Screen capturer is not initialized")

        capture_region: tuple[int, int, int, int] | None = None

        if target_window and self.window_manager:
            win = self.window_manager.find_window(target_window)
            if win:
                if self.blacklist_guard:
                    self.blacklist_guard.assert_not_blacklisted(win.process_name, hwnd=win.hwnd)
                capture_region = (win.left, win.top, win.width, win.height)

        if region is not None and capture_region is None:
            if isinstance(region, dict):
                capture_region = (
                    region["x"],
                    region["y"],
                    region["width"],
                    region["height"],
                )
            else:
                capture_region = (region.x, region.y, region.width, region.height)

        if hasattr(self.screen_capturer, "capture_frame"):
            frame = self.screen_capturer.capture_frame(region=capture_region)
        else:
            frame = self.screen_capturer.capture(region=capture_region)

        # Evaluate dHash perceptual delta gating
        if skip_if_static and self.perceptual_gater:
            is_static, _cur_hash, dist = self.perceptual_gater.evaluate(frame)
            if is_static:
                return {
                    "isError": False,
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Visual frame unchanged (dHash Hamming distance "
                                f"{dist} <= threshold)."
                            ),
                        }
                    ],
                }

        # Convert numpy array to PIL Image
        if isinstance(frame, np.ndarray):
            if frame.ndim == 2:
                pil_img = Image.fromarray(frame, mode="L")
            elif frame.shape[2] == 4:
                pil_img = Image.fromarray(frame, mode="RGBA")
            else:
                pil_img = Image.fromarray(frame, mode="RGB")
        else:
            pil_img = frame

        # Apply Set-of-Marks (SoM) alphanumeric coordinate grid overlay
        if annotate_grid:
            pil_img = draw_set_of_marks_grid(pil_img)

        img_format: Literal["jpeg", "png"] = "png" if format.lower() == "png" else "jpeg"
        encoded_bytes = encode_image(pil_img, image_format=img_format, quality=quality)
        b64_data = image_to_base64(encoded_bytes)

        return {
            "isError": False,
            "content": [
                {
                    "type": "image",
                    "data": b64_data,
                    "mimeType": f"image/{img_format}",
                }
            ],
        }

    async def _tool_mouse_click(
        self,
        x: int,
        y: int,
        button: Literal["left", "right", "middle"] = "left",
        modifiers: list[Literal["ctrl", "shift", "alt", "win"]] | None = None,
    ) -> dict[str, Any]:
        if not self.input_injector:
            raise AdapterError("Input injector is not initialized")

        cx, cy = self._validate_boundary(x, y)
        mods: list[str] | None = list(modifiers) if modifiers else None
        self.input_injector.mouse_click(x=cx, y=cy, button=button, modifiers=mods)

        return {
            "isError": False,
            "content": [{"type": "text", "text": f"Mouse clicked {button} at ({x}, {y})"}],
        }

    async def _tool_mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: Literal["left", "right", "middle"] = "left",
        duration_ms: int = 300,
        steps: int = 20,
    ) -> dict[str, Any]:
        if not self.input_injector:
            raise AdapterError("Input injector is not initialized")

        csx, csy = self._validate_boundary(start_x, start_y)
        cex, cey = self._validate_boundary(end_x, end_y)

        self.input_injector.mouse_drag(
            csx,
            csy,
            cex,
            cey,
            button=button,
            duration_ms=duration_ms,
            steps=steps,
        )

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Mouse dragged {button} from ({start_x}, {start_y}) to "
                        f"({end_x}, {end_y}) over {duration_ms}ms"
                    ),
                }
            ],
        }

    async def _tool_send_keys(
        self,
        keys: list[str],
        hold_duration_ms: int = 100,
        repeat_count: int = 1,
    ) -> dict[str, Any]:
        if not self.input_injector:
            raise AdapterError("Input injector is not initialized")

        self._validate_active_window_blacklist()

        self.input_injector.send_keys(
            keys,
            hold_duration_ms=hold_duration_ms,
            repeat_count=repeat_count,
        )

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Sent keys {keys} (hold {hold_duration_ms}ms, repeat {repeat_count})",
                }
            ],
        }

    async def _tool_execute_action_chunk(
        self,
        actions: list[dict[str, Any]],
        total_duration_ms: int,
    ) -> dict[str, Any]:
        if not self.action_scheduler:
            raise AdapterError("Action chunk scheduler is not initialized")

        self._validate_active_window_blacklist()

        chunk_items = [ActionChunkItem(**action) for action in actions]
        chunk = ActionChunk(actions=chunk_items, total_duration_ms=total_duration_ms)

        chunk_res = await self.action_scheduler.execute_chunk(chunk)
        executed_count = chunk_res.get("executed_count", 0)
        elapsed_ms = float(chunk_res.get("duration_ms", 0.0))

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Executed action chunk with {executed_count} actions in {elapsed_ms:.1f}ms"
                    ),
                }
            ],
        }

    async def _tool_gamepad_control(
        self,
        left_stick: StickCoordinates | dict[str, float] | None = None,
        right_stick: StickCoordinates | dict[str, float] | None = None,
        left_trigger: float = 0.0,
        right_trigger: float = 0.0,
        buttons_pressed: list[str] | None = None,
        duration_ms: int = 200,
    ) -> dict[str, Any]:
        if not self.gamepad:
            raise AdapterError("Gamepad controller is not initialized")

        if left_stick:
            lx = left_stick["x"] if isinstance(left_stick, dict) else left_stick.x
            ly = left_stick["y"] if isinstance(left_stick, dict) else left_stick.y
            self.gamepad.set_left_stick(lx, ly)

        if right_stick:
            rx = right_stick["x"] if isinstance(right_stick, dict) else right_stick.x
            ry = right_stick["y"] if isinstance(right_stick, dict) else right_stick.y
            self.gamepad.set_right_stick(rx, ry)

        self.gamepad.set_triggers(left_trigger, right_trigger)

        if buttons_pressed:
            for btn in buttons_pressed:
                self.gamepad.press_button(btn)

        # Hold state for requested duration
        await asyncio.sleep(duration_ms / 1000.0)

        # Reset gamepad to neutral
        self.gamepad.reset()

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": f"Gamepad actuated and held for {duration_ms}ms, then reset to neutral",
                }
            ],
        }

    async def _tool_window_focus(
        self,
        title_pattern: str,
        bring_to_front: bool = True,
    ) -> dict[str, Any]:
        if not self.window_manager:
            raise AdapterError("Window manager is not initialized")

        win = self.window_manager.find_window(title_pattern)
        if not win:
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": f"No active window matching pattern '{title_pattern}' found",
                    }
                ],
            }

        if self.blacklist_guard:
            self.blacklist_guard.assert_not_blacklisted(win.process_name, hwnd=win.hwnd)

        if bring_to_front:
            self.window_manager.bring_to_front(win.hwnd)

        self.bound_window_rect = (win.left, win.top, win.right, win.bottom)

        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Focused window '{win.title}' (PID: {win.process_id}, "
                        f"Process: {win.process_name}) with rect ({win.left}, {win.top}, "
                        f"{win.width}, {win.height})"
                    ),
                }
            ],
        }

    # -------------------------------------------------------------------------
    # Resource Readers
    # -------------------------------------------------------------------------

    async def _resource_audio_events(self) -> dict[str, Any]:
        if not self.audio_capturer:
            return {"status": "disabled", "events": []}

        events = self.audio_capturer.get_recent_events()
        return {
            "status": "recording" if self.audio_capturer.is_recording else "stopped",
            "events_count": len(events),
            "events": events,
        }

    async def _resource_screen_info(self) -> dict[str, Any]:
        fg_window = self.window_manager.get_foreground_window() if self.window_manager else None
        return {
            "active_backend": (
                self.screen_capturer.active_backend if self.screen_capturer else None
            ),
            "bound_window_rect": self.bound_window_rect,
            "foreground_window": fg_window.model_dump() if fg_window else None,
        }

    # -------------------------------------------------------------------------
    # Prompt Renderers
    # -------------------------------------------------------------------------

    async def _prompt_gameplay_strategy(
        self,
        game_title: str = "Desktop Video Game",
        objective: str = "Complete the game objective autonomously",
    ) -> list[dict[str, Any]]:
        text = (
            "You are an autonomous AI game-playing agent using the Universal Computer Use "
            f"adapter.\nGame: {game_title}\nObjective: {objective}\n\n"
            "Operational Workflow:\n"
            "1. Use `screenshot(annotate_grid=True)` to observe visual state with markers.\n"
            "2. Use `mouse_click(x, y)` or `mouse_drag(...)` to interact with the UI.\n"
            "3. Use `send_keys(['w'], hold_duration_ms=200)` for character movement.\n"
            "4. Use `execute_action_chunk` for timed multi-step motor sequences.\n"
            "5. Check `game://audio/events` for tactical sound cues (alarms, footsteps).\n"
            "6. Do not target blacklisted system processes."
        )
        return [{"role": "user", "content": {"type": "text", "text": text}}]

    # -------------------------------------------------------------------------
    # Helper Validations
    # -------------------------------------------------------------------------

    def _validate_boundary(self, x: int, y: int) -> tuple[int, int]:
        """Validate coordinates against bound window rect or foreground window rect."""
        if not self.boundary_guard:
            return x, y

        rect = self.bound_window_rect
        if rect is None and self.window_manager:
            fg = self.window_manager.get_foreground_window()
            if fg and not fg.is_minimized:
                rect = (fg.left, fg.top, fg.right, fg.bottom)

        if rect is not None:
            self.boundary_guard.set_rect(rect)
            return self.boundary_guard.validate_coordinates(x, y, strict=False)

        return x, y

    def _validate_active_window_blacklist(self) -> None:
        """Reject input injection if active foreground window is blacklisted."""
        if not self.blacklist_guard or not self.window_manager:
            return

        fg = self.window_manager.get_foreground_window()
        if fg:
            self.blacklist_guard.assert_not_blacklisted(fg.process_name, hwnd=fg.hwnd)
