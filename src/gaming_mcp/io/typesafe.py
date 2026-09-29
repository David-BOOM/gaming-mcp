"""TypeSafe System One (JEV) client and protocol models."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import wave
from typing import TYPE_CHECKING, Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from gaming_mcp.core.exceptions import AdapterError

if TYPE_CHECKING:
    from gaming_mcp.config import TypeSafeJEVConfig

logger = logging.getLogger("gaming_mcp.io.typesafe")


def pcm_to_base64_wav(samples: Any, sample_rate: int = 44100) -> str:
    """Convert audio samples to a base64-encoded WAV data URL.

    Accepts a NumPy array or sequence of float samples in the range [-1.0, 1.0].
    """
    try:
        import numpy as np

        if isinstance(samples, np.ndarray):
            clamped = np.clip(samples, -1.0, 1.0)
            int16_samples = (clamped * 32767.0).astype(np.int16)
            channels = int16_samples.shape[1] if int16_samples.ndim > 1 else 1
            raw_bytes = int16_samples.tobytes()
        else:
            # Fallback for standard sequence of floats
            int16_list = [int(max(-1.0, min(1.0, float(x))) * 32767.0) for x in samples]
            import struct

            raw_bytes = struct.pack(f"<{len(int16_list)}h", *int16_list)
            channels = 1
    except ImportError:
        import struct

        int16_list = [int(max(-1.0, min(1.0, float(x))) * 32767.0) for x in samples]
        raw_bytes = struct.pack(f"<{len(int16_list)}h", *int16_list)
        channels = 1

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_bytes)

    b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:audio/wav;base64,{b64_str}"


class SystemOneState(BaseModel):
    """Multimodal observation state provided to JEV System 1."""

    model_config = ConfigDict(extra="ignore")

    text: str | None = Field(default=None, description="Textual context or observation")
    image: str | None = Field(default=None, description="Base64 or data URL encoded visual frame")
    audio: str | None = Field(default=None, description="Base64 or data URL encoded audio sample")


class ChoiceQuestion(BaseModel):
    """Discrete tactical choice question."""

    type: Literal["choice"] = "choice"
    instructions: str = Field(..., min_length=1, description="Decision prompt directive")
    criteria: dict[str, str] = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Dictionary mapping option IDs to option descriptions (1 to 255 items)",
    )


class ScoreQuestion(BaseModel):
    """Ordinal scale evaluation question."""

    type: Literal["score"] = "score"
    instructions: str = Field(..., min_length=1, description="Scoring prompt directive")
    criteria: list[str] = Field(
        ...,
        min_length=2,
        max_length=10,
        description="List of 2 to 10 scale level description strings",
    )


Question = Annotated[
    ChoiceQuestion | ScoreQuestion,
    Field(discriminator="type"),
]


class SystemOneRequest(BaseModel):
    """Full request payload for /v1/systemone."""

    model: str = Field(default="jev-1.13.0", description="Model identifier")
    state: SystemOneState = Field(default_factory=SystemOneState, description="Observation state")
    questions: dict[str, Question] = Field(
        ...,
        min_length=1,
        description="Dictionary of question ID to Question definition",
    )


class ChoiceAnswer(BaseModel):
    """Evaluated discrete choice answer."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["choice"] = "choice"
    choice: str = Field(..., description="Selected option ID")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Decision confidence")
    probabilities: dict[str, float] = Field(
        default_factory=dict,
        description="Probability distribution across options",
    )


