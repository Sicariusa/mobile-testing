"""Complexity & correctness guards (the harness, as CI). Each asserts a scaling
*ratio* or an op *bound*, never wall-clock, so it holds on any machine. A change
that makes resolve/rank/fingerprint super-linear, or the crawl unbounded, or the
hierarchy memo stop working, fails here."""
from __future__ import annotations

import pytest

from tools import perf


@pytest.mark.parametrize("check", perf.ALL_CHECKS, ids=lambda c: c.__name__)
def test_engine_check_passes(check):
    result = check()
    assert result.ok, f"{result.name}: {result.detail}"


def test_hierarchy_memo_is_o1():
    c = perf.check_hierarchy_memo_o1()
    assert c.ok and c.verdict == "O(n)".replace("n", "1")  # "O(1)"


def test_rank_candidates_is_linear():
    c = perf.check_rank_candidates_linear()
    assert c.verdict in ("O(n)", "~O(n log n)"), c.detail


def test_crawl_ops_are_bounded_and_correct():
    c = perf.check_crawl_bounded()
    assert c.ok, c.detail
