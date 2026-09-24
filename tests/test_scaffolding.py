"""Tests for package scaffolding, configuration, exceptions, and CLI parsing."""

import json
from pathlib import Path

import pytest

from gaming_mcp import __version__
from gaming_mcp.__main__ import parse_args
from gaming_mcp.config import GamingMCPConfig, TransportType
from gaming_mcp.core.exceptions import (
    AdapterInitializationError,
    AdapterNotFoundError,
    CaptureError,
    DXGICaptureError,
    ElicitationDeniedError,
    GamingMCPError,
    InputInjectionError,
    SafetyKillSwitchTriggered,
    SecurityViolationError,
    SkillExecutionError,
)
from gaming_mcp.utils.logging import StructuredFormatter, setup_logging


def test_package_version() -> None:
    """Verify package version is defined and follows semver."""
    assert __version__ == "0.1.0"


def test_default_configuration(default_config: GamingMCPConfig) -> None:
    """Verify default configuration values adhere to system invariants."""
    assert default_config.transport == TransportType.STDIO
    assert default_config.host == "127.0.0.1"
    assert default_config.port == 8080
    assert default_config.screen.jpeg_quality == 85
    assert default_config.screen.dhash_threshold == 3
    assert default_config.security.enable_kill_switch is True
    assert "cmd.exe" in default_config.security.blacklisted_processes
    assert "powershell.exe" in default_config.security.blacklisted_processes
    assert "Taskmgr.exe" in default_config.security.blacklisted_processes
    assert default_config.adapters.default_adapter == "computer_use"


def test_config_loader_from_file(tmp_path: Path) -> None:
    """Verify configuration loads cleanly from JSON file."""
    config_file = tmp_path / "custom_config.json"
    custom_data = {
        "transport": "http",
        "port": 9090,
        "screen": {
            "jpeg_quality": 90,
            "dhash_threshold": 5,
        },
        "adapters": {
            "default_adapter": "minecraft",
        },
    }
    config_file.write_text(json.dumps(custom_data), encoding="utf-8")

    cfg = GamingMCPConfig.load(str(config_file))
    assert cfg.transport == TransportType.HTTP
    assert cfg.port == 9090
    assert cfg.screen.jpeg_quality == 90
    assert cfg.screen.dhash_threshold == 5
    assert cfg.adapters.default_adapter == "minecraft"


def test_config_loader_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify environment variables override configuration defaults."""
    monkeypatch.setenv("GAMING_MCP_TRANSPORT", "sse")
    monkeypatch.setenv("GAMING_MCP_PORT", "9999")
    monkeypatch.setenv("GAMING_MCP_ADAPTER", "retro")
    monkeypatch.setenv("GAMING_MCP_LOG_LEVEL", "DEBUG")

    cfg = GamingMCPConfig.load()
    assert cfg.transport == TransportType.SSE
    assert cfg.port == 9999
    assert cfg.adapters.default_adapter == "retro"
    assert cfg.log_level == "DEBUG"


def test_cli_argument_parsing() -> None:
    """Verify CLI argument parsing handles flags correctly."""
    args = parse_args(
        [
            "--transport",
            "http",
            "--port",
            "8888",
            "--adapter",
            "minecraft",
            "--log-level",
            "DEBUG",
        ]
    )
    assert args.transport == "http"
    assert args.port == 8888
    assert args.adapter == "minecraft"
    assert args.log_level == "DEBUG"


def test_typed_exceptions_jsonrpc_mapping() -> None:
    """Verify all custom exceptions map properly to JSON-RPC error formats."""
    err = GamingMCPError("generic failure", error_code=-32000, data={"detail": "info"})
    json_err = err.to_jsonrpc_error()
    assert json_err["code"] == -32000
    assert json_err["message"] == "generic failure"
    assert json_err["data"]["detail"] == "info"

    adapter_err = AdapterNotFoundError("nonexistent")
    assert adapter_err.error_code == -32001
    assert "nonexistent" in adapter_err.message
    assert adapter_err.data["adapter_id"] == "nonexistent"

    init_err = AdapterInitializationError("vi_gem", "device missing")
    assert init_err.error_code == -32002
    assert "vi_gem" in init_err.message

    cap_err = CaptureError("frame dropped")
    assert cap_err.error_code == -32001

    dxgi_err = DXGICaptureError("surface lost", hr=0x887A0026)
    assert dxgi_err.error_code == -32001
    assert dxgi_err.data["hresult"] == "0x887a0026"

    inj_err = InputInjectionError("failed to inject scan code")
    assert inj_err.error_code == -32001

    sec_err = SecurityViolationError("blacklist", "cmd.exe active")
    assert sec_err.error_code == -32004
    assert sec_err.data["violation_type"] == "blacklist"

    kill_err = SafetyKillSwitchTriggered()
    assert kill_err.error_code == -32005

    skill_err = SkillExecutionError("step failed", step_index=3)
    assert skill_err.error_code == -32000
    assert skill_err.data["step_index"] == 3

    elic_err = ElicitationDeniedError("format_c")
    assert elic_err.error_code == -32006
    assert elic_err.data["action"] == "format_c"


def test_structured_logger_formatting() -> None:
    """Verify structured logger formats JSON records properly."""
    logger = setup_logging("INFO", structured=True)
    assert logger.name == "gaming_mcp"
    assert len(logger.handlers) == 1
    formatter = logger.handlers[0].formatter
    assert isinstance(formatter, StructuredFormatter)


def test_structured_formatter_record_fields() -> None:
    """Verify StructuredFormatter serializes extra attributes and exceptions."""
    import logging

    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg="test message with extra",
        args=(),
        exc_info=None,
    )
    record.adapter_id = "test_adapter"
    record.tool_name = "test_tool"
    record.latency_ms = 12.5

    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["level"] == "ERROR"
    assert parsed["message"] == "test message with extra"
    assert parsed["adapter_id"] == "test_adapter"
    assert parsed["tool_name"] == "test_tool"
    assert parsed["latency_ms"] == 12.5

    # Test exception formatting
    try:
        raise ValueError("synthetic failure")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()

    output_with_exc = formatter.format(record)
    parsed_exc = json.loads(output_with_exc)
    assert "exception" in parsed_exc
    assert "synthetic failure" in parsed_exc["exception"]


def test_unstructured_logger() -> None:
    """Verify setup_logging with structured=False creates a standard Formatter."""
    logger = setup_logging("DEBUG", structured=False)
    assert logger.level == 10
    formatter = logger.handlers[0].formatter
    assert not isinstance(formatter, StructuredFormatter)


@pytest.mark.asyncio
async def test_async_main(default_config: GamingMCPConfig) -> None:
    """Verify async_main executes without error."""
    from unittest.mock import AsyncMock, patch

    from gaming_mcp.__main__ import async_main

    with patch("gaming_mcp.server.GamingMCPServer.start", new_callable=AsyncMock) as mock_start:
        await async_main(default_config)
        mock_start.assert_awaited_once()
