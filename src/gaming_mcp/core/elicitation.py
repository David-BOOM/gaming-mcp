"""Human elicitation authorization gates for irreversible and high-risk operations.

Implements MCP elicitation/createMessage pattern to pause autonomous agent
routines before destructive actions (save deletion, save file overwrite,
in-game store transactions, configuration resets) until explicit human
authorization is confirmed.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from gaming_mcp.core.exceptions import ElicitationDeniedError

logger = logging.getLogger("gaming_mcp.core.elicitation")


class ElicitationRequest(BaseModel):
    """Payload representing a human authorization request."""

    action: str = Field(..., description="Target action identifier requiring approval")
    prompt: str = Field(..., description="Descriptive prompt presented to the human reviewer")
    risk_level: str = Field(
        default="critical",
        description="Assessed risk level: 'low', 'medium', 'high', or 'critical'",
    )
    timeout_sec: float = Field(
        default=60.0,
        gt=0.0,
        description="Timeout in seconds before automatic rejection",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Auxiliary context or parameters associated with the action",
    )


class ElicitationResponse(BaseModel):
    """Structured response from human reviewer or authorization handler."""

    action: str = Field(..., description="Action identifier")
    approved: bool = Field(..., description="True if authorization was granted")
    decision: Literal["accept", "decline", "cancel"] = Field(
        default="accept",
        description="Official MCP 3-state action outcome",
    )
    reason: str = Field(
        default="",
        description="Human justification or rejection explanation",
    )
    responder: str = Field(
        default="user",
        description="Identity of the authorizer (e.g. 'user', 'policy_engine')",
    )


ElicitationHandler = Callable[[ElicitationRequest], Awaitable[ElicitationResponse]]


class ElicitationGate:
    """Authorization gate evaluating high-risk actions via human elicitation."""

    DEFAULT_CRITICAL_ACTIONS: ClassVar[set[str]] = {
        "delete_save",
        "delete_world_save",
        "overwrite_save",
        "format_storage",
        "in_game_purchase",
        "reset_all_settings",
        "wipe_inventory",
    }

    def __init__(
        self,
        default_timeout_sec: float = 60.0,
        auto_approve: bool = False,
        handler: ElicitationHandler | None = None,
        critical_actions: set[str] | None = None,
    ) -> None:
        self.default_timeout_sec = default_timeout_sec
        self.auto_approve = auto_approve
        self.handler = handler
        self._critical_actions = {
            a.lower().strip() for a in (critical_actions or self.DEFAULT_CRITICAL_ACTIONS)
        }
        self._history: list[dict[str, Any]] = []

    def register_critical_action(self, action: str) -> None:
        """Add an action identifier to the critical actions registry."""
        self._critical_actions.add(action.lower().strip())

    def unregister_critical_action(self, action: str) -> None:
        """Remove an action identifier from the critical actions registry."""
        self._critical_actions.discard(action.lower().strip())

    def is_critical_action(self, action: str) -> bool:
        """Return True if the specified action requires human elicitation."""
        return action.lower().strip() in self._critical_actions

    def set_handler(self, handler: ElicitationHandler) -> None:
        """Set or replace the async elicitation callback handler."""
        self.handler = handler

    async def request_authorization(
        self,
        action: str,
        prompt: str = "",
        risk_level: str = "critical",
        timeout_sec: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ElicitationResponse:
        """Execute elicitation check, raising ElicitationDeniedError if rejected or timed out."""
        req_timeout = timeout_sec or self.default_timeout_sec
        req_prompt = prompt or f"Confirm execution of critical action '{action}'?"
        request = ElicitationRequest(
            action=action,
            prompt=req_prompt,
            risk_level=risk_level,
            timeout_sec=req_timeout,
            metadata=metadata or {},
        )

        logger.info(
            "Elicitation request initiated for action '%s' (risk=%s, timeout=%.1fs)",
            action,
            risk_level,
            req_timeout,
        )

        if self.auto_approve:
            logger.warning(
                "Elicitation auto_approve active: automatically authorizing action '%s'",
                action,
            )
            response = ElicitationResponse(
                action=action,
                approved=True,
                decision="accept",
                reason="Auto-approved by configuration",
                responder="auto_approver",
            )
            self._record_history(request, response)
            return response

        if self.handler is None:
            logger.error(
                "No elicitation handler registered to authorize critical action '%s'",
                action,
            )
            response = ElicitationResponse(
                action=action,
                approved=False,
                decision="decline",
                reason="No human elicitation handler registered",
                responder="system",
            )
            self._record_history(request, response)
            raise ElicitationDeniedError(action)

        try:
            response = await asyncio.wait_for(self.handler(request), timeout=req_timeout)
        except TimeoutError:
            logger.warning(
                "Human elicitation request timed out after %.1fs for action '%s'",
                req_timeout,
                action,
            )
            response = ElicitationResponse(
                action=action,
                approved=False,
                decision="cancel",
                reason=f"Human elicitation timed out after {req_timeout:.1f}s",
                responder="system",
            )
            self._record_history(request, response)
            raise ElicitationDeniedError(action) from None
        except Exception as exc:
            logger.error("Human elicitation handler failed for action '%s': %s", action, exc)
            response = ElicitationResponse(
                action=action,
                approved=False,
                decision="cancel",
                reason=f"Handler exception: {exc}",
                responder="system",
            )
            self._record_history(request, response)
            raise ElicitationDeniedError(action) from exc

        self._record_history(request, response)

        if not response.approved or response.decision != "accept":
            logger.warning(
                "Human elicitation denied authorization for action '%s' (decision=%s): %s",
                action,
                response.decision,
                response.reason,
            )
            raise ElicitationDeniedError(action)

        logger.info("Human elicitation granted authorization for action '%s'", action)
        return response

    def _record_history(self, request: ElicitationRequest, response: ElicitationResponse) -> None:
        """Store authorization attempt in audit history."""
        self._history.append(
            {
                "action": request.action,
                "risk_level": request.risk_level,
                "approved": response.approved,
                "decision": response.decision,
                "reason": response.reason,
                "responder": response.responder,
            }
        )

    def get_history(self) -> list[dict[str, Any]]:
        """Return deep copy history of all evaluated elicitation requests."""
        return [dict(record) for record in self._history]
