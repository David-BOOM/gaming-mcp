"""Game adapter service provider interfaces and implementations."""

from gaming_mcp.adapters.base import AdapterMetadata, GameAdapter
from gaming_mcp.adapters.computer_use import ComputerUseAdapter
from gaming_mcp.adapters.minecraft import MinecraftAdapter, MinecraftBridge
from gaming_mcp.adapters.router import AdapterRouter, SwitchAdapterInput

__all__ = [
    "AdapterMetadata",
    "AdapterRouter",
    "ComputerUseAdapter",
    "GameAdapter",
    "MinecraftAdapter",
    "MinecraftBridge",
    "SwitchAdapterInput",
]
