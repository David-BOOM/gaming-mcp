"""Pydantic v2 schemas and enumerations for the unified game_control tool interface."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MovementType(StrEnum):
    """Supported directional movement commands."""

    FORWARD = "forward"
    BACKWARD = "backward"
    STRAFE_LEFT = "strafe_left"
    STRAFE_RIGHT = "strafe_right"
    JUMP = "jump"
    SPRINT = "sprint"
    CROUCH = "crouch"


class LookDirection(StrEnum):
    """Cardinal camera look directions."""

    LOOK_UP = "look_up"
    LOOK_DOWN = "look_down"
    LOOK_LEFT = "look_left"
    LOOK_RIGHT = "look_right"


class LookInput(BaseModel):
    """Camera look and angular rotation parameters."""

    direction: LookDirection | None = Field(
        default=None,
        description="Discrete cardinal look direction",
    )
    dx: int | None = Field(
        default=None,
        description="Relative horizontal mouse movement delta in pixels",
    )
    dy: int | None = Field(
        default=None,
        description="Relative vertical mouse movement delta in pixels",
    )
    yaw: float | None = Field(
        default=None,
        description="Horizontal camera rotation in degrees",
    )
    pitch: float | None = Field(
        default=None,
        description="Vertical camera rotation in degrees",
    )
    smooth: bool = Field(
        default=True,
        description="Apply Flash and Hogan minimum-jerk trajectory splining",
    )


class ActionType(StrEnum):
    """Common game actions and interactions."""

    PRIMARY_ACTION = "primary_action"
    SECONDARY_ACTION = "secondary_action"
    INTERACT = "interact"
    RELOAD = "reload"
    PAUSE = "pause"
    MENU = "menu"


class SequenceStep(BaseModel):
    """Individual action step inside a compound sequence."""

    movement: MovementType | None = Field(
        default=None,
        description="Directional locomotion command",
    )
    look: LookInput | None = Field(
        default=None,
        description="Camera view rotation or relative mouse delta",
    )
    action: ActionType | None = Field(
        default=None,
        description="Standard game interaction or contextual action",
    )
    slot: int | None = Field(
        default=None,
        ge=1,
        le=9,
        description="Hotbar or weapon inventory slot (1 to 9)",
    )
    chord: list[str] | None = Field(
        default=None,
        description="Simultaneous multi-key or button chord",
    )
    delay_ms: int = Field(
        default=0,
        ge=0,
        description="Delay in milliseconds before step execution",
    )
    hold_duration_ms: int = Field(
        default=50,
        ge=0,
        description="Duration in milliseconds to hold keys down",
    )


class GameControlInput(BaseModel):
    """Input parameters for the unified game_control tool."""

    movement: MovementType | None = Field(
        default=None,
        description="Directional locomotion or locomotion modifier",
    )
    look: LookInput | None = Field(
        default=None,
        description="Camera view rotation or relative mouse delta",
    )
    action: ActionType | None = Field(
        default=None,
        description="Standard game interaction or contextual action",
    )
    slot: int | None = Field(
        default=None,
        ge=1,
        le=9,
        description="Hotbar or weapon inventory slot (1 to 9)",
    )
    chord: list[str] | None = Field(
        default=None,
        description="Simultaneous multi-key or button chord",
    )
    sequence: list[SequenceStep] | None = Field(
        default=None,
        description="Timed multi-step action sequence",
    )
    hold_duration_ms: int = Field(
        default=50,
        ge=0,
        description="Duration in milliseconds to hold keys down",
    )


class GameControlOutput(BaseModel):
    """Standardized response schema for game_control tool."""

    success: bool = Field(description="Whether the control action executed successfully")
    status: str = Field(description="Execution status summary (e.g. executed, noop, cancelled)")
    action_type: str = Field(description="Primary action category executed")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured execution metadata, key mappings, and delta details",
    )
