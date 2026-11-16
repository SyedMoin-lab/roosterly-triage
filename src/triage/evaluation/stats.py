import math

Z_95 = 1.959964


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    share = successes / total
    denominator = 1 + z * z / total
    centre = (share + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def mcnemar_exact(fixed: int, broken: int) -> float:
    changed = fixed + broken
    if changed == 0:
        return 1.0
    tail = sum(math.comb(changed, k) for k in range(min(fixed, broken) + 1)) / 2.0**changed
    return min(1.0, 2 * tail)
