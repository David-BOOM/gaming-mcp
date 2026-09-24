"""Unit tests for SQLite-backed SkillStore."""

from collections.abc import Generator
from pathlib import Path

import numpy as np
import pytest

from gaming_mcp.skills.store import (
    SkillDefinition,
    SkillStep,
    SkillStore,
)


@pytest.fixture
def memory_store() -> Generator[SkillStore, None, None]:
    """Fixture providing an in-memory SkillStore instance."""
    store = SkillStore(":memory:")
    yield store
    store.close()


def test_schema_initialization_and_migrations(memory_store: SkillStore) -> None:
    """Verify table creation, indexes, and schema migration tracking."""
    with memory_store._lock:
        cur = memory_store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = {row[0] for row in cur.fetchall()}
        assert "skills" in tables
        assert "skill_executions" in tables
        assert "schema_migrations" in tables

        cur = memory_store._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version;"
        )
        versions = [row[0] for row in cur.fetchall()]
        assert 1 in versions

        cur = memory_store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='skills';"
        )
        indexes = {row[0] for row in cur.fetchall()}
        assert "idx_skills_name" in indexes


def test_save_and_get_skill(memory_store: SkillStore) -> None:
    """Verify saving a new skill and retrieving by name and ID."""
    step1 = SkillStep(
        action="key_down",
        parameters={"key": "W"},
        description="Walk forward",
        delay_ms=250.0,
    )
    step2 = SkillStep(
        action="mouse_click",
        parameters={"button": "left"},
        description="Attack target",
    )
    skill = SkillDefinition(
        id="skill-test-1",
        name="walk_and_attack",
        description="Navigate toward enemy and strike with primary weapon.",
        parameters={"speed": "normal"},
        steps=[step1, step2],
        tags=["combat", "movement"],
    )

    saved = memory_store.save_skill(skill)
    assert saved.id == "skill-test-1"
    assert saved.created_at is not None

    by_name = memory_store.get_skill("walk_and_attack")
    assert by_name is not None
    assert by_name.id == "skill-test-1"
    assert by_name.name == "walk_and_attack"
    assert len(by_name.steps) == 2
    assert by_name.steps[0].action == "key_down"
    assert by_name.steps[0].tool_name == "key_down"
    assert by_name.steps[0].parameters == {"key": "W"}
    assert by_name.steps[0].arguments == {"key": "W"}
    assert by_name.steps[0].delay_ms == 250.0
    assert by_name.tags == ["combat", "movement"]

    by_id = memory_store.get_skill_by_id("skill-test-1")
    assert by_id is not None
    assert by_id.name == "walk_and_attack"


def test_save_skill_with_embedding(memory_store: SkillStore) -> None:
    """Verify persisting and retrieving vector embeddings as BLOBs."""
    embedding = np.random.randn(256).astype(np.float32)
    embedding = embedding / np.linalg.norm(embedding)

    skill = SkillDefinition(
        id="skill-emb-1",
        name="craft_planks",
        description="Convert wood logs into wooden planks.",
        steps=[SkillStep(action="craft", parameters={"recipe": "planks"})],
        tags=["crafting"],
    )

    memory_store.save_skill(skill, embedding=embedding)

    fetched = memory_store.get_skill("craft_planks")
    assert fetched is not None
    assert fetched.embedding is not None
    assert len(fetched.embedding) == 256
    np.testing.assert_allclose(fetched.embedding, embedding, rtol=1e-5, atol=1e-5)

    all_embs = memory_store.get_all_embeddings()
    assert "skill-emb-1" in all_embs
    np.testing.assert_allclose(all_embs["skill-emb-1"], embedding, rtol=1e-5, atol=1e-5)


def test_unique_name_constraint(memory_store: SkillStore) -> None:
    """Verify attempting to save a duplicate name with different ID raises ValueError."""
    skill1 = SkillDefinition(
        id="id-1",
        name="mine_block",
        description="Mine a block.",
        steps=[],
    )
    memory_store.save_skill(skill1)

    skill2 = SkillDefinition(
        id="id-2",
        name="mine_block",
        description="Different description.",
        steps=[],
    )
    with pytest.raises(ValueError, match="already used"):
        memory_store.save_skill(skill2)


def test_update_existing_skill(memory_store: SkillStore) -> None:
    """Verify updating an existing skill with the same ID updates attributes."""
    skill = SkillDefinition(
        id="id-update",
        name="jump_once",
        description="Jump.",
        steps=[SkillStep(action="press_key", parameters={"key": "space"})],
    )
    memory_store.save_skill(skill)

    updated_skill = SkillDefinition(
        id="id-update",
        name="jump_twice",
        description="Jump twice in succession.",
        steps=[
            SkillStep(action="press_key", parameters={"key": "space"}),
            SkillStep(action="press_key", parameters={"key": "space"}),
        ],
        tags=["acrobatics"],
    )
    memory_store.save_skill(updated_skill)

    retrieved = memory_store.get_skill_by_id("id-update")
    assert retrieved is not None
    assert retrieved.name == "jump_twice"
    assert len(retrieved.steps) == 2
    assert retrieved.tags == ["acrobatics"]
    assert memory_store.get_skill("jump_once") is None


