"""LLM Postmortem Invariant Miner with Citation Verification (TASK-P3-003).

Mines candidate invariants from postmortem documents and enforces strict
citation verification against source documents to prevent LLM hallucinations (§8.5).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from miner.ast_miner import MinedCandidate
from miner.citation_verifier import verify_citation

logger = logging.getLogger(__name__)


@dataclass
class PostmortemCandidate(MinedCandidate):
    """Invariant candidate mined from postmortem documentation."""

    citation: str = ""
    citation_unverified: bool = False

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}
        self.metadata["citation"] = self.citation
        self.metadata["citation_unverified"] = self.citation_unverified

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["citation"] = self.citation
        d["citation_unverified"] = self.citation_unverified
        return d


class PostmortemMiner:
    """Mines invariant candidates from postmortem documents and enforces near-verbatim

    citation verification per §8.5.
    """

    def __init__(self, min_similarity: float = 0.92) -> None:
        self.min_similarity = min_similarity
        self.total_citations_checked = 0
        self.failed_citations_count = 0
        self.verified_candidates: list[PostmortemCandidate] = []
        self.unverified_candidates: list[PostmortemCandidate] = []

    @property
    def citation_verification_fail_rate(self) -> float:
        """Calculates the citation verification failure rate across all checked citations."""
        if self.total_citations_checked == 0:
            return 0.0
        return self.failed_citations_count / self.total_citations_checked

    def process_candidate_draft(
        self,
        draft: dict[str, Any],
        source_document: str,
    ) -> PostmortemCandidate:
        """Processes a single candidate draft against source_document, verifying its citation."""
        self.total_citations_checked += 1

        citation = draft.get("citation", "").strip()
        requested_severity = draft.get("severity", "critical")
        category = draft.get("category", "safety")
        check_expr = draft.get("check", "true")
        statement = draft.get("statement", "")

        candidate_id = draft.get(
            "id",
            f"pm_{hashlib.sha256(statement.encode('utf-8')).hexdigest()[:10]}",
        )

        is_valid_citation = False
        if citation:
            is_valid_citation = verify_citation(
                candidate_citation=citation,
                source_document=source_document,
                min_similarity=self.min_similarity,
            )

        if is_valid_citation:
            unverified = False
            severity = requested_severity
            status = "candidate"
        else:
            self.failed_citations_count += 1
            unverified = True
            status = "unverified_citation"
            # Forbidden to set severity: critical if citation is unverified (§8.5)
            severity = "advisory" if requested_severity == "critical" else requested_severity

        cand_metadata = draft.get("metadata", {}).copy()
        cand_metadata["citation"] = citation
        cand_metadata["citation_unverified"] = unverified

        candidate = PostmortemCandidate(
            id=candidate_id,
            statement=statement,
            category=category,
            check=check_expr,
            severity=severity,
            source=draft.get("source", ["postmortem"]),
            status=status,
            citation=citation,
            citation_unverified=unverified,
            metadata=cand_metadata,
        )

        if unverified:
            self.unverified_candidates.append(candidate)
        else:
            self.verified_candidates.append(candidate)

        return candidate

    def mine_from_postmortem(
        self,
        postmortem_text: str,
        candidate_drafts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Mines candidates from candidate drafts and verifies their citations against postmortem_text."""
        candidates: list[PostmortemCandidate] = []
        for draft in candidate_drafts:
            cand = self.process_candidate_draft(draft, postmortem_text)
            candidates.append(cand)

        return {
            "total_checked": self.total_citations_checked,
            "failed_count": self.failed_citations_count,
            "fail_rate": self.citation_verification_fail_rate,
            "verified_candidates": self.verified_candidates,
            "unverified_candidates": self.unverified_candidates,
            "all_candidates": candidates,
        }
