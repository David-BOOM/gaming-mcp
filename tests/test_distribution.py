"""Automated tests for distribution configuration templates, documentation, and package metadata."""

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTION_DIR = REPO_ROOT / "distribution"
DOCS_DIR = REPO_ROOT / "docs"


def check_no_emojis(text: str) -> list[tuple[int, str, str]]:
    """Scan text for disallowed Unicode emoji code points.

    Returns list of (line_number, character, unicode_codepoint) infractions.
    """
    infractions: list[tuple[int, str, str]] = []
    for line_idx, line in enumerate(text.splitlines(), start=1):
        for char in line:
            cp = ord(char)
            # Unicode ranges for emojis and pictograms
            if (
                0x1F000 <= cp <= 0x1FFFF
                or 0x2600 <= cp <= 0x27BF
                or 0x2B50 <= cp <= 0x2B55
                or 0x2300 <= cp <= 0x23FF
                or 0x2B05 <= cp <= 0x2B07
                or 0x2934 <= cp <= 0x2935
                or 0x3297 <= cp <= 0x3299
                or 0xFE00 <= cp <= 0xFE0F
                or 0x1F900 <= cp <= 0x1F9FF
                or 0x1FA70 <= cp <= 0x1FAFF
            ):
                infractions.append((line_idx, char, f"U+{cp:04X}"))
    return infractions


def test_distribution_files_exist() -> None:
    """Verify all required distribution configuration templates exist."""
    assert DISTRIBUTION_DIR.is_dir(), f"Missing directory: {DISTRIBUTION_DIR}"

    required_files = [
        "claude_desktop_config.json",
        "cursor_config.json",
        "mcp_registry_entry.json",
    ]
    for filename in required_files:
        filepath = DISTRIBUTION_DIR / filename
        assert filepath.is_file(), f"Missing distribution template: {filepath}"
        assert filepath.stat().st_size > 0, f"Empty distribution template: {filepath}"


def test_claude_desktop_config_schema() -> None:
    """Validate Claude Desktop config template structure and MCP transport settings."""
    filepath = DISTRIBUTION_DIR / "claude_desktop_config.json"
    content = filepath.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(content)

    assert "mcpServers" in data, "claude_desktop_config.json missing 'mcpServers' root key"
    servers: dict[str, Any] = data["mcpServers"]
    assert len(servers) >= 2, "Expected at least stdio and sse server configurations"

    # Verify Stdio config
    assert "gaming-mcp" in servers, "Missing 'gaming-mcp' stdio server entry"
    stdio_server = servers["gaming-mcp"]
    assert "command" in stdio_server
    assert "args" in stdio_server
    assert isinstance(stdio_server["args"], list)
    assert any("gaming-mcp" in str(arg) for arg in stdio_server["args"])

    # Verify SSE config
    assert "gaming-mcp-sse" in servers, "Missing 'gaming-mcp-sse' server entry"
    sse_server = servers["gaming-mcp-sse"]
    assert "url" in sse_server
    assert sse_server["url"].startswith("http://")
    assert "/sse" in sse_server["url"]


def test_cursor_config_schema() -> None:
    """Validate Cursor MCP configuration template structure."""
    filepath = DISTRIBUTION_DIR / "cursor_config.json"
    content = filepath.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(content)

    assert "mcpServers" in data, "cursor_config.json missing 'mcpServers' root key"
    servers: dict[str, Any] = data["mcpServers"]
    assert "gaming-mcp" in servers, "Missing 'gaming-mcp' in Cursor config"

    server = servers["gaming-mcp"]
    assert "command" in server
    assert "args" in server
    assert isinstance(server["args"], list)
    assert any("gaming-mcp" in str(arg) for arg in server["args"])


def test_mcp_registry_entry_schema() -> None:
    """Validate official modelcontextprotocol/servers registry entry manifest."""
    filepath = DISTRIBUTION_DIR / "mcp_registry_entry.json"
    content = filepath.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(content)

    # Required top-level manifest keys
    expected_keys = [
        "name",
        "displayName",
        "description",
        "version",
        "license",
        "repository",
        "package",
        "transports",
        "capabilities",
        "adapters",
    ]
    for key in expected_keys:
        assert key in data, f"mcp_registry_entry.json missing required key: {key}"

    assert data["name"] == "gaming-mcp"
    assert data["license"] == "Apache-2.0"
    assert "stdio" in data["transports"]
    assert "sse" in data["transports"]

    # Validate capabilities flags
    caps: dict[str, bool] = data["capabilities"]
    assert caps.get("tools") is True
    assert caps.get("resources") is True
    assert caps.get("prompts") is True

    # Validate adapter list
    adapters = [a["id"] for a in data["adapters"] if isinstance(a, dict)]
    assert "computer_use" in adapters
    assert "minecraft" in adapters
    assert "retro" in adapters
    assert "gymnasium" in adapters


def test_diataxis_docs_suite_exists() -> None:
    """Verify complete Diataxis documentation suite exists with all 4 quadrants."""
    expected_docs = [
        DOCS_DIR / "tutorials" / "quickstart.md",
        DOCS_DIR / "how_to" / "configuration_guide.md",
        DOCS_DIR / "reference" / "tools_and_resources.md",
        DOCS_DIR / "explanation" / "pomdp_and_token_economics.md",
    ]
    for doc in expected_docs:
        assert doc.is_file(), f"Missing Diataxis documentation file: {doc}"
        text = doc.read_text(encoding="utf-8")
        assert len(text.strip()) > 500, f"Documentation file {doc} appears incomplete or too short"


def test_zero_emojis_in_distribution_and_docs() -> None:
    """Verify zero emoji infractions across all distribution configs and docs files."""
    scanned_files: list[Path] = []
    scanned_files.extend(DISTRIBUTION_DIR.rglob("*.json"))
    scanned_files.extend(DOCS_DIR.rglob("*.md"))

    assert len(scanned_files) >= 6, f"Expected at least 6 files, found {len(scanned_files)}"

    all_infractions: dict[str, list[tuple[int, str, str]]] = {}
    for file_path in scanned_files:
        text = file_path.read_text(encoding="utf-8")
        infractions = check_no_emojis(text)
        if infractions:
            all_infractions[str(file_path)] = infractions

    total_count = sum(len(v) for v in all_infractions.values())
    assert not all_infractions, (
        f"Found {total_count} emoji infractions: {all_infractions}"
    )


def test_pyproject_pep621_metadata() -> None:
    """Validate PEP 621 packaging metadata in pyproject.toml."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    assert pyproject_path.is_file(), "pyproject.toml not found"

    content = pyproject_path.read_text(encoding="utf-8")
    assert 'name = "gaming-mcp"' in content
    assert 'version = "0.1.0"' in content
    assert 'build-backend = "hatchling.build"' in content
    assert 'gaming-mcp = "gaming_mcp.__main__:main"' in content
