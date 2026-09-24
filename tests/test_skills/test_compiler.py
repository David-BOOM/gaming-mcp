"""Unit tests for MacroCompiler: templating, type coercion, validation, and error handling."""

import pytest

from gaming_mcp.core.registries import ToolRegistry
from gaming_mcp.skills.compiler import (
    InvalidStepSchemaError,
    MacroCompilationError,
    MacroCompiler,
    MissingParameterError,
    ParameterTypeError,
)
from gaming_mcp.skills.models import (
    MacroStep,
    ParameterDefinition,
    SkillDefinition,
)


def test_compiler_initialization() -> None:
    """Verify compiler initializes with default or custom strictness."""
    compiler_lenient = MacroCompiler()
    assert compiler_lenient._strict_tools is False

    compiler_strict = MacroCompiler(strict_tools=True)
    assert compiler_strict._strict_tools is True


def test_type_coercion_primitives() -> None:
    """Verify type coercion for integer, float, string, and boolean."""
    compiler = MacroCompiler()

    # Integers
    assert compiler.coerce_type("42", "int", "count") == 42
    assert compiler.coerce_type(100.0, "int", "count") == 100
    assert compiler.coerce_type(17, "integer", "count") == 17

    # Floats
    assert compiler.coerce_type("3.1415", "float", "coord") == pytest.approx(3.1415)
    assert compiler.coerce_type(5, "number", "coord") == 5.0

    # Booleans
    assert compiler.coerce_type("true", "bool", "flag") is True
    assert compiler.coerce_type("1", "boolean", "flag") is True
    assert compiler.coerce_type("yes", "bool", "flag") is True
    assert compiler.coerce_type("on", "bool", "flag") is True
    assert compiler.coerce_type("false", "bool", "flag") is False
    assert compiler.coerce_type("0", "boolean", "flag") is False
    assert compiler.coerce_type("no", "bool", "flag") is False
    assert compiler.coerce_type("off", "bool", "flag") is False
    assert compiler.coerce_type(True, "bool", "flag") is True

    # Strings
    assert compiler.coerce_type(12345, "str", "id") == "12345"
    assert compiler.coerce_type(True, "string", "id") == "True"


def test_type_coercion_complex_structures() -> None:
    """Verify list and dict coercion from strings and native objects."""
    compiler = MacroCompiler()

    # Lists
    assert compiler.coerce_type("[1, 2, 3]", "list", "items") == [1, 2, 3]
    assert compiler.coerce_type(["a", "b"], "list", "items") == ["a", "b"]

    # Dictionaries
    assert compiler.coerce_type('{"x": 10, "y": 20}', "dict", "coords") == {"x": 10, "y": 20}
    assert compiler.coerce_type({"k": "v"}, "dict", "coords") == {"k": "v"}


def test_type_coercion_invalid_values() -> None:
    """Verify appropriate ParameterTypeError on invalid type conversions."""
    compiler = MacroCompiler()

    with pytest.raises(ParameterTypeError, match="expected integer"):
        compiler.coerce_type("not_a_number", "int", "count")

    with pytest.raises(ParameterTypeError, match="expected float"):
        compiler.coerce_type("abc", "float", "velocity")

    with pytest.raises(ParameterTypeError, match="cannot coerce string"):
        compiler.coerce_type("maybe", "bool", "enabled")


def test_parameter_resolution_and_defaults() -> None:
    """Verify resolution applies provided values, defaults, or raises on missing required."""
    compiler = MacroCompiler()
    defs = {
        "item": ParameterDefinition(type="str", required=True),
        "count": ParameterDefinition(type="int", default=1, required=False),
        "fast": ParameterDefinition(type="bool", default=False, required=False),
    }

    # Case A: All provided
    res1 = compiler.validate_and_resolve_parameters(
        defs, {"item": "iron_ore", "count": "5", "fast": "true"}
    )
    assert res1 == {"item": "iron_ore", "count": 5, "fast": True}

    # Case B: Defaults applied
    res2 = compiler.validate_and_resolve_parameters(defs, {"item": "gold_ore"})
    assert res2 == {"item": "gold_ore", "count": 1, "fast": False}

    # Case C: Missing required parameter
    with pytest.raises(MissingParameterError, match="Missing required parameter 'item'"):
        compiler.validate_and_resolve_parameters(defs, {"count": 3})


def test_parameter_resolution_raw_dicts_and_passthrough() -> None:
    """Verify resolution works with raw dict schemas and extra passthrough arguments."""
    compiler = MacroCompiler()
    raw_defs = {
        "x": {"type": "float", "default": 0.0},
        "name": "str",
    }
    res = compiler.validate_and_resolve_parameters(
        raw_defs, {"name": "player1", "extra_arg": 999}
    )
    assert res["x"] == 0.0
    assert res["name"] == "player1"
    assert res["extra_arg"] == 999


def test_interpolate_value_exact_match() -> None:
    """Verify single exact variable match '{var}' preserves coerced typed value."""
    compiler = MacroCompiler()
    params = {"target": "diamond_block", "amount": 64, "ratio": 0.75, "active": True}

    assert compiler.interpolate_value("{target}", params) == "diamond_block"
    assert compiler.interpolate_value("{amount}", params) == 64
    assert compiler.interpolate_value("{ratio}", params) == 0.75
    assert compiler.interpolate_value("{active}", params) is True


