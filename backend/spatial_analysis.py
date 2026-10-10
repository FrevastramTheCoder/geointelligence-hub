"""Pure-Python validation and math used by spatial-analysis workflows.

These functions are intentionally independent of Earth Engine so that AHP,
normalization, and input validation remain testable without user credentials.
"""
from __future__ import annotations

import math


def validate_weights(weights, allowed=None):
    if not isinstance(weights, dict) or not weights:
        raise ValueError("Provide explicit criterion weights; no scientific weights are assumed.")
    clean = {}
    for name, value in weights.items():
        key = str(name).strip().lower()
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Weight for {key!r} must be numeric.")
        if not key or not math.isfinite(number) or number < 0:
            raise ValueError("Weights must have non-empty names and finite non-negative values.")
        clean[key] = number
    if allowed is not None:
        unknown = sorted(set(clean) - set(allowed))
        if unknown:
            raise ValueError(f"Unknown criteria: {', '.join(unknown)}. Available: {', '.join(sorted(allowed))}.")
    total = sum(clean.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("At least one criterion weight must be greater than zero.")
    return {k: v / total for k, v in clean.items()}


def ahp_weights(matrix, criteria=None):
    """Validate reciprocal Saaty matrix and return principal-vector weights/CR."""
    if not isinstance(matrix, list) or not 2 <= len(matrix) <= 8:
        raise ValueError("AHP pairwiseMatrix must be a square 2–8 criterion matrix.")
    n = len(matrix)
    if any(not isinstance(row, list) or len(row) != n for row in matrix):
        raise ValueError("AHP pairwiseMatrix must be square.")
    a = []
    for row in matrix:
        parsed = []
        for val in row:
            try:
                x = float(val)
            except (TypeError, ValueError):
                raise ValueError("AHP matrix values must be numeric Saaty comparisons.")
            if not math.isfinite(x) or x <= 0:
                raise ValueError("AHP matrix values must be finite and positive.")
            parsed.append(x)
        a.append(parsed)
    for i in range(n):
        if abs(a[i][i] - 1) > 1e-8:
            raise ValueError("AHP diagonal entries must equal 1.")
        for j in range(n):
            if abs(a[i][j] * a[j][i] - 1) > 1e-5:
                raise ValueError("AHP matrix must be reciprocal (a[i,j] × a[j,i] = 1).")
    # Geometric-mean principal-vector approximation, commonly used for AHP.
    gm = [math.prod(row) ** (1 / n) for row in a]
    total = sum(gm)
    weights = [x / total for x in gm]
    aw = [sum(a[i][j] * weights[j] for j in range(n)) for i in range(n)]
    lam_max = sum(aw[i] / weights[i] for i in range(n)) / n
    ci = max(0.0, (lam_max - n) / (n - 1))
    ri = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12,
          6: 1.24, 7: 1.32, 8: 1.41}[n]
    cr = ci / ri if ri else 0.0
    names = criteria or [f"criterion_{i + 1}" for i in range(n)]
    if not isinstance(names, list) or len(names) != n or any(not isinstance(x, str) or not x.strip() for x in names):
        raise ValueError("criteria must contain one unique name per AHP matrix row/column.")
    names = [x.strip().lower() for x in names]
    if len(set(names)) != n:
        raise ValueError("criteria must contain one unique name per AHP matrix row/column.")
    return dict(zip(names, weights)), cr, lam_max


def normalize_values(values, direction="benefit", scale=None):
    """Min-max normalization; optional explicit (minimum, maximum) scale."""
    if direction not in ("benefit", "cost"):
        raise ValueError("direction must be 'benefit' or 'cost'.")
    finite = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("Criterion values must be numeric or missing.")
        if math.isfinite(number):
            finite.append(number)
    if not finite:
        raise ValueError("Criterion has no finite, non-missing values.")
    lo, hi = (float(scale[0]), float(scale[1])) if scale else (min(finite), max(finite))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        raise ValueError("Normalization scale requires finite minimum < maximum.")
    normalized = []
    for value in values:
        if value is None:
            normalized.append(None)
            continue
        number = float(value)
        scaled = (number - lo) / (hi - lo) if direction == "benefit" else (hi - number) / (hi - lo)
        normalized.append(max(0, min(1, scaled)))
    return normalized
