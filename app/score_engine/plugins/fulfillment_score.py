"""履约评分插件。"""

from __future__ import annotations

from app.score_engine.base import BaseScorePlugin
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult


class FulfillmentScorePlugin(BaseScorePlugin):
    """评估发货速度、库存、售后、订单处理和响应时间。"""

    name = "fulfillment_score"
    display_name = "Fulfillment Score"
    version = "1.0.0"
    weight_key = "fulfillment_score"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """计算履约分数。"""
        rules = context.rules.get(self.name, {})
        supplier = context.supplier
        product = context.product
        reasons: list[str] = []
        risks: list[str] = []
        details: dict[str, object] = {}
        score = float(rules.get("base_score", 35))

        ships_in_48h = bool(supplier and supplier.ships_in_48h)
        response_speed = supplier.response_speed if supplier else None
        stock_stable = product.stock_status == "stable" or (product.stock or 0) >= 500

        details.update(
            {
                "ships_in_48h": ships_in_48h,
                "response_speed": response_speed,
                "stock_stable": stock_stable,
            }
        )

        if ships_in_48h:
            score += float(rules.get("ships_48h_points", 20))
            reasons.append("供应商支持 48 小时发货")
        else:
            risks.append("发货时效信息不足")

        if stock_stable:
            score += float(rules.get("stock_stable_points", 15))
            reasons.append("库存稳定性较好")

        if product.support_drop_shipping or (supplier and supplier.support_drop_shipping):
            score += float(rules.get("order_process_points", 10))
            reasons.append("支持一件代发，订单处理链路更轻")

        if response_speed is not None and response_speed >= 0.8:
            score += float(rules.get("fast_response_points", 10))
            reasons.append("供应商响应速度较好")

        # V1 暂无售后指标，默认给中性分。
        score += float(rules.get("after_sales_points", 10)) * 0.5

        return ScorePluginResult(
            plugin_name=self.name,
            score=self.clamp_score(score),
            details=details,
            reasons=reasons,
            risks=risks,
        )

