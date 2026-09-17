"""Unit tests for Corpus Profiling & Postmortem Miner with verify_citation (TASK-P3-003)."""

from __future__ import annotations

import os
import sys

# Ensure control-plane is in sys.path
sys.path.insert(0, os.path.abspath("control-plane"))

from miner import (
    DifferentialProfiler,
    PostmortemMiner,
    get_citation_similarity,
    verify_citation,
)


def test_verify_citation_exact_and_near_verbatim() -> None:
    """Happy Path 1: Source contains exact sentence, candidate citation has 0.98 similarity."""
    source_doc = (
        "Postmortem Report INC-2026-09:\n"
        "Root cause analysis revealed an edge case in refund handling.\n"
        "Refunds must never exceed the original transaction value under any circumstances.\n"
        "Action item: implement invariant check on payment service."
    )
    # Exact citation
    candidate_exact = (
        "Refunds must never exceed the original transaction value under any circumstances."
    )
    assert verify_citation(candidate_exact, source_doc, min_similarity=0.92) is True
    assert get_citation_similarity(candidate_exact, source_doc) >= 0.98

    # Near-verbatim citation (missing 's' in circumstances -> near identical match)
    candidate_near = (
        "Refunds must never exceed the original transaction value under any circumstance."
    )
    assert verify_citation(candidate_near, source_doc, min_similarity=0.92) is True
    assert get_citation_similarity(candidate_near, source_doc) >= 0.92


def test_differential_profiling_finds_divergent_step() -> None:
    """Happy Path 2: Compares 1 error trace (double refund) with 50 success traces, locating retry step after timeout."""
    user_prompt = "Process refund for order #9981"

    # 50 success traces
    success_traces = [
        {
            "trace_id": f"trace_ok_{i}",
            "user_prompt": user_prompt,
            "status": "completed",
            "status_source": "reconciliation_webhook",
            "steps": [
                {
                    "step_index": 0,
                    "name": "parse_request",
                    "action": "parse",
                    "status": "success",
                },
                {
                    "step_index": 1,
                    "name": "call_payment_api",
                    "action": "refund",
                    "status": "success",
                },
            ],
        }
        for i in range(50)
    ]

    # 1 error trace with double refund
    error_trace = {
        "trace_id": "trace_err_double_refund",
        "user_prompt": user_prompt,
        "status": "agent_error",
        "status_source": "human_triage",
        "steps": [
            {
                "step_index": 0,
                "name": "parse_request",
                "action": "parse",
                "status": "success",
            },
            {
                "step_index": 1,
                "name": "call_payment_api",
                "action": "refund",
                "status": "timeout",
            },
            {
                "step_index": 2,
                "name": "retry_payment_api",
                "action": "retry_refund",
                "status": "duplicate_refund",
            },
        ],
    }

    profiler = DifferentialProfiler()
    result = profiler.profile(error_trace, success_traces)

    assert result.divergent_step is not None
    assert result.divergent_step_index in (1, 2)
    # Profiler accurately locates the point of divergence at the retry step after tool returned timeout
    assert (
        "retry" in result.divergent_step.get("action", "").lower()
        or result.divergent_step.get("status") in ("timeout", "duplicate_refund")
    )
    assert result.filtered_baseline_count == 50


def test_verify_citation_rejects_hallucinated_paraphrase() -> None:
    """Edge Case 1: LLM free paraphrase citation gets similarity 0.54 < 0.92, flagged citation_unverified: True and forbidden critical."""
    source_doc = (
        "Postmortem Report INC-2026-09:\n"
        "Refunds must never exceed the original transaction value under any circumstances."
    )
    paraphrased_citation = "The agent shouldn't give too much money back to customers."

    similarity = get_citation_similarity(paraphrased_citation, source_doc)
    assert similarity < 0.92
    assert (
        verify_citation(paraphrased_citation, source_doc, min_similarity=0.92) is False
    )

    # Test PostmortemMiner handling of unverified citation
    miner = PostmortemMiner(min_similarity=0.92)
    draft = {
        "id": "cand_paraphrase",
        "statement": "Agent refund limit invariant",
        "category": "safety",
        "check": "refund <= total",
        "severity": "critical",  # Requested severity critical
        "citation": paraphrased_citation,
    }

    result = miner.mine_from_postmortem(source_doc, [draft])
    candidate = result["all_candidates"][0]

    assert candidate.citation_unverified is True
    assert candidate.metadata.get("citation_unverified") is True
    # Forbidden to set severity critical
    assert candidate.severity != "critical"
    assert candidate.severity == "advisory"
    assert miner.citation_verification_fail_rate == 1.0


def test_differential_profiling_ignores_unreliable_traces() -> None:
    """Edge Case 2: Profiler automatically filters out traces with status_source='inferred_no_terminal_event'."""
    user_prompt = "Process refund for order #100"

    mixed_traces = [
        # Reliable traces
        {
            "trace_id": "trace_rel_1",
            "user_prompt": user_prompt,
            "status": "completed",
            "status_source": "human_triage",
            "steps": [
                {
                    "step_index": 0,
                    "name": "step1",
                    "action": "refund",
                    "status": "success",
                }
            ],
        },
        {
            "trace_id": "trace_rel_2",
            "user_prompt": user_prompt,
            "status": "completed",
            "status_source": "reconciliation_webhook",
            "steps": [
                {
                    "step_index": 0,
                    "name": "step1",
                    "action": "refund",
                    "status": "success",
                }
            ],
        },
        # Unreliable trace
        {
            "trace_id": "trace_unrel_1",
            "user_prompt": user_prompt,
            "status": "completed",
            "status_source": "inferred_no_terminal_event",
            "steps": [
                {
                    "step_index": 0,
                    "name": "step1",
                    "action": "refund",
                    "status": "success",
                }
            ],
        },
    ]

    profiler = DifferentialProfiler()
    reliable, ignored = profiler.filter_reliable_traces(
        mixed_traces, for_success_baseline=True
    )

    assert len(reliable) == 2
    assert len(ignored) == 1
    assert ignored[0]["trace_id"] == "trace_unrel_1"
    assert ignored[0]["status_source"] == "inferred_no_terminal_event"
