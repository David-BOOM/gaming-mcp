"""Configuration models and loader for gaming-mcp server."""

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TransportType(StrEnum):
    """Supported server transport protocols."""

    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


class ScreenCaptureConfig(BaseModel):
    """Configuration for visual perception and frame capture."""

    preferred_backend: str = Field(
        default="auto",
        description="'auto', 'dxgi', 'mss', or 'pillow'",
    )
    default_format: str = Field(
        default="jpeg",
        description="'jpeg' or 'png'",
    )
    jpeg_quality: int = Field(
        default=85,
        ge=1,
        le=100,
        description="JPEG compression quality parameter",
    )
    downscale_resolution: tuple[int, int] = Field(
        default=(1024, 576),
        description="Target width and height for frame downscaling",
    )
    dhash_threshold: int = Field(
        default=3,
        ge=0,
        le=64,
        description="Hamming distance threshold for 64-bit dHash perceptual gating",
    )
    som_grid_spacing: int = Field(
        default=100,
        ge=25,
        le=500,
        description="Pixel spacing for Set-of-Marks visual coordinate grid",
    )


class InputConfig(BaseModel):
    """Configuration for keyboard, mouse, and gamepad actuation."""

    preferred_backend: str = Field(
        default="auto",
        description="'auto', 'scancode', 'vigem', or 'pyautogui'",
    )
    mouse_smoothing: bool = Field(
        default=True,
        description="Apply polynomial minimum-jerk trajectory smoothing to mouse movement",
    )
    jitter_range_px: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Random micro-jitter pixel range for human-like motor dispersion",
    )
    keypress_mean_ms: float = Field(
        default=85.0,
        ge=10.0,
        description="Gaussian distribution mean for discrete keypress hold duration (ms)",
    )
    keypress_std_ms: float = Field(
        default=15.0,
        ge=0.0,
        description="Gaussian distribution standard deviation for keypress duration (ms)",
    )


class AudioConfig(BaseModel):
    """Configuration for WASAPI / PulseAudio loopback audio capture."""

    enabled: bool = Field(
        default=False,
        description="Enable master audio output loopback capture",
    )
    sample_rate: int = Field(
        default=48000,
        description="Audio sampling rate in Hz (WASAPI default is 48kHz)",
    )
    mel_bands: int = Field(
        default=64,
        description="Number of Mel frequency filter banks for spectrogram extraction",
    )


class SecurityConfig(BaseModel):
    """Safety guardrails, window bounds, process isolation, and kill-switches."""

    enable_kill_switch: bool = Field(
        default=True,
        description="Enable global emergency keyboard kill-switch hook",
    )
    kill_switch_combo: list[str] = Field(
        default_factory=lambda: ["ctrl", "alt", "shift", "pause"],
        description="Key combo to trigger instantaneous motor disconnect",
    )
    window_boundary_clipping: bool = Field(
        default=True,
        description="Clamp mouse cursor coordinates strictly to the active target window rect",
    )
    blacklisted_processes: list[str] = Field(
        default_factory=lambda: [
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "Taskmgr.exe",
            "regedit.exe",
            "mmc.exe",
            "explorer.exe",
            "CredentialUIBroker.exe",
        ],
        description="Processes protected against input injection and focus locking",
    )
    privacy_redaction_zones: list[dict[str, int]] = Field(
        default_factory=list,
        description=(
            "List of bounding boxes {x, y, width, height} to zero out before frame encoding"
        ),
    )


class AdapterConfig(BaseModel):
    """Configuration for game adapter integrations."""

    default_adapter: str = Field(
        default="computer_use",
        description="Initial adapter to activate on server startup",
    )
    minecraft: dict[str, Any] | None = None
    retro: dict[str, Any] | None = None
    gymnasium: dict[str, Any] | None = None


class GamingMCPConfig(BaseModel):
    """Master configuration schema for the Gaming MCP Server."""

    transport: TransportType = TransportType.STDIO
    host: str = Field(default="127.0.0.1", description="Bind host for SSE/HTTP transport")
    port: int = Field(
        default=8080,
        ge=1024,
        le=65535,
        description="Bind port for SSE/HTTP transport",
    )
    screen: ScreenCaptureConfig = Field(default_factory=ScreenCaptureConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    adapters: AdapterConfig = Field(default_factory=AdapterConfig)
    log_level: str = Field(default="INFO", description="'DEBUG', 'INFO', 'WARNING', 'ERROR'")

    @classmethod
    def load(cls, config_path: str | None = None) -> "GamingMCPConfig":
        """Load configuration from file, environment variables, and defaults."""
        data: dict[str, Any] = {}

        # 1. Load from file if specified or if default config.json exists
        target_path: Path | None = None
        if config_path:
            target_path = Path(config_path)
        elif Path("config.json").exists():
            target_path = Path("config.json")

        if target_path and target_path.exists():
            with open(target_path, encoding="utf-8") as f:
                data = json.load(f)

        # 2. Override from environment variables
        env_transport = os.getenv("GAMING_MCP_TRANSPORT")
        if env_transport:
            data["transport"] = env_transport

        env_host = os.getenv("GAMING_MCP_HOST")
        if env_host:
            data["host"] = env_host

        env_port = os.getenv("GAMING_MCP_PORT")
        if env_port:
            data["port"] = int(env_port)

        env_adapter = os.getenv("GAMING_MCP_ADAPTER")
        if env_adapter:
            adapters = data.get("adapters", {})
            adapters["default_adapter"] = env_adapter
            data["adapters"] = adapters

        env_log_level = os.getenv("GAMING_MCP_LOG_LEVEL")
        if env_log_level:
            data["log_level"] = env_log_level

        return cls(**data)
