"""利润评分插件。"""

from __future__ import annotations

import math

from app.score_engine.base import BaseScorePlugin
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult


class ProfitScorePlugin(BaseScorePlugin):
    """计算采购价、成本、利润、利润率和 ROI。"""

    name = "profit_score"
    display_name = "Profit Score"
    version = "1.0.0"
    weight_key = "profit_score"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """计算利润分数。"""
        rules = context.rules.get(self.name, {})
        product = context.product
        reasons: list[str] = []
        risks: list[str] = []

        purchase_price = product.purchase_price or _parse_price(product.price)
        logistics_cost = product.shipping_fee
        if logistics_cost is None:
            logistics_cost = float(rules.get("logistics_cost", 3.0))

        packaging_cost = product.packaging_cost
        if packaging_cost is None:
            packaging_cost = float(rules.get("packaging_cost", 1.0))

        commission_rate = product.platform_commission_rate
        if commission_rate is None:
            commission_rate = float(rules.get("platform_commission_rate", 0.08))

        use_existing_price = bool(rules.get("use_existing_suggested_price", False))
        if use_existing_price and product.suggested_price:
            suggested_price = product.suggested_price
            suggested_price_source = "商品已有建议售价"
        else:
            suggested_price = calculate_suggested_price(
                purchase_price=purchase_price,
                logistics_cost=logistics_cost,
                packaging_cost=packaging_cost,
                commission_rate=commission_rate,
                rules=rules,
            )
            suggested_price_source = "成本加成模型"

        commission = suggested_price * commission_rate
        total_cost = purchase_price + logistics_cost + packaging_cost + commission
        estimated_profit = suggested_price - total_cost
        profit_margin = estimated_profit / suggested_price if suggested_price else 0
        roi = estimated_profit / total_cost if total_cost else 0

        good_profit_margin = float(rules.get("good_profit_margin", 0.35))
        good_roi = float(rules.get("good_roi", 1.0))
        score = 0.0
        score += min(max(profit_margin, 0) / good_profit_margin, 1) * 55
        score += min(max(roi, 0) / good_roi, 1) * 45

        supplier = context.supplier
        is_factory = bool(supplier and supplier.is_factory)
        non_factory_penalty = float(rules.get("non_factory_profit_score_penalty", 0))
        if not is_factory and non_factory_penalty > 0:
            score *= max(0, 1 - non_factory_penalty)
            risks.append("供应商未识别为源头工厂，利润空间可能被中间商加价压缩")
        elif is_factory:
            reasons.append("源头工厂供应链更短，利润空间更可信")

        if profit_margin >= good_profit_margin:
            reasons.append("利润率达到健康区间")
        elif profit_margin < 0.2:
            risks.append("利润率偏低，价格波动会快速侵蚀利润")

        if roi >= good_roi:
            reasons.append("ROI 表现较好")
        elif roi < 0.5:
            risks.append("ROI 偏低，投放放大空间有限")

        return ScorePluginResult(
            plugin_name=self.name,
            score=self.clamp_score(score),
            details={
                "purchase_price": round(purchase_price, 2),
                "logistics_cost": round(logistics_cost, 2),
                "packaging_cost": round(packaging_cost, 2),
                "platform_commission": round(commission, 2),
                "suggested_price": round(suggested_price, 2),
                "suggested_price_source": suggested_price_source,
                "estimated_profit": round(estimated_profit, 2),
                "profit_margin": round(profit_margin, 4),
                "roi": round(roi, 4),
                "is_factory": is_factory,
                "non_factory_profit_score_penalty": non_factory_penalty,
            },
            reasons=reasons,
            risks=risks,
        )


def calculate_suggested_price(
    purchase_price: float,
    logistics_cost: float,
    packaging_cost: float,
    commission_rate: float,
    rules: dict[str, object],
) -> float:
    """根据成本、目标利润率和风险缓冲计算建议售价。"""
    target_profit_margin = float(
        rules.get("target_profit_margin", rules.get("good_profit_margin", 0.35))
    )
    risk_buffer_rate = float(rules.get("risk_buffer_rate", 0.08))
    min_markup_rate = float(rules.get("min_markup_rate", 1.6))
    fallback_markup_rate = float(rules.get("markup_rate", 2.2))

    base_cost = max(purchase_price, 0) + max(logistics_cost, 0) + max(packaging_cost, 0)
    risk_buffer = base_cost * max(risk_buffer_rate, 0)

    denominator = 1 - max(commission_rate, 0) - max(target_profit_margin, 0)
    if denominator <= 0:
        raw_price = purchase_price * fallback_markup_rate
    else:
        raw_price = (base_cost + risk_buffer) / denominator

    min_price = purchase_price * min_markup_rate
    suggested_price = max(raw_price, min_price)
    return _round_up_to_retail_price(suggested_price)


def _round_up_to_retail_price(price: float) -> float:
    """将建议售价向上取到 0.1 元，避免利润被四舍五入压低。"""
    if price <= 0:
        return 0.0

    return round(math.ceil(price * 10) / 10, 2)


def _parse_price(price: str | None) -> float:
    """从字符串价格中提取第一个数值。"""
    if not price:
        return 0.0

    cleaned = ""
    for char in price:
        if char.isdigit() or char == ".":
            cleaned += char
        elif cleaned:
            break

    try:
        return float(cleaned)
    except ValueError:
        return 0.0
