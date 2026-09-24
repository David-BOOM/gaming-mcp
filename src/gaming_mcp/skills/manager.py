"""High-level skill manager coordinating store, embeddings, compiler, and executor."""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from gaming_mcp.core.cancellation import CancellationManager
from gaming_mcp.core.registries import PromptRegistry, ResourceRegistry, ToolRegistry
from gaming_mcp.skills.compiler import MacroCompiler
from gaming_mcp.skills.embeddings import LocalEmbeddingEngine
from gaming_mcp.skills.models import (
    MacroStep,
    ParameterDefinition,
    SkillDefinition,
)
from gaming_mcp.skills.repair import MacroExecutor
from gaming_mcp.skills.store import SkillStore

logger = logging.getLogger("gaming_mcp.skills.manager")


# ---------------------------------------------------------------------------
# MCP Tool Input Models
# ---------------------------------------------------------------------------


class SkillSearchInput(BaseModel):
    """Input parameters for searching skills by semantic similarity."""

    query: str = Field(
        description="Natural language query describing desired gameplay objective or action.",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of relevant skills to return.",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Optional list of tags to restrict the search candidates.",
    )


class SkillRegisterInput(BaseModel):
    """Input parameters for registering a new composite macro skill."""

    name: str = Field(
        description="Unique identifier for the macro skill (e.g. 'craft_wooden_pickaxe').",
    )
    description: str = Field(
        description="Comprehensive natural language description of what the skill accomplishes.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Map of parameter names to type definitions or parameter schema objects.",
    )
    steps: list[dict[str, Any]] = Field(
        description="Sequential list of atomic tool execution steps.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Taxonomy tags describing the domain, game, and action category.",
    )


class SkillExecuteInput(BaseModel):
    """Input parameters for executing a composite macro skill."""

    name: str = Field(
        description="Name of the registered skill to execute.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Dictionary of argument values matching the skill's parameter template.",
    )
    auto_repair: bool = Field(
        default=True,
        description="Whether to activate autonomous failure recovery, retries, and compensation.",
    )


class SkillDeleteInput(BaseModel):
    """Input parameters for deleting a registered skill."""

    name: str = Field(
        description="Name of the skill to delete from the library.",
    )


class SkillGetInput(BaseModel):
    """Input parameters for retrieving full details of a specific skill."""

    name: str = Field(
        description="Name of the skill to retrieve.",
    )


class SkillListInput(BaseModel):
    """Input parameters for listing skills with optional tag filtering."""

    tag: str | None = Field(
        default=None,
        description="Optional tag to filter returned skills.",
    )


# ---------------------------------------------------------------------------
# SkillManager Coordinator
# ---------------------------------------------------------------------------


