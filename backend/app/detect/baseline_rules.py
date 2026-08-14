"""The rules baseline -- what banks actually run today.

    flag if (dormant > 90 days AND a single credit over ₹1,00,000)
         or (paid 5 or more distinct recipients inside 10 minutes)

Both clauses describe real behaviour and both are genuinely used. The tier is
here to be beaten, but it must be beaten *fairly*: the thresholds come from
config, the fan-out clause is computed exactly rather than approximated, and
its precision and recall are reported next to everything else.

The failure mode this tier demonstrates is the one that matters. It fires on
every legitimate high-velocity account -- chit fund operators, travel agents,
wholesale traders all pay many recipients quickly -- and it misses structuring
rings completely, because staying under ₹50,000 is the entire design of a
structuring ring. Neither failure is fixable by moving a threshold.
"""

from __future__ import annotations

import math

import numpy as np

from app.config import settings
from app.graphstore.features import FeatureMatrix


def rule_scores(matrix: FeatureMatrix) -> np.ndarray:
    """Score in [0, 1] per account. The rule is binary, so it returns 0 or 1.

    A binary score is exactly why this tier cannot support an interdiction
    budget: with 312 accounts flagged and authority to freeze 12, it offers no
    way to choose which 12.
    """
    columns = {name: i for i, name in enumerate(matrix.names)}
    values = matrix.values

    dormant = values[:, columns["dormancy_days"]] > settings.rule_dormancy_days
    large_credit = values[:, columns["log_max_credit"]] > math.log1p(
        settings.rule_single_credit_inr
    )
    wide_fanout = (
        values[:, columns["max_fanout_10min"]] >= settings.rule_fanout_count
    )

    flagged = (dormant & large_credit) | wide_fanout
    return flagged.astype(np.float64)


def rule_reasons(matrix: FeatureMatrix, account_id: str) -> list[str]:
    """Which clause fired, for the explainability drawer."""
    columns = {name: i for i, name in enumerate(matrix.names)}
    row = matrix.row(account_id)

    reasons: list[str] = []
    if (
        row[columns["dormancy_days"]] > settings.rule_dormancy_days
        and row[columns["log_max_credit"]]
        > math.log1p(settings.rule_single_credit_inr)
    ):
        reasons.append("dormant_then_large_credit")
    if row[columns["max_fanout_10min"]] >= settings.rule_fanout_count:
        reasons.append("wide_fanout_in_10min")
    return reasons
