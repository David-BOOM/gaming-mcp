"""Shared pytest fixtures and test configuration for gaming-mcp."""

import pytest

from gaming_mcp.config import GamingMCPConfig, TransportType


@pytest.fixture
def default_config() -> GamingMCPConfig:
    """Return default server configuration for testing."""
    return GamingMCPConfig()


@pytest.fixture
def stdio_config() -> GamingMCPConfig:
    """Return stdio transport configuration."""
    return GamingMCPConfig(transport=TransportType.STDIO)
