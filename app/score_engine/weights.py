"""AI Score 默认权重配置。"""

from __future__ import annotations


DEFAULT_WEIGHTS: dict[str, float] = {
    "supplier_score": 0.40,
    "product_score": 0.20,
    "profit_score": 0.20,
    "price_score": 0.10,
    "fulfillment_score": 0.10,
    # V1 预留插件，默认不参与总分。
    "competition_score": 0.00,
    "supplier_stability_score": 0.00,
}


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """规范化权重，确保参与 V1 总分的权重总和为 1。"""
    active_keys = [
        "supplier_score",
        "product_score",
        "profit_score",
        "price_score",
        "fulfillment_score",
    ]
    active_total = sum(max(weights.get(key, 0), 0) for key in active_keys)
    if active_total <= 0:
        return DEFAULT_WEIGHTS.copy()

    normalized = weights.copy()
    for key in active_keys:
        normalized[key] = round(max(weights.get(key, 0), 0) / active_total, 4)

    normalized["competition_score"] = weights.get("competition_score", 0)
    normalized["supplier_stability_score"] = weights.get(
        "supplier_stability_score",
        0,
    )
    return normalized
