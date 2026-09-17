"""Delta Debugging (`ddmin`) algorithm for minimal fault sequence reduction."""

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class IrreproducibleBugError(Exception):
    """Raised when a bug cannot be reproduced with the initial full fault sequence."""



def ddmin(
    faults: list[T],
    test_fn: Callable[[list[T]], bool],
) -> list[T]:
    """Delta Debugging algorithm to find a minimal subset of faults that reproduces a failure.

    Args:
        faults: The initial list of candidate faults.
        test_fn: A function that takes a subset of faults and returns True if the invariant
                 violation/failure is reproduced, False otherwise.

    Returns:
        The minimal subset of faults that still reproduces the failure.

    Raises:
        IrreproducibleBugError: If the initial full list of faults does not reproduce the failure.
    """
    if not faults:
        return []

    if not test_fn(faults):
        raise IrreproducibleBugError(
            "Bug is irreproducible with the full sequence of faults."
        )

    n = 2
    c = list(faults)

    while len(c) >= 2:
        length = len(c)
        chunk_size = max(1, length // n)

        # Partition indices into n chunks
        chunks_indices: list[list[int]] = []
        for i in range(n):
            start = i * chunk_size
            end = length if i == n - 1 else (i + 1) * chunk_size
            if start < length:
                chunks_indices.append(list(range(start, end)))

        # Filter out any empty chunks
        chunks_indices = [chk for chk in chunks_indices if chk]
        actual_n = len(chunks_indices)

        reduced = False

        # 1. Test subsets
        for chk_idx in chunks_indices:
            sub = [c[i] for i in chk_idx]
            if test_fn(sub):
                c = sub
                n = 2
                reduced = True
                break

        if reduced:
            continue

        # 2. Test complements
        for chk_idx in chunks_indices:
            chk_set = set(chk_idx)
            comp = [c[i] for i in range(length) if i not in chk_set]
            if comp and test_fn(comp):
                c = comp
                n = max(actual_n - 1, 2)
                reduced = True
                break

        if reduced:
            continue

        # 3. Increase granularity if possible
        if actual_n < length:
            n = min(length, actual_n * 2)
        else:
            break

    return c
