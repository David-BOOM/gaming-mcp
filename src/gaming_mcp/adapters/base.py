"""Abstract Service Provider Interface (SPI) for gaming adapters."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from gaming_mcp.config import GamingMCPConfig
    from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry


class AdapterMetadata(BaseModel):
    """Metadata detailing adapter capabilities, version, and requirements."""

    id: str = Field(..., description="Unique slug identifier (e.g. 'computer_use', 'minecraft')")
    display_name: str = Field(..., description="Human-readable title")
    version: str = Field(default="0.1.0", description="Semantic version string")
    description: str = Field(..., description="Description of adapter functionality")
    author: str = Field(default="Gaming MCP Team", description="Author or organization")
    supported_platforms: list[str] = Field(
        default_factory=lambda: ["win32", "linux", "darwin"],
        description="List of supported sys.platform values",
    )
    requires_display: bool = Field(
        default=True,
        description="Whether a visible desktop/display output is required",
    )
    requires_admin_privileges: bool = Field(
        default=False,
        description="Whether OS elevated privileges are required",
    )


class GameAdapter(ABC):
    """Abstract Service Provider Interface (SPI) for all gaming adapters."""

    def __init__(self, config: "GamingMCPConfig") -> None:
        self.config = config
        self.is_initialized: bool = False

    @property
    @abstractmethod
    def metadata(self) -> AdapterMetadata:
        """Return metadata detailing adapter capabilities and prerequisites."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Asynchronously initialize hardware drivers, game sockets, or child subprocesses."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully release virtual input drivers, stop subprocesses, and close sockets."""
        ...

    @abstractmethod
    def register_tools(self, registry: "ToolRegistry") -> None:
        """Declare and bind all execution tools into the active server registry."""
        ...

    @abstractmethod
    def register_resources(self, registry: "ResourceRegistry") -> None:
        """Declare and bind all readable telemetry resources into the active server registry."""
        ...

    @abstractmethod
    def register_prompts(self, registry: "PromptRegistry") -> None:
        """Declare contextual prompt templates for LLM strategic scaffolds."""
        ...

    async def health_check(self) -> dict[str, Any]:
        """Probe verifying process liveness, frame capture rates, and driver connectivity."""
        return {
            "adapter_id": self.metadata.id,
            "status": "healthy" if self.is_initialized else "uninitialized",
            "requires_display": self.metadata.requires_display,
        }
