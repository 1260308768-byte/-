"""价格评分插件。"""

from __future__ import annotations

from app.score_engine.base import BaseScorePlugin
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult
from app.score_engine.plugins.profit_score import _parse_price


class PriceScorePlugin(BaseScorePlugin):
    """评估价格吸引力、运费、包邮和价格稳定性。"""

    name = "price_score"
    display_name = "Price Score"
    version = "1.0.0"
    weight_key = "price_score"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """计算价格分数。"""
        rules = context.rules.get(self.name, {})
        product = context.product
        reasons: list[str] = []
        risks: list[str] = []
        score = float(rules.get("base_score", 50))

        purchase_price = product.purchase_price or _parse_price(product.price)
        shipping_fee = product.shipping_fee or 0
        market_price = product.suggested_price or purchase_price * float(
            rules.get("market_price_factor", 1.15)
        )
        price_rank_score = 0

        if market_price and purchase_price <= market_price:
            price_rank_score = 20
            reasons.append("采购价低于或接近市场参考价")
        else:
            risks.append("采购价相对市场参考价偏高")

        score += price_rank_score

        if product.free_shipping:
            score += float(rules.get("free_shipping_points", 15))
            reasons.append("商品支持包邮")
        elif shipping_fee <= 3:
            score += float(rules.get("low_shipping_points", 10))
            reasons.append("运费较低")

        # 当前 V1 无历史价格曲线，默认给保守稳定分。
        score += float(rules.get("price_stability_points", 15)) * 0.6

        return ScorePluginResult(
            plugin_name=self.name,
            score=self.clamp_score(score),
            details={
                "purchase_price": round(purchase_price, 2),
                "market_price": round(market_price, 2),
                "shipping_fee": round(shipping_fee, 2),
                "free_shipping": product.free_shipping,
                "price_rank_score": price_rank_score,
            },
            reasons=reasons,
            risks=risks,
        )

