"""Core protocol, registration, and lifecycle primitives."""

from gaming_mcp.core.elicitation import (
    ElicitationGate,
    ElicitationRequest,
    ElicitationResponse,
)
from gaming_mcp.core.exceptions import (
    AdapterError,
    AdapterInitializationError,
    AdapterNotFoundError,
    CaptureError,
    DXGICaptureError,
    ElicitationDeniedError,
    GamingMCPError,
    InputInjectionError,
    SafetyKillSwitchError,
    SafetyKillSwitchTriggered,
    SecurityViolationError,
    SkillExecutionError,
)

__all__ = [
    "AdapterError",
    "AdapterInitializationError",
    "AdapterNotFoundError",
    "CaptureError",
    "DXGICaptureError",
    "ElicitationDeniedError",
    "ElicitationGate",
    "ElicitationRequest",
    "ElicitationResponse",
    "GamingMCPError",
    "InputInjectionError",
    "SafetyKillSwitchError",
    "SafetyKillSwitchTriggered",
    "SecurityViolationError",
    "SkillExecutionError",
]