class ScoreAnswer(BaseModel):
    """Evaluated ordinal score answer."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["score"] = "score"
    score: float = Field(
        ..., description="Continuous expected score index across levels [0.0, N-1.0]"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Scoring confidence")
    legend: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping from level index string to level description",
    )
    probabilities: dict[str, float] = Field(
        default_factory=dict,
        description="Probability distribution across level indices",
    )


QuestionAnswer = Annotated[
    ChoiceAnswer | ScoreAnswer,
    Field(discriminator="type"),
]


class TokenUsage(BaseModel):
    """Token consumption metrics."""

    model_config = ConfigDict(extra="ignore")

    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)


class SystemOneResponse(BaseModel):
    """Parsed response envelope from /v1/systemone."""

    model_config = ConfigDict(extra="ignore")

    model: str
    answers: dict[str, QuestionAnswer]
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = Field(default=0.0)


class TypeSafeClient:
    """Asynchronous client for RelayRouter TypeSafe System One (/v1/systemone)."""

    def __init__(self, config: TypeSafeJEVConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._requests_total = 0
        self._requests_success = 0
        self._requests_failed = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._cumulative_latency_ms = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                headers=headers,
                timeout=httpx.Timeout(self.config.timeout_sec),
            )
        return self._client

    async def close(self) -> None:
        """Close underlying HTTP client connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def get_telemetry(self) -> dict[str, Any]:
        """Return cumulative telemetry and operational metrics."""
        avg_latency = (
            self._cumulative_latency_ms / self._requests_success
            if self._requests_success > 0
            else 0.0
        )
        return {
            "requests_total": self._requests_total,
            "requests_success": self._requests_success,
            "requests_failed": self._requests_failed,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "average_latency_ms": round(avg_latency, 2),
            "mock_mode": self.config.mock_mode,
            "active_model": self.config.model,
        }

    async def evaluate(self, request: SystemOneRequest) -> SystemOneResponse:
        """Evaluate a System One request payload with retries and latency tracking."""
        self._requests_total += 1
        start_time = time.perf_counter()

        if self.config.mock_mode:
            return self._simulate_mock_response(request, start_time)

        client = await self._get_client()
        payload = request.model_dump(exclude_none=True)

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await client.post("/systemone", json=payload)
                if resp.status_code == 200:
                    latency_ms = (time.perf_counter() - start_time) * 1000.0
                    data = resp.json()
                    data["latency_ms"] = latency_ms

                    parsed = SystemOneResponse.model_validate(data)
                    self._requests_success += 1
                    self._total_input_tokens += parsed.usage.input_tokens
                    self._total_output_tokens += parsed.usage.output_tokens
                    self._cumulative_latency_ms += latency_ms
                    return parsed

                if resp.status_code in (429, 502, 503, 504) and attempt < self.config.max_retries:
                    wait_sec = 0.5 * (2**attempt)
                    logger.warning(
                        "TypeSafe JEV returned HTTP %d, retrying in %.2fs (attempt %d/%d)",
                        resp.status_code,
                        wait_sec,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(wait_sec)
                    continue

                error_body = resp.text
                self._requests_failed += 1
                raise AdapterError(
                    f"TypeSafe JEV request failed with HTTP {resp.status_code}: {error_body}",
                    data={"status_code": resp.status_code, "body": error_body},
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    wait_sec = 0.5 * (2**attempt)
                    await asyncio.sleep(wait_sec)
                    continue
                self._requests_failed += 1
                raise AdapterError(
                    f"TypeSafe JEV request timed out after {self.config.timeout_sec}s: {exc}",
                ) from exc
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    wait_sec = 0.5 * (2**attempt)
                    await asyncio.sleep(wait_sec)
                    continue
                self._requests_failed += 1
                raise AdapterError(f"TypeSafe JEV network error: {exc}") from exc

        self._requests_failed += 1
        raise AdapterError(f"TypeSafe JEV request failed after retries: {last_error}")

    def _simulate_mock_response(
        self,
        request: SystemOneRequest,
        start_time: float,
    ) -> SystemOneResponse:
        """Generate high-fidelity deterministic response for offline simulation."""
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        answers: dict[str, Any] = {}

        for q_id, q in request.questions.items():
            if q.type == "choice":
                options = list(q.criteria.keys())
                selected = options[0] if options else "0"
                probs = {opt: (1.0 if opt == selected else 0.0) for opt in options}
                answers[q_id] = {
                    "type": "choice",
                    "choice": selected,
                    "confidence": 0.95,
                    "probabilities": probs,
                }
            elif q.type == "score":
                levels = q.criteria
                legend = {str(i): level for i, level in enumerate(levels)}
                probs = {str(i): (1.0 if i == 0 else 0.0) for i in range(len(levels))}
                answers[q_id] = {
                    "type": "score",
                    "score": 0.0,
                    "confidence": 0.90,
                    "legend": legend,
                    "probabilities": probs,
                }

        self._requests_success += 1
        self._total_input_tokens += 120
        self._total_output_tokens += 25
        self._cumulative_latency_ms += latency_ms

        return SystemOneResponse(
            model=request.model,
            answers=answers,
            usage=TokenUsage(input_tokens=120, output_tokens=25),
            latency_ms=latency_ms,
        )