def test_interpolate_value_embedded_strings() -> None:
    """Verify embedded variables within larger strings are interpolated properly."""
    compiler = MacroCompiler()
    params = {"hero": "Steve", "action": "mining", "target": "obsidian"}

    template = "Player {hero} is currently {action} {target} blocks."
    result = compiler.interpolate_value(template, params)
    assert result == "Player Steve is currently mining obsidian blocks."


def test_interpolate_value_nested_structures() -> None:
    """Verify deep traversal of dicts and lists during interpolation."""
    compiler = MacroCompiler()
    params = {"x_pos": 100, "y_pos": 64, "z_pos": -250, "item": "torch"}

    raw_args = {
        "command": "place_{item}",
        "coordinates": {"x": "{x_pos}", "y": "{y_pos}", "z": "{z_pos}"},
        "flags": ["drop_on_break", "burn_{item}"],
    }

    interpolated = compiler.interpolate_value(raw_args, params)
    assert interpolated["command"] == "place_torch"
    assert interpolated["coordinates"] == {"x": 100, "y": 64, "z": -250}
    assert interpolated["flags"] == ["drop_on_break", "burn_torch"]


def test_interpolate_value_undefined_variable() -> None:
    """Verify error raised when step references an undefined parameter variable."""
    compiler = MacroCompiler()
    with pytest.raises(MacroCompilationError, match="undefined parameter variable 'missing_var'"):
        compiler.interpolate_value("{missing_var}", {"other_var": 1})

    with pytest.raises(MacroCompilationError, match="undefined parameter variable 'not_found'"):
        compiler.interpolate_value("prefix {not_found} suffix", {})


def test_validate_step_schema_empty_tool_name() -> None:
    """Verify InvalidStepSchemaError when tool_name is empty or whitespace."""
    compiler = MacroCompiler()
    invalid_step = MacroStep(tool_name="   ", arguments={})
    with pytest.raises(InvalidStepSchemaError, match="empty or invalid tool_name"):
        compiler.validate_step_schema(invalid_step, step_index=0)


def test_validate_step_schema_non_dict_arguments() -> None:
    """Verify InvalidStepSchemaError when step arguments are not a dictionary."""
    compiler = MacroCompiler()
    # Construct invalid step with invalid arguments type directly
    step = MacroStep(tool_name="test_tool")
    step.arguments = "not_a_dict"  # type: ignore[assignment]
    with pytest.raises(InvalidStepSchemaError, match="must be a dictionary"):
        compiler.validate_step_schema(step, step_index=1)


def test_validate_step_schema_strict_registry() -> None:
    """Verify strict tool registry verification catches unregistered tools."""
    registry = ToolRegistry()

    async def _dummy_handler() -> str:
        return "ok"

    registry.register(name="known_tool", handler=_dummy_handler)

    compiler_strict = MacroCompiler(strict_tools=True)

    # Known tool passes
    step_ok = MacroStep(tool_name="known_tool", arguments={})
    compiler_strict.validate_step_schema(step_ok, tool_registry=registry)

    # Unknown tool fails
    step_unknown = MacroStep(tool_name="unknown_tool", arguments={})
    with pytest.raises(InvalidStepSchemaError, match="references unregistered tool 'unknown_tool'"):
        compiler_strict.validate_step_schema(step_unknown, tool_registry=registry)


def test_compile_skill_complete_flow() -> None:
    """Verify full skill compilation with parameter resolution and compensation steps."""
    compiler = MacroCompiler()

    compensation = MacroStep(
        tool_name="drop_item",
        arguments={"item_name": "{item}"},
        description="Revert held item",
    )
    step1 = MacroStep(
        tool_name="equip_item",
        arguments={"item_name": "{item}", "slot": "{slot_num}"},
        description="Equip target item",
        compensation_steps=[compensation],
    )
    step2 = MacroStep(
        tool_name="use_item",
        arguments={"duration": "{use_seconds}"},
        description="Use target item",
    )

    skill = SkillDefinition(
        name="equip_and_use",
        description="Equip item in slot and use it",
        parameters={
            "item": ParameterDefinition(type="str"),
            "slot_num": ParameterDefinition(type="int", default=1),
            "use_seconds": ParameterDefinition(type="float", default=2.5),
        },
        steps=[step1, step2],
    )

    compiled = compiler.compile_skill(
        skill=skill,
        parameters={"item": "golden_apple", "slot_num": "3"},
    )

    assert len(compiled) == 2
    # Step 1
    assert compiled[0].tool_name == "equip_item"
    assert compiled[0].arguments == {"item_name": "golden_apple", "slot": 3}
    assert len(compiled[0].compensation_steps) == 1
    assert compiled[0].compensation_steps[0].arguments == {"item_name": "golden_apple"}

    # Step 2
    assert compiled[1].tool_name == "use_item"
    assert compiled[1].arguments == {"duration": 2.5}