class SkillManager:
    """High-level coordinator connecting store, embeddings, compiler, and executor."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        resource_registry: ResourceRegistry | None = None,
        prompt_registry: PromptRegistry | None = None,
        store: SkillStore | None = None,
        embedding_engine: LocalEmbeddingEngine | None = None,
        compiler: MacroCompiler | None = None,
        executor: MacroExecutor | None = None,
        cancellation_manager: CancellationManager | None = None,
    ) -> None:
        """Initialize the SkillManager and bind MCP primitives.

        Args:
            tool_registry: Server ToolRegistry to register skill tools and execute steps against.
            resource_registry: Optional ResourceRegistry for reactive skill memory resources.
            prompt_registry: Optional PromptRegistry for synthesis playbooks.
            store: Optional SkillStore instance (defaults to in-memory SQLite).
            embedding_engine: Optional LocalEmbeddingEngine instance.
            compiler: Optional MacroCompiler instance.
            executor: Optional MacroExecutor instance.
            cancellation_manager: Optional CancellationManager for token monitoring.
        """
        self.tool_registry = tool_registry
        self.resource_registry = resource_registry
        self.prompt_registry = prompt_registry
        self.cancellation_manager = cancellation_manager

        self.store = store or SkillStore(db_path=":memory:")
        self.embedding_engine = embedding_engine or LocalEmbeddingEngine()
        self.compiler = compiler or MacroCompiler()
        self.executor = executor or MacroExecutor(
            tool_registry=self.tool_registry,
            store=self.store,
            compiler=self.compiler,
        )

        self._register_tools()
        if self.resource_registry is not None:
            self._register_resources()
        if self.prompt_registry is not None:
            self._register_prompts()

    # -----------------------------------------------------------------------
    # Tool Registration
    # -----------------------------------------------------------------------

    def _register_tools(self) -> None:
        """Register MCP skill management tools on the tool registry."""
        self.tool_registry.register(
            name="skill_search",
            handler=self._handle_skill_search,
            description=(
                "Search the Voyager skill library for relevant macros using "
                "semantic vector similarity."
            ),
            input_model=SkillSearchInput,
        )
        self.tool_registry.register(
            name="skill_register",
            handler=self._handle_skill_register,
            description="Register a new reusable composite macro skill with parameter templates.",
            input_model=SkillRegisterInput,
        )
        self.tool_registry.register(
            name="skill_execute",
            handler=self._handle_skill_execute,
            description="Execute a registered composite skill with parameter binding.",
            input_model=SkillExecuteInput,
        )
        self.tool_registry.register(
            name="skill_delete",
            handler=self._handle_skill_delete,
            description="Delete a composite skill from the persistent skill library.",
            input_model=SkillDeleteInput,
        )
        self.tool_registry.register(
            name="skill_get",
            handler=self._handle_skill_get,
            description="Retrieve specification and parameter schema of a registered skill.",
            input_model=SkillGetInput,
        )
        self.tool_registry.register(
            name="skill_list",
            handler=self._handle_skill_list,
            description="List registered skills in the library with optional tag filtering.",
            input_model=SkillListInput,
        )

    # -----------------------------------------------------------------------
    # Resource Registration
    # -----------------------------------------------------------------------

    def _register_resources(self) -> None:
        """Register MCP reactive skill resources on the resource registry."""
        if self.resource_registry is None:
            return

        async def _read_registry_resource() -> dict[str, Any]:
            skills = self.store.list_skills()
            stats = self.store.get_stats()
            return {
                "stats": stats,
                "skills": [s.model_dump(exclude={"embedding"}) for s in skills],
            }

        async def _read_history_resource() -> dict[str, Any]:
            records = self.store.get_history(limit=50)
            return {
                "history": [r.model_dump() for r in records],
            }

        self.resource_registry.register(
            uri="skills://registry",
            reader=_read_registry_resource,
            name="Skill Registry",
            description=(
                "Catalog of registered composite macro skills and performance metrics."
            ),
            mime_type="application/json",
        )
        self.resource_registry.register(
            uri="skills://history",
            reader=_read_history_resource,
            name="Macro Execution History",
            description=(
                "Log of recent macro executions with step durations and diagnostic traces."
            ),
            mime_type="application/json",
        )

    # -----------------------------------------------------------------------
    # Prompt Registration
    # -----------------------------------------------------------------------

    def _register_prompts(self) -> None:
        """Register MCP contextual synthesis playbook prompt."""
        if self.prompt_registry is None:
            return

        async def _generate_synthesis_playbook(
            task_domain: str = "general", target_goal: str = ""
        ) -> list[dict[str, Any]]:
            goal_desc = target_goal or "Autonomous Macro Composition"
            guide_lines = [
                f"Voyager Skill Synthesis & Self-Repair Playbook ({task_domain.upper()})",
                f"Target Goal: {goal_desc}\n",
                "1. Skill Discovery:",
                "   - Before attempting multi-step routines, call skill_search(query)",
                "     to check if a verified macro already exists in the library.\n",
                "2. Parameter Abstraction:",
                "   - Abstract dynamic values into parameter templates: '{target}', '{count}'.",
                "   - Explicitly specify parameter types (str, int, float, bool) and defaults.\n",
                "3. Robust Step Construction:",
                "   - Deconstruct the goal into atomic MCP tool steps.",
                "   - Define max_retries and retry_delay_s for transient timing delays.",
                "   - Define fallback compensation_steps to reverse partial changes on failure.\n",
                "4. Registration & Verification:",
                "   - Register skill via skill_register(name, description, parameters, steps).",
                "   - Test skill with skill_execute(name, parameters, auto_repair=True).",
                "   - Inspect execution traces in skills://history to verify stability.\n",
                "5. Autonomous Self-Repair:",
                "   - When skill_execute returns status 'failed', inspect the diagnosis.",
                "   - Update step schemas or compensation steps to resolve edge cases.",
            ]
            guide_text = "\n".join(guide_lines)
            return [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": guide_text,
                    },
                }
            ]

        self.prompt_registry.register(
            name="skill_synthesis_playbook",
            generator=_generate_synthesis_playbook,
            description="Playbook instructing agents on synthesizing and repairing skills.",
            arguments=[
                {
                    "name": "task_domain",
                    "description": "Domain of interest (e.g. 'minecraft', 'retro').",
                    "required": False,
                },
                {
                    "name": "target_goal",
                    "description": "Specific gameplay objective or task to synthesize.",
                    "required": False,
                },
            ],
        )

    # -----------------------------------------------------------------------
    # Tool Handlers
    # -----------------------------------------------------------------------

    async def _handle_skill_search(
        self,
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search the skill library by semantic embedding similarity."""
        query_vec = self.embedding_engine.embed(query)
        all_skills = self.store.list_skills()

        # Filter by tags if provided
        if tags:
            filter_tags_lower = {t.lower().strip() for t in tags}
            candidates = [
                s for s in all_skills if any(t.lower() in filter_tags_lower for t in s.tags)
            ]
        else:
            candidates = all_skills

        if not candidates:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"results": [], "count": 0}),
                    }
                ]
            }

        # Build candidate vector list, computing embedding if missing
        vector_candidates: list[tuple[str, list[float]]] = []
        skill_map: dict[str, SkillDefinition] = {}

        for skill in candidates:
            skill_map[skill.name] = skill
            if skill.embedding is None:
                text_to_embed = f"{skill.name} {skill.description} {' '.join(skill.tags)}"
                skill.embedding = self.embedding_engine.embed(text_to_embed)
                self.store.save_skill(skill)
            vector_candidates.append((skill.name, skill.embedding))

        ranked = self.embedding_engine.rank_candidates(
            query_vector=query_vec,
            candidates=vector_candidates,
            top_k=top_k,
        )

        results: list[dict[str, Any]] = []
        for name, score in ranked:
            s = skill_map[name]
            results.append(
                {
                    "name": s.name,
                    "description": s.description,
                    "similarity": round(score, 4),
                    "tags": s.tags,
                    "success_count": s.success_count,
                    "failure_count": s.failure_count,
                    "step_count": len(s.steps),
                    "parameters": {k: v.model_dump() for k, v in s.parameters.items()},
                }
            )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"results": results, "count": len(results)}, indent=2),
                }
            ]
        }

    async def _handle_skill_register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        steps: list[dict[str, Any]],
        tags: list[str],
    ) -> dict[str, Any]:
        """Register a new composite macro skill."""
        if not name or not name.strip():
            return {
                "isError": True,
                "error_code": -32602,
                "content": [{"type": "text", "text": "Skill name cannot be empty."}],
            }

        # Parse and normalize parameters
        parsed_parameters: dict[str, ParameterDefinition] = {}
        for p_name, p_val in parameters.items():
            if isinstance(p_val, str):
                parsed_parameters[p_name] = ParameterDefinition(type=p_val)
            elif isinstance(p_val, dict):
                parsed_parameters[p_name] = ParameterDefinition.model_validate(p_val)
            elif isinstance(p_val, ParameterDefinition):
                parsed_parameters[p_name] = p_val
            else:
                return {
                    "isError": True,
                    "error_code": -32602,
                    "content": [
                        {
                            "type": "text",
                            "text": f"Invalid parameter definition for '{p_name}': {p_val!r}",
                        }
                    ],
                }

        # Parse and validate steps
        parsed_steps: list[MacroStep] = []
        for idx, step_dict in enumerate(steps):
            try:
                macro_step = MacroStep.model_validate(step_dict)
                self.compiler.validate_step_schema(
                    macro_step, step_index=idx, tool_registry=self.tool_registry
                )
                parsed_steps.append(macro_step)
            except Exception as exc:
                return {
                    "isError": True,
                    "error_code": -32602,
                    "content": [
                        {
                            "type": "text",
                            "text": f"Invalid step schema at index {idx}: {exc}",
                        }
                    ],
                }

        # Compute semantic embedding
        embed_text = f"{name} {description} {' '.join(tags)}"
        embedding = self.embedding_engine.embed(embed_text)

        skill = SkillDefinition(
            name=name,
            description=description,
            parameters=parsed_parameters,
            steps=parsed_steps,
            tags=tags,
            embedding=embedding,
        )

        self.store.save_skill(skill)
        logger.info("Registered skill '%s' with %d steps", name, len(parsed_steps))

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "registered",
                            "id": skill.id,
                            "name": skill.name,
                            "step_count": len(skill.steps),
                            "tags": skill.tags,
                        }
                    ),
                }
            ]
        }

    async def _handle_skill_execute(
        self,
        name: str,
        parameters: dict[str, Any] | None = None,
        auto_repair: bool = True,
    ) -> dict[str, Any]:
        """Execute a registered composite skill."""
        skill = self.store.get_skill(name)
        if not skill:
            return {
                "isError": True,
                "error_code": -32602,
                "content": [
                    {
                        "type": "text",
                        "text": f"Skill '{name}' not found in skill library.",
                    }
                ],
            }

        record = await self.executor.execute_macro(
            skill=skill,
            parameters=parameters or {},
            auto_repair=auto_repair,
            cancellation_manager=self.cancellation_manager,
        )

        result_payload = {
            "skill_name": record.skill_name,
            "status": record.status,
            "duration_ms": round(record.duration_ms, 2),
            "step_count": len(record.steps),
            "steps": [s.model_dump() for s in record.steps],
            "error": record.error,
            "diagnosis": record.diagnosis,
        }

        is_error = record.status == "failed"
        return {
            "isError": is_error,
            "error_code": -32000 if is_error else 0,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result_payload, indent=2),
                }
            ],
        }

    async def _handle_skill_delete(self, name: str) -> dict[str, Any]:
        """Delete a registered skill."""
        deleted = self.store.delete_skill(name)
        if not deleted:
            return {
                "isError": True,
                "error_code": -32602,
                "content": [
                    {
                        "type": "text",
                        "text": f"Skill '{name}' not found in skill library.",
                    }
                ],
            }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"status": "deleted", "name": name}),
                }
            ]
        }

    async def _handle_skill_get(self, name: str) -> dict[str, Any]:
        """Retrieve full details of a registered skill."""
        skill = self.store.get_skill(name)
        if not skill:
            return {
                "isError": True,
                "error_code": -32602,
                "content": [
                    {
                        "type": "text",
                        "text": f"Skill '{name}' not found in skill library.",
                    }
                ],
            }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(skill.model_dump(exclude={"embedding"}), indent=2),
                }
            ]
        }

    async def _handle_skill_list(self, tag: str | None = None) -> dict[str, Any]:
        """List registered skills in the library."""
        skills = self.store.list_skills(tag=tag)
        summaries = [
            {
                "name": s.name,
                "description": s.description,
                "tags": s.tags,
                "step_count": len(s.steps),
                "success_count": s.success_count,
                "failure_count": s.failure_count,
            }
            for s in skills
        ]
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"skills": summaries, "count": len(summaries)}, indent=2),
                }
            ]
        }
