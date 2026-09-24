"""Local deterministic embedding engine and vector similarity index.

This module provides zero-dependency semantic feature extraction, deterministic
hashing projection, and vectorized cosine similarity search for the Voyager-style
persistent skill store.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence

import numpy as np


class LocalEmbeddingEngine:
    """Zero-dependency local embedding generator using deterministic feature hashing.

    Projects text into fixed-dimension dense vectors using word tokens and character
    n-grams combined with the hashing trick (Count-Sketch / Weinberger et al.),
    sublinear term frequency weighting, and L2 unit normalization.
    """

    def __init__(
        self,
        dimension: int = 256,
        min_ngram: int = 3,
        max_ngram: int = 4,
    ) -> None:
        """Initialize the embedding engine.

        Args:
            dimension: Dimensionality of the generated embedding vector.
            min_ngram: Minimum character n-gram length for subword extraction.
            max_ngram: Maximum character n-gram length for subword extraction.
        """
        if dimension <= 0:
            raise ValueError(f"Embedding dimension must be positive, got {dimension}")
        if min_ngram <= 0 or max_ngram < min_ngram:
            raise ValueError(
                f"Invalid n-gram bounds: min_ngram={min_ngram}, max_ngram={max_ngram}"
            )

        self.dimension = dimension
        self.min_ngram = min_ngram
        self.max_ngram = max_ngram
        self._word_pattern = re.compile(r"\b\w+\b")

    def _extract_features(self, text: str) -> list[str]:
        """Extract word unigrams and character n-grams from text."""
        normalized = text.lower()
        words = self._word_pattern.findall(normalized)
        features: list[str] = []

        for word in words:
            features.append(f"w:{word}")
            padded = f"<{word}>"
            padded_len = len(padded)
            for n in range(self.min_ngram, self.max_ngram + 1):
                if padded_len >= n:
                    for i in range(padded_len - n + 1):
                        features.append(f"c:{padded[i : i + n]}")

        return features

    def compute_embedding(self, text: str) -> np.ndarray:
        """Compute a unit-normalized dense embedding vector for the given text.

        Args:
            text: Input string to embed.

        Returns:
            np.ndarray of shape (dimension,) with dtype float32, normalized to unit length.
        """
        features = self._extract_features(text)
        vector = np.zeros(self.dimension, dtype=np.float32)
        if not features:
            return vector

        # Count frequencies
        counts: dict[str, int] = {}
        for feat in features:
            counts[feat] = counts.get(feat, 0) + 1

        # Project features into vector space using SHA-256 for cross-process determinism
        for feat, count in counts.items():
            digest = hashlib.sha256(feat.encode("utf-8")).digest()
            # First 4 bytes determine dimension index
            idx = int.from_bytes(digest[:4], byteorder="big") % self.dimension
            # Next 4 bytes determine random projection sign (+1 or -1)
            sign = 1.0 if (int.from_bytes(digest[4:8], byteorder="big") & 1) == 0 else -1.0
            # Sublinear term frequency weighting: 1.0 + ln(count)
            weight = float(1.0 + np.log(float(count)))
            vector[idx] += np.float32(sign * weight)

        # L2 unit normalization
        norm = float(np.linalg.norm(vector))
        if norm > 1e-12:
            vector = (vector / np.float32(norm)).astype(np.float32)
        return vector

    def embed(self, text: str) -> list[float]:
        """Compute embedding as a list of floats.

        Args:
            text: Input string to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        return [float(x) for x in self.compute_embedding(text)]

    def rank_candidates(
        self,
        query_vector: np.ndarray | Sequence[float],
        candidates: Sequence[tuple[str, np.ndarray | Sequence[float]]],
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Rank candidate vectors against a query vector by cosine similarity.

        Args:
            query_vector: Query vector as ndarray or sequence of floats.
            candidates: Sequence of (id, vector) tuples.
            top_k: Maximum number of ranked results to return.

        Returns:
            List of (id, score) pairs ordered descending by similarity score.
        """
        q_vec = (
            query_vector
            if isinstance(query_vector, np.ndarray)
            else np.asarray(query_vector, dtype=np.float32)
        )
        cand_list: list[tuple[str, np.ndarray]] = [
            (
                cid,
                c_v
                if isinstance(c_v, np.ndarray)
                else np.asarray(c_v, dtype=np.float32),
            )
            for cid, c_v in candidates
        ]
        return VectorIndex.search(q_vec, cand_list, top_k=top_k)


class VectorIndex:
    """Vector similarity search engine using pure NumPy cosine similarity."""

    @staticmethod
    def cosine_similarity(
        vec1: np.ndarray | Sequence[float],
        vec2: np.ndarray | Sequence[float],
    ) -> float:
        """Calculate cosine similarity between two 1D vectors.

        Args:
            vec1: First 1D vector.
            vec2: Second 1D vector.

        Returns:
            Cosine similarity score clamped to [-1.0, 1.0].
        """
        v1 = vec1 if isinstance(vec1, np.ndarray) else np.asarray(vec1, dtype=np.float32)
        v2 = vec2 if isinstance(vec2, np.ndarray) else np.asarray(vec2, dtype=np.float32)

        if v1.shape != v2.shape:
            raise ValueError(f"Vector shape mismatch: {v1.shape} vs {v2.shape}")
        if v1.ndim != 1:
            raise ValueError(f"Vectors must be 1D, got ndim={v1.ndim}")

        norm1 = float(np.linalg.norm(v1))
        norm2 = float(np.linalg.norm(v2))
        if norm1 <= 1e-12 or norm2 <= 1e-12:
            return 0.0

        dot = float(np.dot(v1, v2))
        similarity = dot / (norm1 * norm2)
        return float(np.clip(similarity, -1.0, 1.0))

    @staticmethod
    def search(
        query_vector: np.ndarray | Sequence[float],
        candidate_vectors: (
            Mapping[str, np.ndarray | Sequence[float]]
            | Sequence[tuple[str, np.ndarray | Sequence[float]]]
        ),
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Search candidate vectors for highest cosine similarity to query_vector.

        Args:
            query_vector: 1D query vector.
            candidate_vectors: Mapping of ID to vector, or sequence of (id, vector) pairs.
            top_k: Maximum number of ranked results to return.

        Returns:
            List of (id, score) pairs ordered descending by similarity score.
        """
        if top_k <= 0:
            return []

        if isinstance(candidate_vectors, Mapping):
            raw_items = list(candidate_vectors.items())
        else:
            raw_items = list(candidate_vectors)

        if not raw_items:
            return []

        q_vec = (
            query_vector
            if isinstance(query_vector, np.ndarray)
            else np.asarray(query_vector, dtype=np.float32)
        )

        if q_vec.ndim != 1:
            raise ValueError(f"query_vector must be 1D, got ndim={q_vec.ndim}")

        dim = q_vec.shape[0]
        q_norm = float(np.linalg.norm(q_vec))
        if q_norm > 1e-12:
            q_unit = (q_vec / np.float32(q_norm)).astype(np.float32)
        else:
            q_unit = q_vec.astype(np.float32)

        ids: list[str] = []
        matrix_rows: list[np.ndarray] = []

        for cand_id, raw_v in raw_items:
            vec = (
                raw_v
                if isinstance(raw_v, np.ndarray)
                else np.asarray(raw_v, dtype=np.float32)
            )
            if vec.ndim != 1 or vec.shape[0] != dim:
                raise ValueError(
                    f"Candidate vector '{cand_id}' shape {vec.shape} "
                    f"does not match query dimension {dim}"
                )
            v_norm = float(np.linalg.norm(vec))
            if v_norm > 1e-12:
                v_unit = (vec / np.float32(v_norm)).astype(np.float32)
            else:
                v_unit = vec.astype(np.float32)

            ids.append(cand_id)
            matrix_rows.append(v_unit)

        matrix = np.stack(matrix_rows, axis=0)
        scores = np.dot(matrix, q_unit)
        scores = np.clip(scores, -1.0, 1.0)

        num_candidates = len(ids)
        top_count = min(top_k, num_candidates)

        if top_count < num_candidates:
            part_indices = np.argpartition(-scores, top_count)[:top_count]
            sorted_indices = part_indices[np.argsort(-scores[part_indices])]
        else:
            sorted_indices = np.argsort(-scores)

        results: list[tuple[str, float]] = [
            (ids[idx], float(scores[idx])) for idx in sorted_indices
        ]
        return results
