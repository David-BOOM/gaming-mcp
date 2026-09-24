"""SQLite-backed persistent skill store for Voyager-style macros.

This module provides SQLite storage and lifecycle management for composite macros,
parameter schemas, execution telemetry, and vector embeddings.
"""

import json
import sqlite3
import threading
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, model_validator


class SkillStep(BaseModel):
    """Atomic execution step within a composite macro skill."""

    action: str = Field(
        default="",
        description="Action name or tool identifier to invoke",
    )
    tool_name: str = Field(
        default="",
        description="Name of the MCP tool to invoke",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters passed to the action",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments passed to the action",
    )
    description: str = Field(
        default="",
        description="Human-readable rationale or description of the step",
    )
    delay_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Post-execution pause in milliseconds",
    )
    retry_delay_s: float = Field(
        default=0.0,
        ge=0.0,
        description="Seconds to wait before retrying a failed step",
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        description="Maximum retry attempts if this step fails during execution",
    )
    expected_outcome: str | None = Field(
        default=None,
        description="Expected state or observation after step execution",
    )
    compensation_steps: list["SkillStep"] = Field(
        default_factory=list,
        description="Fallback compensation steps to execute if this step fails",
    )
    on_error: str = Field(
        default="retry",
        description="Action strategy on failure: retry, compensate, fail, or ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            act = data.get("action") or data.get("tool_name") or ""
            data["action"] = act
            data["tool_name"] = act
            params = data.get("parameters") or data.get("arguments") or {}
            data["parameters"] = params
            data["arguments"] = params
        return data


MacroStep = SkillStep


class SkillDefinition(BaseModel):
    """Voyager-style composite skill definition with parameters and execution steps."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique skill UUID or identifier",
    )
    name: str = Field(
        ...,
        min_length=1,
        description="Unique human-readable skill name",
    )
    description: str = Field(
        ...,
        description="Natural language description of skill capability",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameter schema or definitions for macro variables",
    )
    steps: list[SkillStep] = Field(
        default_factory=list,
        description="Ordered sequence of execution steps",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Categorization, genre, or game tags",
    )
    success_count: int = Field(
        default=0,
        ge=0,
        description="Cumulative count of successful executions",
    )
    failure_count: int = Field(
        default=0,
        ge=0,
        description="Cumulative count of failed executions",
    )
    created_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp of skill creation",
    )
    updated_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp of last update",
    )
    embedding: list[float] | None = Field(
        default=None,
        description="Optional dense vector embedding representation",
    )


class SkillExecutionRecord(BaseModel):
    """Audit log entry capturing the result of a single skill execution."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique execution record identifier",
    )
    skill_id: str = Field(
        ...,
        description="ID of the executed skill",
    )
    status: str = Field(
        ...,
        description="Execution status: 'success', 'failure', etc.",
    )
    error: str | None = Field(
        default=None,
        description="Error message or stack trace if execution failed",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Total execution duration in milliseconds",
    )
    executed_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp of execution",
    )


SCHEMA_MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            """
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                embedding BLOB
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);",
            """
            CREATE TABLE IF NOT EXISTS skill_executions (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                duration_ms REAL NOT NULL,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(skill_id) REFERENCES skills(id) ON DELETE CASCADE
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_executions_skill_id ON skill_executions(skill_id);",
        ],
    ),
]