def test_list_skills_and_tag_filtering(memory_store: SkillStore) -> None:
    """Verify listing all skills and filtering by tag."""
    s1 = SkillDefinition(
        id="s1",
        name="craft_torch",
        description="Craft torch",
        tags=["crafting", "light"],
    )
    s2 = SkillDefinition(
        id="s2",
        name="craft_sword",
        description="Craft sword",
        tags=["crafting", "combat"],
    )
    s3 = SkillDefinition(
        id="s3",
        name="dig_tunnel",
        description="Dig tunnel",
        tags=["mining"],
    )

    memory_store.save_skill(s1)
    memory_store.save_skill(s2)
    memory_store.save_skill(s3)

    all_skills = memory_store.list_skills()
    assert len(all_skills) == 3
    names = [s.name for s in all_skills]
    assert names == ["craft_sword", "craft_torch", "dig_tunnel"]

    crafting_skills = memory_store.list_skills(tag="crafting")
    assert len(crafting_skills) == 2
    assert {s.name for s in crafting_skills} == {"craft_torch", "craft_sword"}

    combat_skills = memory_store.list_skills(tag="combat")
    assert len(combat_skills) == 1
    assert combat_skills[0].name == "craft_sword"

    empty_tag = memory_store.list_skills(tag="nonexistent_tag")
    assert len(empty_tag) == 0


def test_delete_skill(memory_store: SkillStore) -> None:
    """Verify deleting by ID and name, and non-existent deletion returning False."""
    skill = SkillDefinition(
        id="del-1",
        name="temporary_macro",
        description="To be deleted",
        steps=[],
    )
    memory_store.save_skill(skill)

    assert memory_store.delete_skill("temporary_macro") is True
    assert memory_store.get_skill("temporary_macro") is None
    assert memory_store.delete_skill("temporary_macro") is False

    skill2 = SkillDefinition(
        id="del-2",
        name="another_temp",
        description="Another to delete",
        steps=[],
    )
    memory_store.save_skill(skill2)
    assert memory_store.delete_skill("del-2") is True
    assert memory_store.get_skill_by_id("del-2") is None


def test_execution_tracking(memory_store: SkillStore) -> None:
    """Verify record_execution updates counts and logs telemetry history."""
    skill = SkillDefinition(
        id="exec-1",
        name="smelt_ore",
        description="Smelt ore in furnace",
        steps=[],
    )
    memory_store.save_skill(skill)

    rec1 = memory_store.record_execution(
        skill_id="exec-1",
        status="success",
        duration_ms=145.2,
    )
    assert rec1.skill_id == "exec-1"
    assert rec1.status == "success"
    assert rec1.duration_ms == 145.2
    assert rec1.error is None

    s_after = memory_store.get_skill_by_id("exec-1")
    assert s_after is not None
    assert s_after.success_count == 1
    assert s_after.failure_count == 0

    rec2 = memory_store.record_execution(
        skill_id="exec-1",
        status="failure",
        error="Furnace ran out of fuel",
        duration_ms=88.0,
    )
    assert rec2.status == "failure"
    assert rec2.error == "Furnace ran out of fuel"

    s_after2 = memory_store.get_skill_by_id("exec-1")
    assert s_after2 is not None
    assert s_after2.success_count == 1
    assert s_after2.failure_count == 1

    history = memory_store.get_execution_history("exec-1")
    assert len(history) == 2
    assert history[0].id == rec2.id
    assert history[1].id == rec1.id


def test_record_execution_nonexistent_skill(memory_store: SkillStore) -> None:
    """Verify recording execution on nonexistent skill raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        memory_store.record_execution("ghost-id", status="success")


def test_on_disk_persistence(tmp_path: Path) -> None:
    """Verify persistent file database preserves skills and state across reopenings."""
    db_file = tmp_path / "skills_test.db"

    with SkillStore(db_file) as store1:
        skill = SkillDefinition(
            id="persist-1",
            name="open_inventory",
            description="Press E to toggle player inventory.",
            steps=[SkillStep(action="press_key", parameters={"key": "E"})],
            tags=["ui", "inventory"],
        )
        store1.save_skill(skill)
        store1.record_execution("persist-1", status="success", duration_ms=25.0)

    with SkillStore(db_file) as store2:
        loaded = store2.get_skill("open_inventory")
        assert loaded is not None
        assert loaded.id == "persist-1"
        assert loaded.success_count == 1
        assert len(loaded.steps) == 1
        assert loaded.steps[0].action == "press_key"
        history = store2.get_execution_history("persist-1")
        assert len(history) == 1
        assert history[0].status == "success"
