"""Typed exception hierarchy for gaming-mcp server."""

from typing import Any


class GamingMCPError(Exception):
    """Root exception for all gaming-mcp errors."""

    def __init__(
        self,
        message: str,
        error_code: int = -32000,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.data = data or {}
        super().__init__(message)

    def to_jsonrpc_error(self) -> dict[str, Any]:
        """Format exception as standard JSON-RPC 2.0 error object."""
        result: dict[str, Any] = {
            "code": self.error_code,
            "message": self.message,
        }
        if self.data:
            result["data"] = self.data
        return result


class AdapterError(GamingMCPError):
    """Raised when an adapter fails to initialize, execute, or communicate."""

    def __init__(
        self,
        message: str,
        error_code: int = -32002,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code, data=data)


class AdapterNotFoundError(AdapterError):
    """Raised when the requested adapter_id does not exist in the registry."""

    def __init__(self, adapter_id: str) -> None:
        super().__init__(
            f"Adapter '{adapter_id}' not found in registry",
            error_code=-32001,
            data={"adapter_id": adapter_id},
        )


class AdapterInitializationError(AdapterError):
    """Raised when adapter hardware or child process initialization fails."""

    def __init__(self, adapter_id: str, reason: str) -> None:
        super().__init__(
            f"Adapter '{adapter_id}' failed to initialize: {reason}",
            error_code=-32002,
            data={"adapter_id": adapter_id, "reason": reason},
        )


class CaptureError(GamingMCPError):
    """Raised when screen, audio, or memory capture fails."""

    def __init__(
        self,
        message: str,
        error_code: int = -32001,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code, data=data)


class DXGICaptureError(CaptureError):
    """DXGI Desktop Duplication specific failures."""

    def __init__(self, message: str, hr: int | None = None) -> None:
        data = {"hresult": hex(hr)} if hr is not None else {}
        super().__init__(message, error_code=-32001, data=data)


class InputInjectionError(GamingMCPError):
    """Raised when keyboard, mouse, or gamepad input injection is blocked or fails."""

    def __init__(
        self,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code=-32001, data=data)


class SecurityViolationError(GamingMCPError):
    """Raised when a safety guardrail is triggered (window boundary, blacklisted process)."""

    def __init__(self, violation_type: str, details: str) -> None:
        super().__init__(
            f"Security violation [{violation_type}]: {details}",
            error_code=-32004,
            data={"violation_type": violation_type, "details": details},
        )


class SafetyKillSwitchError(GamingMCPError):
    """Raised when emergency hardware kill-switch is activated."""

    def __init__(self, message: str = "Emergency hardware kill-switch activated") -> None:
        super().__init__(message, error_code=-32005)


SafetyKillSwitchTriggered = SafetyKillSwitchError


class SkillExecutionError(GamingMCPError):
    """Raised when a macro skill step fails during replay."""

    def __init__(self, message: str, step_index: int | None = None) -> None:
        data = {"step_index": step_index} if step_index is not None else {}
        super().__init__(message, error_code=-32000, data=data)


class ElicitationDeniedError(GamingMCPError):
    """Raised when human elicitation gate is denied by user."""

    def __init__(self, action: str) -> None:
        super().__init__(
            f"Human elicitation denied for action: {action}",
            error_code=-32006,
            data={"action": action},
        )
