"""Unit tests for SkillManager: MCP tool execution, resource reading, and prompt rendering."""

import json
from typing import Any

import pytest

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry
from gaming_mcp.skills.manager import SkillManager
from gaming_mcp.skills.store import SkillStore


@pytest.fixture
def test_setup() -> tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager]:
    """Fixture providing initialized registries, in-memory store, and SkillManager."""
    tools = ToolRegistry()
    resources = ResourceRegistry()
    prompts = PromptRegistry()
    store = SkillStore(":memory:")
    cancellation = CancellationManager()

    manager = SkillManager(
        tool_registry=tools,
        resource_registry=resources,
        prompt_registry=prompts,
        store=store,
        cancellation_manager=cancellation,
    )
    return tools, resources, prompts, store, manager


def test_manager_registration(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify all 6 MCP tools, 2 resources, and 1 prompt are registered."""
    tools, resources, prompts, _, _ = test_setup

    tool_names = {t.name for t in tools.list_tools()}
    assert "skill_search" in tool_names
    assert "skill_register" in tool_names
    assert "skill_execute" in tool_names
    assert "skill_delete" in tool_names
    assert "skill_get" in tool_names
    assert "skill_list" in tool_names

    resource_uris = {r.uri for r in resources.list_resources()}
    assert "skills://registry" in resource_uris
    assert "skills://history" in resource_uris

    prompt_names = {p.name for p in prompts.list_prompts()}
    assert "skill_synthesis_playbook" in prompt_names


@pytest.mark.asyncio
async def test_tool_skill_register_and_get(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify registering a skill via MCP tool and retrieving its definition."""
    tools, _, _, _, _ = test_setup

    reg_payload = {
        "name": "craft_wooden_pickaxe",
        "description": "Craft wooden pickaxe using 3 wood planks and 2 sticks",
        "parameters": {
            "plank_type": {"type": "str", "default": "oak_planks"},
            "count": {"type": "int", "default": 1},
        },
        "steps": [
            {
                "tool_name": "craft_item",
                "arguments": {"recipe": "wooden_pickaxe", "material": "{plank_type}"},
                "description": "Craft tool at workbench",
            }
        ],
        "tags": ["crafting", "minecraft", "tools"],
    }

    res_reg = await tools.execute("skill_register", reg_payload)
    assert res_reg.get("isError") is False
    reg_data = json.loads(res_reg["content"][0]["text"])
    assert reg_data["status"] == "registered"
    assert reg_data["name"] == "craft_wooden_pickaxe"
    assert reg_data["step_count"] == 1

    # Retrieve definition via skill_get
    res_get = await tools.execute("skill_get", {"name": "craft_wooden_pickaxe"})
    assert res_get.get("isError") is False
    get_data = json.loads(res_get["content"][0]["text"])
    assert get_data["name"] == "craft_wooden_pickaxe"
    assert "plank_type" in get_data["parameters"]
    assert len(get_data["steps"]) == 1


@pytest.mark.asyncio
async def test_tool_skill_register_validation_errors(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify validation errors when registering with empty name or invalid steps."""
    tools, _, _, _, _ = test_setup

    # Empty name
    res1 = await tools.execute(
        "skill_register",
        {
            "name": "  ",
            "description": "invalid",
            "parameters": {},
            "steps": [{"tool_name": "t", "arguments": {}}],
            "tags": [],
        },
    )
    assert res1.get("isError") is True

    # Empty tool_name in step
    res2 = await tools.execute(
        "skill_register",
        {
            "name": "bad_step_skill",
            "description": "invalid step",
            "parameters": {},
            "steps": [{"tool_name": "", "arguments": {}}],
            "tags": [],
        },
    )
    assert res2.get("isError") is True
    assert "Invalid step schema" in res2["content"][0]["text"]


@pytest.mark.asyncio
async def test_tool_skill_list_and_filter(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify listing skills with and without tag filtering."""
    tools, _, _, _, _ = test_setup

    # Register 2 skills
    await tools.execute(
        "skill_register",
        {
            "name": "sword_slash",
            "description": "Basic combat attack",
            "parameters": {},
            "steps": [{"tool_name": "attack", "arguments": {}}],
            "tags": ["combat", "action"],
        },
    )
    await tools.execute(
        "skill_register",
        {
            "name": "smelt_iron",
            "description": "Smelt iron ore in furnace",
            "parameters": {},
            "steps": [{"tool_name": "furnace", "arguments": {}}],
            "tags": ["smelting", "utility"],
        },
    )

    # List all
    res_all = await tools.execute("skill_list", {})
    assert res_all.get("isError") is False
    all_data = json.loads(res_all["content"][0]["text"])
    assert all_data["count"] == 2

    # Filter by tag combat
    res_combat = await tools.execute("skill_list", {"tag": "combat"})
    assert res_combat.get("isError") is False
    combat_data = json.loads(res_combat["content"][0]["text"])
    assert combat_data["count"] == 1
    assert combat_data["skills"][0]["name"] == "sword_slash"


@pytest.mark.asyncio
async def test_tool_skill_search_semantic(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify semantic skill search ranks the most relevant skills highest."""
    tools, _, _, _, _ = test_setup

    await tools.execute(
        "skill_register",
        {
            "name": "mine_diamond_ore",
            "description": "Dig and extract diamond minerals from subterranean caves",
            "parameters": {},
            "steps": [{"tool_name": "dig", "arguments": {}}],
            "tags": ["mining", "diamonds"],
        },
    )
    await tools.execute(
        "skill_register",
        {
            "name": "swim_ocean",
            "description": "Navigate and dive through water biomes",
            "parameters": {},
            "steps": [{"tool_name": "swim", "arguments": {}}],
            "tags": ["exploration", "water"],
        },
    )

    res_search = await tools.execute(
        "skill_search",
        {"query": "extract diamond ores underground", "top_k": 2},
    )
    assert res_search.get("isError") is False
    search_data = json.loads(res_search["content"][0]["text"])
    assert search_data["count"] >= 1
    top_result = search_data["results"][0]
    assert top_result["name"] == "mine_diamond_ore"
    assert top_result["similarity"] > 0.1


@pytest.mark.asyncio
async def test_tool_skill_execute_success(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify skill execution via MCP tool binding parameters and reporting latency."""
    tools, _, _, _, _ = test_setup
    executed_args: dict[str, Any] = {}

    async def _mock_action(args: dict[str, Any]) -> str:
        nonlocal executed_args
        executed_args.update(args)
        return "action_ok"

    tools.register("mock_action", _mock_action)

    await tools.execute(
        "skill_register",
        {
            "name": "harvest_wood",
            "description": "Chop down tree logs",
            "parameters": {"block_type": {"type": "str", "default": "oak_log"}},
            "steps": [
                {
                    "tool_name": "mock_action",
                    "arguments": {"target": "{block_type}", "hits": 5},
                }
            ],
            "tags": ["woodcutting"],
        },
    )

    exec_res = await tools.execute(
        "skill_execute",
        {"name": "harvest_wood", "parameters": {"block_type": "birch_log"}},
    )
    assert exec_res.get("isError") is False
    exec_data = json.loads(exec_res["content"][0]["text"])
    assert exec_data["status"] == "success"
    assert exec_data["skill_name"] == "harvest_wood"
    assert exec_data["step_count"] == 1
    assert executed_args == {"target": "birch_log", "hits": 5}


@pytest.mark.asyncio
async def test_tool_skill_execute_not_found(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify executing non-existent skill returns error."""
    tools, _, _, _, _ = test_setup
    res = await tools.execute("skill_execute", {"name": "non_existent_skill"})
    assert res.get("isError") is True
    assert "not found" in res["content"][0]["text"]


@pytest.mark.asyncio
async def test_tool_skill_delete(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify deleting registered skills and handling non-existent deletes."""
    tools, _, _, _, _ = test_setup

    await tools.execute(
        "skill_register",
        {
            "name": "temporary_skill",
            "description": "To be deleted",
            "parameters": {},
            "steps": [{"tool_name": "noop", "arguments": {}}],
            "tags": [],
        },
    )

    del_res = await tools.execute("skill_delete", {"name": "temporary_skill"})
    assert del_res.get("isError") is False
    assert json.loads(del_res["content"][0]["text"])["status"] == "deleted"

    # Delete again -> not found error
    del_again = await tools.execute("skill_delete", {"name": "temporary_skill"})
    assert del_again.get("isError") is True


@pytest.mark.asyncio
async def test_resources_reading(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify reading skills://registry and skills://history resources."""
    tools, resources, _, _, _ = test_setup

    # Register and execute a skill
    async def _dummy() -> str:
        return "ok"

    tools.register("noop_tool", _dummy)

    await tools.execute(
        "skill_register",
        {
            "name": "registry_test_skill",
            "description": "Skill for registry testing",
            "parameters": {},
            "steps": [{"tool_name": "noop_tool", "arguments": {}}],
            "tags": ["testing"],
        },
    )
    await tools.execute("skill_execute", {"name": "registry_test_skill"})

    # Read skills://registry
    res_reg = await resources.read("skills://registry")
    assert res_reg.get("isError") is None or res_reg.get("isError") is False
    reg_content = json.loads(res_reg["contents"][0]["text"])
    assert "stats" in reg_content
    assert reg_content["stats"]["total_skills"] == 1
    assert len(reg_content["skills"]) == 1
    assert reg_content["skills"][0]["name"] == "registry_test_skill"

    # Read skills://history
    res_hist = await resources.read("skills://history")
    assert res_hist.get("isError") is None or res_hist.get("isError") is False
    hist_content = json.loads(res_hist["contents"][0]["text"])
    assert "history" in hist_content
    assert len(hist_content["history"]) == 1
    assert hist_content["history"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_prompt_skill_synthesis_playbook(
    test_setup: tuple[ToolRegistry, ResourceRegistry, PromptRegistry, SkillStore, SkillManager],
) -> None:
    """Verify prompt rendering for skill synthesis playbook with default and custom arguments."""
    _, _, prompts, _, _ = test_setup

    # Default arguments
    rendered_default = await prompts.render("skill_synthesis_playbook")
    assert len(rendered_default) == 1
    msg_default = rendered_default[0]
    assert msg_default["role"] == "user"
    assert "Voyager Skill Synthesis & Self-Repair Playbook" in msg_default["content"]["text"]
    assert "skill_search" in msg_default["content"]["text"]
    assert "skill_register" in msg_default["content"]["text"]
    assert "skill_execute" in msg_default["content"]["text"]

    # Custom arguments
    rendered_custom = await prompts.render(
        "skill_synthesis_playbook",
        {"task_domain": "minecraft", "target_goal": "craft a diamond sword"},
    )
    assert len(rendered_custom) == 1
    msg_custom = rendered_custom[0]
    assert "MINECRAFT" in msg_custom["content"]["text"]
    assert "craft a diamond sword" in msg_custom["content"]["text"]
