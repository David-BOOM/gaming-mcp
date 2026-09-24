"""Data models and schemas for Voyager-inspired skill library, macros, and telemetry."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from gaming_mcp.skills.store import (
    MacroStep,
    SkillDefinition,
    SkillExecutionRecord,
    SkillStep,
)


class ParameterDefinition(BaseModel):
    """Definition and constraints for a macro parameter."""

    type: str = Field(
        default="str",
        description="Data type of the parameter: str, int, float, bool, dict, list, or any.",
    )
    description: str = Field(
        default="",
        description="Human-readable description of what this parameter controls.",
    )
    default: Any = Field(
        default=None,
        description="Default value used when parameter is omitted from invocation.",
    )
    required: bool = Field(
        default=True,
        description="Whether this parameter is strictly required when executing the macro.",
    )


class StepExecutionResult(BaseModel):
    """Execution telemetry for a single macro step."""

    step_index: int = Field(
        description="Zero-based index of the step within the macro.",
    )
    tool_name: str = Field(
        description="Name of the invoked MCP tool.",
    )
    status: Literal["success", "failed", "repaired", "skipped"] = Field(
        description="Final execution outcome for this step.",
    )
    latency_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Execution duration in milliseconds.",
    )
    output: Any = Field(
        default=None,
        description="Result payload returned by the tool handler.",
    )
    error: str | None = Field(
        default=None,
        description="Error message if execution failed.",
    )
    retry_attempts: int = Field(
        default=0,
        ge=0,
        description="Number of retries attempted before resolution.",
    )
    compensated: bool = Field(
        default=False,
        description="Whether fallback compensation steps were executed.",
    )


class ExecutionRecord(BaseModel):
    """Comprehensive historical trace of a macro execution run."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique execution run identifier.",
    )
    skill_name: str = Field(
        description="Name of the executed skill.",
    )
    status: Literal["success", "failed", "repaired"] = Field(
        description="Overall macro execution outcome.",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Total wall-clock execution duration in milliseconds.",
    )
    start_time: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 execution start timestamp.",
    )
    end_time: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 execution end timestamp.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters passed to the macro invocation.",
    )
    steps: list[StepExecutionResult] = Field(
        default_factory=list,
        description="Chronological step execution records.",
    )
    error: str | None = Field(
        default=None,
        description="High-level error summary if macro execution failed.",
    )
    diagnosis: str | None = Field(
        default=None,
        description="Automated diagnostic report explaining failure causes and suggested fixes.",
    )


__all__ = [
    "ExecutionRecord",
    "MacroStep",
    "ParameterDefinition",
    "SkillDefinition",
    "SkillExecutionRecord",
    "SkillStep",
    "StepExecutionResult",
]
