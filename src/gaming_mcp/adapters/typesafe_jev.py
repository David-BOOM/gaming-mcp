"""TypeSafe JEV System 1 discrete decision adapter."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.config import GamingMCPConfig
from gaming_mcp.core.exceptions import AdapterError
from gaming_mcp.io.typesafe import (
    ChoiceAnswer,
    ChoiceQuestion,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneRequest,
    SystemOneState,
    TypeSafeClient,
    pcm_to_base64_wav,
)

if TYPE_CHECKING:
    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry
    from gaming_mcp.io.audio import WASAPIAudioCapturer
    from gaming_mcp.io.input import Win32InputInjector
    from gaming_mcp.io.screen import CompositeScreenCapturer

logger = logging.getLogger("gaming_mcp.adapters.typesafe_jev")


class JevEvaluateChoiceInput(BaseModel):
    """Input parameters for jev_evaluate_choice tool."""

    instructions: str = Field(..., min_length=1, description="Decision prompt directive")
    options: dict[str, str] | list[str] = Field(
        ...,
        description="Candidate options as a dictionary {id: description} or list of option strings",
    )
    context_text: str | None = Field(default=None, description="Optional text context or telemetry")
    capture_screen: bool = Field(default=False, description="Capture live display as visual state")
    capture_audio: bool = Field(default=False, description="Capture live audio as acoustic state")
    custom_image: str | None = Field(
        default=None, description="Optional custom base64 image data URL"
    )
    custom_audio: str | None = Field(
        default=None, description="Optional custom base64 audio data URL"
    )


class JevEvaluateScoreInput(BaseModel):
    """Input parameters for jev_evaluate_score tool."""

    instructions: str = Field(..., min_length=1, description="Scoring prompt directive")
    criteria: list[str] = Field(
        ...,
        min_length=2,
        max_length=10,
        description="Ordinal scale level descriptions (2 to 10 items in ascending order)",
    )
    context_text: str | None = Field(default=None, description="Optional text context or telemetry")
    capture_screen: bool = Field(default=False, description="Capture live display as visual state")
    capture_audio: bool = Field(default=False, description="Capture live audio as acoustic state")
    custom_image: str | None = Field(
        default=None, description="Optional custom base64 image data URL"
    )
    custom_audio: str | None = Field(
        default=None, description="Optional custom base64 audio data URL"
    )


class JevDecideAndActInput(BaseModel):
    """Input parameters for jev_decide_and_act tool."""

    instructions: str = Field(
        ..., min_length=1, description="Decision directive for evaluating candidate actions"
    )
    actions: dict[str, str | dict[str, Any]] = Field(
        ...,
        description="Dictionary mapping action candidate name to key or input macro",
    )
    confidence_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence required to dispatch the winning action",
    )
    execute: bool = Field(
        default=True, description="Whether to actuate input if confidence meets threshold"
    )
    context_text: str | None = Field(default=None, description="Optional text context or telemetry")
    capture_screen: bool = Field(default=False, description="Capture live display as visual state")
    capture_audio: bool = Field(default=False, description="Capture live audio as acoustic state")


class TypeSafeJEVAdapter(GameAdapter):
    """Game adapter integrating TypeSafe JEV System 1 discrete decision model."""

    def __init__(self, config: GamingMCPConfig | None = None) -> None:
        cfg = config or GamingMCPConfig.load()
        super().__init__(cfg)
        self.client = TypeSafeClient(self.config.adapters.typesafe_jev)
        self._screen_capturer: CompositeScreenCapturer | None = None
        self._audio_capturer: WASAPIAudioCapturer | None = None
        self._input_injector: Win32InputInjector | None = None

    @property
    def metadata(self) -> AdapterMetadata:
        """Return TypeSafe JEV adapter metadata."""
        return AdapterMetadata(
            id="typesafe_jev",
            display_name="TypeSafe JEV System 1 Decision Adapter",
            version="0.1.0",
            description=(
                "Low-latency discrete decision and scoring adapter powered by TypeSafe JEV "
                "via RelayRouter System One API"
            ),
            author="Gaming MCP Team",
            supported_platforms=["win32", "linux", "darwin"],
            requires_display=False,
            requires_admin_privileges=False,
        )

    async def initialize(self) -> None:
        """Initialize HTTP client and optional local perception capturers."""
        if self.is_initialized:
            return

        # Attempt to load visual capture if on Windows
        if sys.platform == "win32":
            try:
                from gaming_mcp.io.screen import CompositeScreenCapturer

                prefer_dxgi = self.config.screen.preferred_backend in ("auto", "dxgi")
                self._screen_capturer = CompositeScreenCapturer(
                    prefer_dxgi=prefer_dxgi,
                    monitor_index=self.config.screen.monitor_index,
                    dhash_threshold=self.config.screen.dhash_threshold,
                )
            except Exception as exc:
                logger.debug("CompositeScreenCapturer not initialized: %s", exc)

            try:
                from gaming_mcp.io.audio import WASAPIAudioCapturer

                self._audio_capturer = WASAPIAudioCapturer(
                    sample_rate=self.config.audio.sample_rate,
                    buffer_duration_sec=self.config.audio.buffer_duration_sec,
                )
            except Exception as exc:
                logger.debug("WASAPIAudioCapturer not initialized: %s", exc)

            try:
                from gaming_mcp.io.input import Win32InputInjector

                self._input_injector = Win32InputInjector()
            except Exception as exc:
                logger.debug("Win32InputInjector not initialized: %s", exc)

        self.is_initialized = True
        logger.info(
            "TypeSafeJEVAdapter initialized successfully (model=%s)",
            self.config.adapters.typesafe_jev.model,
        )

    async def shutdown(self) -> None:
        """Close client and release capturers."""
        if not self.is_initialized:
            return

        await self.client.close()

        if self._screen_capturer:
            with contextlib.suppress(Exception):
                self._screen_capturer.close()
            self._screen_capturer = None

        if self._audio_capturer:
            with contextlib.suppress(Exception):
                self._audio_capturer.close()
            self._audio_capturer = None

        self._input_injector = None
        self.is_initialized = False
        logger.info("TypeSafeJEVAdapter shut down cleanly")

    async def health_check(self) -> dict[str, Any]:
        """Probe liveness and return telemetry status."""
        health = await super().health_check()
        health.update(
            {
                "model": self.config.adapters.typesafe_jev.model,
                "mock_mode": self.config.adapters.typesafe_jev.mock_mode,
                "telemetry": self.client.get_telemetry(),
            }
        )
        return health

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register JEV System 1 discrete decision and scoring tools."""
        registry.register(
            name="jev_evaluate_choice",
            handler=self._tool_evaluate_choice,
            description=(
                "Evaluate discrete candidate options against current game screen, audio, or "
                "text telemetry using TypeSafe JEV System 1 model. Returns selected choice, "
                "confidence, and probabilities."
            ),
            input_model=JevEvaluateChoiceInput,
        )
        registry.register(
            name="jev_evaluate_score",
            handler=self._tool_evaluate_score,
            description=(
                "Evaluate danger, risk, or tactical score across 2 to 10 ordinal levels using "
                "TypeSafe JEV System 1 model. Returns continuous expected score index "
                "[0.0, N-1.0], confidence, and legend."
            ),
            input_model=JevEvaluateScoreInput,
        )
        registry.register(
            name="jev_decide_and_act",
            handler=self._tool_decide_and_act,
            description=(
                "Evaluate candidate actions and dispatch the winning motor keypress if "
                "decision confidence meets the specified confidence threshold."
            ),
            input_model=JevDecideAndActInput,
        )

    def register_resources(self, registry: ResourceRegistry) -> None:
        """Register live telemetry resource."""
        registry.register(
            uri="jev://telemetry",
            reader=self._resource_telemetry,
            name="TypeSafe JEV Telemetry",
            description=(
                "Operational telemetry including request counts, latency, and token consumption"
            ),
            mime_type="application/json",
        )

    def register_prompts(self, registry: PromptRegistry) -> None:
        """Register strategic scaffolding prompt for System 2 agent delegation."""
        registry.register(
            name="typesafe_tactical_scaffold",
            generator=self._prompt_tactical_scaffold,
            description=(
                "Guidance template for orchestrating LLMs to decompose game goals into JEV choices"
            ),
            arguments=[
                {
                    "name": "objective",
                    "description": "Current high-level game objective",
                    "required": False,
                },
                {
                    "name": "game_title",
                    "description": "Name of the target video game",
                    "required": False,
                },
            ],
        )

    async def _gather_state(
        self,
        context_text: str | None,
        capture_screen: bool,
        capture_audio: bool,
        custom_image: str | None,
        custom_audio: str | None,
    ) -> SystemOneState:
        """Build SystemOneState with optional visual and audio capture."""
        image_url = custom_image
        audio_url = custom_audio

        if capture_screen and not image_url and self._screen_capturer:
            try:
                from PIL import Image

                img: Image.Image | None = None
                if hasattr(self._screen_capturer, "capture"):
                    img = self._screen_capturer.capture()
                elif hasattr(self._screen_capturer, "capture_frame"):
                    frame = self._screen_capturer.capture_frame()
                    if frame is not None:
                        img = Image.fromarray(frame)
                if img is not None:
                    max_dim = max(img.width, img.height)
                    if max_dim > 1024:
                        scale = 1024.0 / max_dim
                        new_size = (int(img.width * scale), int(img.height * scale))
                        img = img.resize(new_size, Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=80)
                    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    image_url = f"data:image/jpeg;base64,{b64}"
            except Exception as exc:
                logger.debug("Screen capture failed for JEV state: %s", exc)

        if capture_audio and not audio_url and self._audio_capturer:
            try:
                samples = None
                if hasattr(self._audio_capturer, "get_recent_audio"):
                    samples = self._audio_capturer.get_recent_audio(duration_sec=1.5)
                elif hasattr(self._audio_capturer, "get_recent_samples"):
                    samples = self._audio_capturer.get_recent_samples(duration_sec=1.5)
                if samples is not None and len(samples) > 0:
                    audio_url = pcm_to_base64_wav(
                        samples, sample_rate=self.config.audio.sample_rate
                    )
            except Exception as exc:
                logger.debug("Audio capture failed for JEV state: %s", exc)

        return SystemOneState(
            text=context_text,
            image=image_url,
            audio=audio_url,
        )

    async def _tool_evaluate_choice(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute jev_evaluate_choice tool."""
        params = JevEvaluateChoiceInput.model_validate(args)

        # Normalize options to dict[str, str]
        if isinstance(params.options, list):
            criteria = {str(i): str(opt) for i, opt in enumerate(params.options)}
        else:
            criteria = {str(k): str(v) for k, v in params.options.items()}

        state = await self._gather_state(
            context_text=params.context_text,
            capture_screen=params.capture_screen,
            capture_audio=params.capture_audio,
            custom_image=params.custom_image,
            custom_audio=params.custom_audio,
        )

        request = SystemOneRequest(
            model=self.config.adapters.typesafe_jev.model,
            state=state,
            questions={
                "choice_q": ChoiceQuestion(
                    instructions=params.instructions,
                    criteria=criteria,
                )
            },
        )

        response = await self.client.evaluate(request)
        answer = response.answers.get("choice_q")
        if not isinstance(answer, ChoiceAnswer):
            raise AdapterError(f"Unexpected answer type for choice question: {type(answer)}")

        result_data = {
            "choice": answer.choice,
            "confidence": answer.confidence,
            "probabilities": answer.probabilities,
            "latency_ms": round(response.latency_ms, 2),
            "usage": response.usage.model_dump(),
        }
        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(result_data)}],
            **result_data,
        }

    async def _tool_evaluate_score(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute jev_evaluate_score tool."""
        params = JevEvaluateScoreInput.model_validate(args)

        state = await self._gather_state(
            context_text=params.context_text,
            capture_screen=params.capture_screen,
            capture_audio=params.capture_audio,
            custom_image=params.custom_image,
            custom_audio=params.custom_audio,
        )

        request = SystemOneRequest(
            model=self.config.adapters.typesafe_jev.model,
            state=state,
            questions={
                "score_q": ScoreQuestion(
                    instructions=params.instructions,
                    criteria=params.criteria,
                )
            },
        )

        response = await self.client.evaluate(request)
        answer = response.answers.get("score_q")
        if not isinstance(answer, ScoreAnswer):
            raise AdapterError(f"Unexpected answer type for score question: {type(answer)}")

        score_data = {
            "score": round(answer.score, 4),
            "confidence": answer.confidence,
            "legend": answer.legend,
            "probabilities": answer.probabilities,
            "latency_ms": round(response.latency_ms, 2),
            "usage": response.usage.model_dump(),
        }
        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(score_data)}],
            **score_data,
        }

    async def _tool_decide_and_act(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute jev_decide_and_act tool."""
        params = JevDecideAndActInput.model_validate(args)

        criteria = {act_name: f"Action: {act_name}" for act_name in params.actions}

        state = await self._gather_state(
            context_text=params.context_text,
            capture_screen=params.capture_screen,
            capture_audio=params.capture_audio,
            custom_image=None,
            custom_audio=None,
        )

        request = SystemOneRequest(
            model=self.config.adapters.typesafe_jev.model,
            state=state,
            questions={
                "action_decision": ChoiceQuestion(
                    instructions=params.instructions,
                    criteria=criteria,
                )
            },
        )

        response = await self.client.evaluate(request)
        answer = response.answers.get("action_decision")
        if not isinstance(answer, ChoiceAnswer):
            raise AdapterError(f"Unexpected answer type for action decision: {type(answer)}")

        selected_action = answer.choice
        confidence = answer.confidence
        probabilities = answer.probabilities

        if confidence < params.confidence_threshold:
            abort_data = {
                "status": "aborted_low_confidence",
                "action_executed": False,
                "selected_action": selected_action,
                "confidence": confidence,
                "threshold": params.confidence_threshold,
                "probabilities": probabilities,
                "latency_ms": round(response.latency_ms, 2),
            }
            return {
                "isError": False,
                "content": [{"type": "text", "text": json.dumps(abort_data)}],
                **abort_data,
            }

        executed = False
        if params.execute:
            action_val = params.actions.get(selected_action)
            executed = self._dispatch_action(selected_action, action_val)

        exec_data = {
            "status": "executed" if executed else "evaluated_only",
            "action_executed": executed,
            "selected_action": selected_action,
            "confidence": confidence,
            "probabilities": probabilities,
            "latency_ms": round(response.latency_ms, 2),
            "usage": response.usage.model_dump(),
        }
        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(exec_data)}],
            **exec_data,
        }

    def _dispatch_action(self, action_name: str, action_val: Any) -> bool:
        """Dispatch winning action to input injector if on Windows."""
        if sys.platform != "win32" or not self._input_injector:
            logger.info(
                "Simulated actuation for action '%s' (platform=%s)", action_name, sys.platform
            )
            return True

        try:
            if isinstance(action_val, str):
                self._input_injector.press_key(action_val)
                return True
            if isinstance(action_val, dict):
                key = action_val.get("key", action_name)
                hold_ms = action_val.get("hold_ms", 50)
                self._input_injector.press_key(key, hold_duration_ms=float(hold_ms))
                return True
            return False
        except Exception as exc:
            logger.warning("Actuation failed for action '%s': %s", action_name, exc)
            return False

    async def _resource_telemetry(self) -> dict[str, Any]:
        """Read jev://telemetry resource."""
        telemetry = self.client.get_telemetry()
        return {
            "uri": "jev://telemetry",
            "contents": [
                {
                    "uri": "jev://telemetry",
                    "mimeType": "application/json",
                    "text": json.dumps(telemetry, indent=2),
                }
            ],
        }

    async def _prompt_tactical_scaffold(
        self,
        args: dict[str, Any] | None = None,
        *,
        objective: str | None = None,
        game_title: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate typesafe_tactical_scaffold prompt."""
        params = args if isinstance(args, dict) else {}
        obj = (
            objective
            or params.get("objective")
            or kwargs.get("objective")
            or "Survive and progress"
        )
        game = (
            game_title
            or params.get("game_title")
            or kwargs.get("game_title")
            or "Current video game"
        )

        prompt_text = (
            f"You are playing '{game}' with high-level objective: '{obj}'.\n\n"
            "SYSTEM ARCHITECTURE DIRECTIVE:\n"
            "- You are the System 2 deliberative planner.\n"
            "- The JEV model connected via TypeSafe System One is your System 1 discrete "
            "tactical evaluator.\n"
            "- Do not hesitate or stall in complex perceptual loops. Decompose situations "
            "into 2-5 candidate actions and invoke 'jev_decide_and_act' or 'jev_evaluate_choice' "
            "to let JEV score and select the best move.\n"
            "- Use 'jev_evaluate_score' to monitor threat levels on an ordinal scale "
            "(e.g. ['safe', 'cautious', 'critical']).\n"
            "- When threat is critical, prioritize defensive macros and immediate "
            "evasive maneuvers."
        )

        return {
            "description": f"Tactical decision scaffold for {game}",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": prompt_text},
                }
            ],
        }
