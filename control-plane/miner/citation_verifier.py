"""Citation Verifier for Postmortem Mining (TASK-P3-003).

Provides near-verbatim citation verification using sliding window normalized edit distance
matching to prevent LLM citation hallucinations (§8.5).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes the Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def compute_normalized_similarity(s1: str, s2: str) -> float:
    """Computes normalized edit distance similarity ratio between two strings: 1 - dist/max_len."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    dist = levenshtein_distance(s1, s2)
    return 1.0 - (dist / max_len)


def get_citation_similarity(candidate_citation: str, source_document: str) -> float:
    """Finds the maximum normalized edit distance similarity of candidate_citation

    across sliding continuous windows in source_document.
    """
    cand = candidate_citation.strip()
    src = source_document.strip()

    if not cand and not src:
        return 1.0
    if not cand or not src:
        return 0.0

    # Substring exact match fast path
    norm_cand = re.sub(r"\s+", " ", cand.lower())
    norm_src = re.sub(r"\s+", " ", src.lower())

    if norm_cand in norm_src:
        return 1.0

    cand_len = len(cand)
    src_len = len(src)

    # Calculate reasonable window length bounds
    delta = max(4, int(cand_len * 0.25) + 2)
    min_w = max(1, cand_len - delta)
    max_w = min(src_len, cand_len + delta)

    candidate_windows: set[str] = set()

    # 1. Line and clause boundaries
    lines = [line.strip() for line in src.splitlines() if line.strip()]
    for line in lines:
        if abs(len(line) - cand_len) <= delta:
            candidate_windows.add(line)

    # 2. Word-based sliding window (fast & aligned to natural language)
    words = src.split()
    cand_word_count = len(cand.split())
    if cand_word_count > 0:
        w_min_words = max(1, cand_word_count - 3)
        w_max_words = cand_word_count + 3

        for w_count in range(w_min_words, w_max_words + 1):
            for i in range(len(words) - w_count + 1):
                win_text = " ".join(words[i : i + w_count])
                if abs(len(win_text) - cand_len) <= delta:
                    candidate_windows.add(win_text)

    # 3. Character-based sliding window with step size
    step = max(1, cand_len // 20)
    for w_len in range(min_w, max_w + 1, max(1, step // 2)):
        for i in range(0, src_len - w_len + 1, step):
            win_text = src[i : i + w_len]
            candidate_windows.add(win_text)

    max_sim = 0.0
    for win in candidate_windows:
        # Pre-filter by length difference before running full Levenshtein
        if abs(len(win) - cand_len) > delta:
            continue
        sim = compute_normalized_similarity(cand, win)
        if sim > max_sim:
            max_sim = sim
            if max_sim >= 0.99:
                break

    return max_sim


def verify_citation(
    candidate_citation: str,
    source_document: str,
    min_similarity: float = 0.92,
) -> bool:
    """Verifies that candidate_citation is a near-verbatim match (similarity >= min_similarity)

    with a continuous text segment in source_document (§8.5).
    """
    similarity = get_citation_similarity(candidate_citation, source_document)
    logger.debug(
        f"Citation verification similarity: {similarity:.4f} (threshold: {min_similarity})"
    )
    return similarity >= min_similarity
