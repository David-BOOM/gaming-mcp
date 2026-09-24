"""Compiler and parameter templating engine for composite macro skills."""

import json
import re
from typing import Any

from gaming_mcp.core.exceptions import GamingMCPError
from gaming_mcp.core.registries import ToolRegistry
from gaming_mcp.skills.models import (
    MacroStep,
    ParameterDefinition,
    SkillDefinition,
)


class MacroCompilationError(GamingMCPError):
    """Base exception for macro compilation failures."""

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, error_code=-32602, data=data)


class MissingParameterError(MacroCompilationError):
    """Raised when a required macro parameter is not provided."""


class ParameterTypeError(MacroCompilationError):
    """Raised when a parameter value cannot be coerced to the expected schema type."""


class InvalidStepSchemaError(MacroCompilationError):
    """Raised when a step specification violates the required schema."""


class MacroCompiler:
    """Compiles and validates macro parameter templates into concrete tool invocations."""

    # Matches parameter interpolation patterns: {param_name}
    _TEMPLATE_REGEX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

    def __init__(self, strict_tools: bool = False) -> None:
        """Initialize the compiler.

        Args:
            strict_tools: If True, tool_name must exist in ToolRegistry during compilation.
        """
        self._strict_tools = strict_tools

    def coerce_type(self, value: Any, target_type: str, param_name: str) -> Any:
        """Coerce a value to the specified parameter type with strict validation."""
        norm_type = target_type.lower().strip()

        if norm_type in ("str", "string"):
            return str(value)

        if norm_type in ("int", "integer"):
            try:
                if isinstance(value, float) and value.is_integer():
                    return int(value)
                return int(value)
            except (ValueError, TypeError) as exc:
                v_type = type(value).__name__
                raise ParameterTypeError(
                    f"Parameter '{param_name}' expected integer, got {v_type} ({value!r})"
                ) from exc

        if norm_type in ("float", "number"):
            try:
                return float(value)
            except (ValueError, TypeError) as exc:
                v_type = type(value).__name__
                raise ParameterTypeError(
                    f"Parameter '{param_name}' expected float, got {v_type} ({value!r})"
                ) from exc

        if norm_type in ("bool", "boolean"):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                v_lower = value.lower().strip()
                if v_lower in ("true", "1", "yes", "on"):
                    return True
                if v_lower in ("false", "0", "no", "off"):
                    return False
                raise ParameterTypeError(
                    f"Parameter '{param_name}' cannot coerce string {value!r} to boolean"
                )
            return bool(value)

        if norm_type == "list":
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
            try:
                return list(value)
            except Exception as exc:
                raise ParameterTypeError(
                    f"Parameter '{param_name}' expected list, got {type(value).__name__}"
                ) from exc

        if norm_type == "dict":
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
            try:
                return dict(value)
            except Exception as exc:
                raise ParameterTypeError(
                    f"Parameter '{param_name}' expected dict, got {type(value).__name__}"
                ) from exc

        # Default fallback for 'any' or unrecognized types
        return value

    def validate_and_resolve_parameters(
        self,
        parameter_defs: dict[str, Any],
        provided: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate provided arguments against parameter definitions and apply defaults."""
        resolved: dict[str, Any] = {}

        for param_name, raw_def in parameter_defs.items():
            if isinstance(raw_def, ParameterDefinition):
                p_type = raw_def.type
                p_default = raw_def.default
                p_req = raw_def.required
            elif isinstance(raw_def, dict):
                p_type = str(raw_def.get("type", "str"))
                p_default = raw_def.get("default", None)
                p_req = bool(raw_def.get("required", True))
            elif isinstance(raw_def, str):
                p_type = raw_def
                p_default = None
                p_req = True
            else:
                p_type = "str"
                p_default = None
                p_req = True

            if param_name in provided:
                raw_val = provided[param_name]
                coerced = self.coerce_type(raw_val, p_type, param_name)
                resolved[param_name] = coerced
            elif p_default is not None:
                resolved[param_name] = p_default
            elif p_req:
                raise MissingParameterError(
                    f"Missing required parameter '{param_name}' for macro execution"
                )
            else:
                resolved[param_name] = None

        # Pass through extra parameters not in explicit definitions
        for key, val in provided.items():
            if key not in resolved:
                resolved[key] = val

        return resolved

    def interpolate_value(
        self,
        value: Any,
        resolved_params: dict[str, Any],
    ) -> Any:
        """Recursively interpolate parameter variables into an argument value."""
        if isinstance(value, str):
            # Check for exact single variable match: "{param}"
            exact_match = re.fullmatch(self._TEMPLATE_REGEX, value.strip())
            if exact_match:
                param_name = exact_match.group(1)
                if param_name not in resolved_params:
                    raise MacroCompilationError(
                        f"Step references undefined parameter variable '{param_name}'"
                    )
                return resolved_params[param_name]

            # Check for embedded variables within string: "prefix {param} suffix"
            matches = list(self._TEMPLATE_REGEX.finditer(value))
            if not matches:
                return value

            result = value
            for match in matches:
                param_name = match.group(1)
                if param_name not in resolved_params:
                    raise MacroCompilationError(
                        f"Step references undefined parameter variable '{param_name}'"
                    )
                param_val = resolved_params[param_name]
                result = result.replace(f"{{{param_name}}}", str(param_val))
            return result

        if isinstance(value, dict):
            return {k: self.interpolate_value(v, resolved_params) for k, v in value.items()}

        if isinstance(value, list):
            return [self.interpolate_value(elem, resolved_params) for elem in value]

        return value

    def validate_step_schema(
        self,
        step: MacroStep,
        step_index: int = 0,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        """Validate step schema consistency and optional tool registry presence."""
        if not step.tool_name or not step.tool_name.strip():
            raise InvalidStepSchemaError(f"Step {step_index} has an empty or invalid tool_name")

        if not isinstance(step.arguments, dict):
            arg_type = type(step.arguments).__name__
            raise InvalidStepSchemaError(
                f"Step {step_index} arguments must be a dictionary, got {arg_type}"
            )

        if (
            self._strict_tools
            and tool_registry is not None
            and not tool_registry.get(step.tool_name)
        ):
            raise InvalidStepSchemaError(
                f"Step {step_index} references unregistered tool '{step.tool_name}'"
            )

        # Recursively validate compensation steps
        for comp_idx, comp_step in enumerate(step.compensation_steps):
            self.validate_step_schema(
                comp_step,
                step_index=comp_idx,
                tool_registry=tool_registry,
            )

    def compile_step(
        self,
        step: MacroStep,
        resolved_params: dict[str, Any],
        step_index: int = 0,
        tool_registry: ToolRegistry | None = None,
    ) -> MacroStep:
        """Compile a single step by interpolating parameters and validating schema."""
        self.validate_step_schema(step, step_index, tool_registry)

        compiled_args = self.interpolate_value(step.arguments, resolved_params)
        if not isinstance(compiled_args, dict):
            c_type = type(compiled_args).__name__
            raise MacroCompilationError(
                f"Compiled step arguments must evaluate to a dictionary, got {c_type}"
            )

        compiled_compensation: list[MacroStep] = [
            self.compile_step(
                cs,
                resolved_params,
                step_index=i,
                tool_registry=tool_registry,
            )
            for i, cs in enumerate(step.compensation_steps)
        ]

        return MacroStep(
            tool_name=step.tool_name,
            arguments=compiled_args,
            description=step.description,
            max_retries=step.max_retries,
            retry_delay_s=step.retry_delay_s,
            compensation_steps=compiled_compensation,
            on_error=step.on_error,
        )

    def compile_skill(
        self,
        skill: SkillDefinition,
        parameters: dict[str, Any],
        tool_registry: ToolRegistry | None = None,
    ) -> list[MacroStep]:
        """Compile all steps in a skill definition using the provided parameters.

        Args:
            skill: The SkillDefinition containing parameter schemas and macro steps.
            parameters: Raw invocation parameters supplied by the client.
            tool_registry: Optional ToolRegistry for strict schema verification.

        Returns:
            List of compiled MacroSteps with concrete argument values ready for execution.
        """
        resolved_params = self.validate_and_resolve_parameters(skill.parameters, parameters)

        compiled_steps: list[MacroStep] = []
        for idx, step in enumerate(skill.steps):
            compiled = self.compile_step(
                step,
                resolved_params,
                step_index=idx,
                tool_registry=tool_registry,
            )
            compiled_steps.append(compiled)

        return compiled_steps