class SkillStore:
    """Thread-safe SQLite store for composite skills and execution history."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Initialize the skill repository.

        Args:
            db_path: Path to on-disk database file or ':memory:' for transient storage.
        """
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        with self._lock:
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._apply_migrations()

    def _apply_migrations(self) -> None:
        """Apply pending schema migrations in sequential order."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations;"
        )
        row = cur.fetchone()
        current_version: int = row[0] if row else 0

        for version, statements in SCHEMA_MIGRATIONS:
            if version > current_version:
                for stmt in statements:
                    self._conn.execute(stmt)
                self._conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?);", (version,)
                )
        self._conn.commit()

    def save_skill(
        self,
        skill: SkillDefinition,
        embedding: np.ndarray | Sequence[float] | None = None,
    ) -> SkillDefinition:
        """Save or update a skill definition in the store.

        Args:
            skill: Skill definition to persist.
            embedding: Optional embedding vector to associate with the skill.

        Returns:
            The persisted SkillDefinition with updated fields.

        Raises:
            ValueError: If skill name is already taken by another skill with a different ID.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM skills WHERE name = ?;", (skill.name,)
            )
            existing = cur.fetchone()
            if existing is not None and existing["id"] != skill.id:
                raise ValueError(
                    f"Skill name '{skill.name}' is already used by skill '{existing['id']}'"
                )

            current_time = skill.created_at or datetime.now(UTC).isoformat()
            updated_time = datetime.now(UTC).isoformat()
            emb_list: list[float] | None = None
            blob: bytes | None = None

            if embedding is not None:
                emb_arr = np.asarray(embedding, dtype=np.float32)
                blob = emb_arr.tobytes()
                emb_list = emb_arr.tolist()
            elif skill.embedding is not None:
                emb_arr = np.asarray(skill.embedding, dtype=np.float32)
                blob = emb_arr.tobytes()
                emb_list = emb_arr.tolist()

            params_dict = {
                k: v.model_dump() if hasattr(v, "model_dump") else v
                for k, v in skill.parameters.items()
            }
            parameters_json = json.dumps(params_dict)
            steps_json = json.dumps([s.model_dump() for s in skill.steps])
            tags_json = json.dumps(skill.tags)

            self._conn.execute(
                """
                INSERT INTO skills (
                    id, name, description, parameters_json, steps_json, tags_json,
                    success_count, failure_count, created_at, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    parameters_json = excluded.parameters_json,
                    steps_json = excluded.steps_json,
                    tags_json = excluded.tags_json,
                    success_count = excluded.success_count,
                    failure_count = excluded.failure_count,
                    embedding = excluded.embedding;
                """,
                (
                    skill.id,
                    skill.name,
                    skill.description,
                    parameters_json,
                    steps_json,
                    tags_json,
                    skill.success_count,
                    skill.failure_count,
                    current_time,
                    blob,
                ),
            )
            self._conn.commit()

            return skill.model_copy(
                update={
                    "created_at": current_time,
                    "updated_at": updated_time,
                    "embedding": emb_list,
                }
            )

    def _row_to_skill(self, row: sqlite3.Row) -> SkillDefinition:
        """Convert a database row to a SkillDefinition model."""
        blob: bytes | None = row["embedding"]
        emb_list: list[float] | None = None
        if blob is not None and len(blob) > 0:
            emb_arr = np.frombuffer(blob, dtype=np.float32)
            emb_list = emb_arr.tolist()

        raw_steps: list[dict[str, Any]] = json.loads(row["steps_json"])
        steps = [SkillStep.model_validate(s) for s in raw_steps]

        return SkillDefinition(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            parameters=json.loads(row["parameters_json"]),
            steps=steps,
            tags=json.loads(row["tags_json"]),
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            created_at=row["created_at"],
            updated_at=row["created_at"],
            embedding=emb_list,
        )

    def get_skill(self, name: str) -> SkillDefinition | None:
        """Retrieve a skill by unique name.

        Args:
            name: Unique name of the skill.

        Returns:
            SkillDefinition if found, otherwise None.
        """
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, name, description, parameters_json, steps_json, tags_json,
                       success_count, failure_count, created_at, embedding
                FROM skills WHERE name = ?;
                """,
                (name,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_skill(row)

    def get_skill_by_id(self, skill_id: str) -> SkillDefinition | None:
        """Retrieve a skill by its unique identifier.

        Args:
            skill_id: Unique skill UUID or ID string.

        Returns:
            SkillDefinition if found, otherwise None.
        """
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, name, description, parameters_json, steps_json, tags_json,
                       success_count, failure_count, created_at, embedding
                FROM skills WHERE id = ?;
                """,
                (skill_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_skill(row)

    def list_skills(self, tag: str | None = None) -> list[SkillDefinition]:
        """List all persisted skills, optionally filtered by tag.

        Args:
            tag: Optional tag to filter by.

        Returns:
            List of SkillDefinition objects sorted by name.
        """
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, name, description, parameters_json, steps_json, tags_json,
                       success_count, failure_count, created_at, embedding
                FROM skills ORDER BY name ASC;
                """
            )
            rows = cur.fetchall()

        skills: list[SkillDefinition] = []
        for row in rows:
            skill = self._row_to_skill(row)
            if tag is None or tag in skill.tags:
                skills.append(skill)
        return skills

    def delete_skill(self, skill_id_or_name: str) -> bool:
        """Delete a skill by identifier or name.

        Args:
            skill_id_or_name: Skill ID or unique name to delete.

        Returns:
            True if a record was deleted, False if not found.
        """
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM skills WHERE id = ? OR name = ?;",
                (skill_id_or_name, skill_id_or_name),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def record_execution(
        self,
        skill_id: Any,
        status: str | None = None,
        error: str | None = None,
        duration_ms: float = 0.0,
    ) -> SkillExecutionRecord:
        """Record an execution telemetry event and update skill counters.

        Args:
            skill_id: ID or name of the executed skill, or an ExecutionRecord object.
            status: Execution status ('success', 'failed', 'repaired', etc.).
            error: Optional error message or traceback.
            duration_ms: Total duration of execution in milliseconds.

        Returns:
            SkillExecutionRecord logging the execution.

        Raises:
            ValueError: If skill cannot be found by ID or name.
        """
        if hasattr(skill_id, "skill_name") and hasattr(skill_id, "status"):
            target_key = str(skill_id.skill_name)
            target_status = str(skill_id.status)
            target_error = getattr(skill_id, "error", None)
            target_dur = float(getattr(skill_id, "duration_ms", 0.0))
        else:
            target_key = str(skill_id)
            target_status = str(status) if status is not None else "success"
            target_error = error
            target_dur = duration_ms

        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM skills WHERE id = ? OR name = ?;",
                (target_key, target_key),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Skill with ID or name '{target_key}' not found")

            resolved_id = str(row[0])
            record_id = str(uuid.uuid4())
            executed_at = datetime.now(UTC).isoformat()

            self._conn.execute(
                """
                INSERT INTO skill_executions (
                    id, skill_id, status, error, duration_ms, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (record_id, resolved_id, target_status, target_error, target_dur, executed_at),
            )

            if target_status.lower() in ("success", "repaired"):
                self._conn.execute(
                    "UPDATE skills SET success_count = success_count + 1 WHERE id = ?;",
                    (resolved_id,),
                )
            else:
                self._conn.execute(
                    "UPDATE skills SET failure_count = failure_count + 1 WHERE id = ?;",
                    (resolved_id,),
                )

            self._conn.commit()

            return SkillExecutionRecord(
                id=record_id,
                skill_id=resolved_id,
                status=target_status,
                error=target_error,
                duration_ms=target_dur,
                executed_at=executed_at,
            )

    def get_execution_history(
        self,
        skill_id: str,
        limit: int = 50,
    ) -> list[SkillExecutionRecord]:
        """Retrieve recent execution records for a skill.

        Args:
            skill_id: ID of the skill.
            limit: Maximum number of records to return.

        Returns:
            List of SkillExecutionRecord objects ordered by executed_at descending.
        """
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, skill_id, status, error, duration_ms, executed_at
                FROM skill_executions
                WHERE skill_id = ?
                ORDER BY executed_at DESC, rowid DESC
                LIMIT ?;
                """,
                (skill_id, limit),
            )
            rows = cur.fetchall()

        records: list[SkillExecutionRecord] = []
        for r in rows:
            records.append(
                SkillExecutionRecord(
                    id=r["id"],
                    skill_id=r["skill_id"],
                    status=r["status"],
                    error=r["error"],
                    duration_ms=r["duration_ms"],
                    executed_at=r["executed_at"],
                )
            )
        return records

    def get_stats(self) -> dict[str, Any]:
        """Calculate aggregated skill statistics across stored skills and executions."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total_skills,
                    COALESCE(SUM(success_count), 0) as total_success,
                    COALESCE(SUM(failure_count), 0) as total_failure
                FROM skills;
                """
            )
            row = cur.fetchone()
            total_skills: int = int(row[0]) if row else 0
            total_success: int = int(row[1]) if row else 0
            total_failure: int = int(row[2]) if row else 0

            cur_history = self._conn.execute(
                "SELECT COUNT(*) FROM skill_executions;"
            )
            hist_row = cur_history.fetchone()
            total_runs: int = int(hist_row[0]) if hist_row else 0

        total_attempts = total_success + total_failure
        success_rate = (
            float(round(total_success / total_attempts, 4))
            if total_attempts > 0
            else 0.0
        )
        return {
            "total_skills": total_skills,
            "total_executions": total_runs,
            "total_success": total_success,
            "total_failure": total_failure,
            "success_rate": success_rate,
        }

    def get_history(
        self,
        limit: int = 50,
        skill_id_or_name: str | None = None,
    ) -> list[SkillExecutionRecord]:
        """Retrieve recent macro execution traces across all skills or for a specific skill."""
        with self._lock:
            if skill_id_or_name:
                cur = self._conn.execute(
                    """
                    SELECT e.id, e.skill_id, e.status, e.error, e.duration_ms, e.executed_at
                    FROM skill_executions e
                    JOIN skills s ON e.skill_id = s.id
                    WHERE e.skill_id = ? OR s.name = ?
                    ORDER BY e.executed_at DESC
                    LIMIT ?;
                    """,
                    (skill_id_or_name, skill_id_or_name, limit),
                )
            else:
                cur = self._conn.execute(
                    """
                    SELECT id, skill_id, status, error, duration_ms, executed_at
                    FROM skill_executions
                    ORDER BY executed_at DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

        records: list[SkillExecutionRecord] = []
        for r in rows:
            records.append(
                SkillExecutionRecord(
                    id=r["id"],
                    skill_id=r["skill_id"],
                    status=r["status"],
                    error=r["error"],
                    duration_ms=r["duration_ms"],
                    executed_at=r["executed_at"],
                )
            )
        return records

    def update_stats(self, skill_id_or_name: str, success: bool) -> None:
        """Increment success or failure count for a skill by ID or name."""
        with self._lock:
            col = "success_count" if success else "failure_count"
            self._conn.execute(
                f"UPDATE skills SET {col} = {col} + 1 WHERE id = ? OR name = ?;",
                (skill_id_or_name, skill_id_or_name),
            )
            self._conn.commit()

    def get_all_embeddings(self) -> dict[str, np.ndarray]:
        """Retrieve all vector embeddings associated with stored skills.

        Returns:
            Dictionary mapping skill_id to 1D float32 numpy array.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, embedding FROM skills WHERE embedding IS NOT NULL;"
            )
            rows = cur.fetchall()

        embeddings: dict[str, np.ndarray] = {}
        for row in rows:
            blob: bytes | None = row["embedding"]
            if blob:
                arr = np.frombuffer(blob, dtype=np.float32).copy()
                embeddings[row["id"]] = arr
        return embeddings

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SkillStore":
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit context manager."""
        self.close()
