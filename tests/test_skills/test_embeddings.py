"""Unit tests for LocalEmbeddingEngine and VectorIndex."""

import numpy as np
import pytest

from gaming_mcp.skills.embeddings import LocalEmbeddingEngine, VectorIndex


def test_embedding_determinism() -> None:
    """Verify identical text produces identical embedding vectors across instances."""
    engine1 = LocalEmbeddingEngine(dimension=256)
    engine2 = LocalEmbeddingEngine(dimension=256)

    text = "craft wooden pickaxe using 3 planks and 2 sticks"
    vec1a = engine1.compute_embedding(text)
    vec1b = engine1.compute_embedding(text)
    vec2 = engine2.compute_embedding(text)

    assert isinstance(vec1a, np.ndarray)
    assert vec1a.shape == (256,)
    assert vec1a.dtype == np.float32

    np.testing.assert_array_equal(vec1a, vec1b)
    np.testing.assert_array_equal(vec1a, vec2)

    diff_text = "equip iron sword and shield"
    diff_vec = engine1.compute_embedding(diff_text)
    assert not np.allclose(vec1a, diff_vec)


def test_embedding_unit_normalization() -> None:
    """Verify non-empty text generates unit-normalized vectors with L2 norm of 1.0."""
    engine = LocalEmbeddingEngine(dimension=128)

    samples = [
        "jump",
        "attack with enchanted diamond sword",
        "craft craft craft repetitive words repetitive words",
        "special_characters_123_test_action",
    ]

    for sample in samples:
        vec = engine.compute_embedding(sample)
        assert vec.shape == (128,)
        norm = float(np.linalg.norm(vec))
        assert pytest.approx(norm, abs=1e-5) == 1.0


def test_empty_and_whitespace_input() -> None:
    """Verify empty or blank strings return zero-vectors gracefully."""
    engine = LocalEmbeddingEngine(dimension=256)

    zero1 = engine.compute_embedding("")
    zero2 = engine.compute_embedding("   \t\n  ")

    assert np.all(zero1 == 0.0)
    assert np.all(zero2 == 0.0)

    # Cosine similarity with zero vector should be 0.0 without errors
    sim = VectorIndex.cosine_similarity(zero1, np.ones(256, dtype=np.float32))
    assert sim == 0.0


def test_case_insensitivity_and_subwords() -> None:
    """Verify embeddings are case-insensitive and capture subword overlap."""
    engine = LocalEmbeddingEngine(dimension=256)

    vec_lower = engine.compute_embedding("mine diamond ore")
    vec_upper = engine.compute_embedding("MINE DIAMOND ORE")
    vec_mixed = engine.compute_embedding("Mine Diamond Ore")

    np.testing.assert_allclose(vec_lower, vec_upper, atol=1e-6)
    np.testing.assert_allclose(vec_lower, vec_mixed, atol=1e-6)

    # Subword and lexical overlap check
    pickaxe_wood = engine.compute_embedding("craft wooden pickaxe")
    pickaxe_stone = engine.compute_embedding("craft stone pickaxe")
    ocean_swim = engine.compute_embedding("swim across deep ocean")

    sim_similar = VectorIndex.cosine_similarity(pickaxe_wood, pickaxe_stone)
    sim_unrelated = VectorIndex.cosine_similarity(pickaxe_wood, ocean_swim)

    assert sim_similar > sim_unrelated
    assert sim_similar > 0.3


def test_vector_index_search_ranking() -> None:
    """Verify VectorIndex.search ranks closest semantic candidate first."""
    engine = LocalEmbeddingEngine(dimension=256)

    candidates = {
        "wood_pick": engine.compute_embedding("craft wooden pickaxe"),
        "stone_pick": engine.compute_embedding("craft stone pickaxe"),
        "diamond_sword": engine.compute_embedding("craft diamond sword"),
        "swim_ocean": engine.compute_embedding("swim across deep ocean"),
    }

    query = engine.compute_embedding("craft stone pickaxe")
    results = VectorIndex.search(query, candidates, top_k=3)

    assert len(results) == 3
    # Top result should be exact match
    top_id, top_score = results[0]
    assert top_id == "stone_pick"
    assert pytest.approx(top_score, abs=1e-4) == 1.0

    # Scores must be in descending order
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)


def test_vector_index_search_with_sequence_of_tuples() -> None:
    """Verify VectorIndex.search supports list of (id, vector) tuples."""
    engine = LocalEmbeddingEngine(dimension=128)

    candidates = [
        ("id1", engine.compute_embedding("attack goblin")),
        ("id2", engine.compute_embedding("heal companion")),
        ("id3", engine.compute_embedding("flee from dragon")),
    ]

    query = engine.compute_embedding("strike goblin with sword")
    results = VectorIndex.search(query, candidates, top_k=2)

    assert len(results) == 2
    assert results[0][0] == "id1"
    assert results[0][1] > results[1][1]


def test_vector_index_edge_cases() -> None:
    """Verify VectorIndex handles empty lists, top_k bounds, and invalid shapes."""
    engine = LocalEmbeddingEngine(dimension=64)
    query = engine.compute_embedding("test query")

    # Empty candidate dictionary/sequence
    assert VectorIndex.search(query, {}, top_k=5) == []
    assert VectorIndex.search(query, [], top_k=5) == []

    # top_k non-positive
    assert VectorIndex.search(query, {"a": query}, top_k=0) == []
    assert VectorIndex.search(query, {"a": query}, top_k=-2) == []

    # Dimension mismatch in query vs candidate
    wrong_dim_cand = {"b": np.zeros(128, dtype=np.float32)}
    with pytest.raises(ValueError, match="does not match query dimension"):
        VectorIndex.search(query, wrong_dim_cand, top_k=3)

    # 2D query vector
    with pytest.raises(ValueError, match="query_vector must be 1D"):
        VectorIndex.search(np.zeros((2, 64), dtype=np.float32), {"a": query})

    # Cosine similarity shape mismatch
    with pytest.raises(ValueError, match="Vector shape mismatch"):
        VectorIndex.cosine_similarity(np.zeros(64), np.zeros(32))


def test_vector_index_cosine_similarity_properties() -> None:
    """Verify cosine similarity mathematical bounds and orthogonality."""
    vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    vec3 = np.array([-1.0, 0.0, 0.0], dtype=np.float32)

    # Orthogonal
    assert pytest.approx(VectorIndex.cosine_similarity(vec1, vec2), abs=1e-5) == 0.0
    # Opposite
    assert pytest.approx(VectorIndex.cosine_similarity(vec1, vec3), abs=1e-5) == -1.0
    # Identical
    assert pytest.approx(VectorIndex.cosine_similarity(vec1, vec1), abs=1e-5) == 1.0


def test_engine_embed_and_rank_candidates() -> None:
    """Verify embed() and rank_candidates() convenience methods on LocalEmbeddingEngine."""
    engine = LocalEmbeddingEngine(dimension=128)

    float_list = engine.embed("build shelter")
    assert isinstance(float_list, list)
    assert len(float_list) == 128
    assert all(isinstance(x, float) for x in float_list)

    candidates = [
        ("s1", engine.embed("build small shelter")),
        ("s2", engine.embed("cook porkchop")),
        ("s3", engine.embed("mine redstone")),
    ]

    ranked = engine.rank_candidates(float_list, candidates, top_k=2)
    assert len(ranked) == 2
    assert ranked[0][0] == "s1"
    assert ranked[0][1] > ranked[1][1]
