"""商品评分插件。"""

from __future__ import annotations

from datetime import datetime

from app.score_engine.base import BaseScorePlugin
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult


class ProductScorePlugin(BaseScorePlugin):
    """评估商品需求、活跃度、评价和库存状态。"""

    name = "product_score"
    display_name = "Product Score"
    version = "1.0.0"
    weight_key = "product_score"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """计算商品分数。"""
        rules = context.rules.get(self.name, {})
        product = context.product
        details: dict[str, object] = {}
        reasons: list[str] = []
        risks: list[str] = []
        score = float(rules.get("base_score", 15))

        sales_count = product.sales_count or 0
        sales_growth_rate = product.sales_growth_rate or 0
        favorite_count = product.favorite_count or 0
        review_count = product.review_count or 0
        positive_rate = product.positive_rate or 0
        stock = product.stock or 0
        high_sales = int(rules.get("high_sales", 10000))
        good_sales = int(rules.get("good_sales", 1000))

        details.update(
            {
                "sales_count": sales_count,
                "sales_growth_rate": sales_growth_rate,
                "favorite_count": favorite_count,
                "review_count": review_count,
                "positive_rate": positive_rate,
                "stock": stock,
                "stock_status": product.stock_status,
            }
        )

        if sales_count >= high_sales:
            score += float(rules.get("sales_points", 25))
            reasons.append("销量表现强，需求基础较好")
        elif sales_count >= good_sales:
            score += float(rules.get("sales_points", 25)) * 0.7
            reasons.append("销量达到可验证水平")
        elif sales_count > 0:
            score += float(rules.get("sales_points", 25)) * 0.35
        else:
            risks.append("销量数据不足，需要谨慎验证需求")

        if sales_growth_rate > 0:
            score += min(sales_growth_rate / 0.5, 1) * float(
                rules.get("sales_growth_points", 15)
            )
            reasons.append("销量增长率为正，具备上升趋势")

        score += min(favorite_count / 1000, 1) * float(
            rules.get("favorite_points", 10)
        )
        score += min(review_count / 500, 1) * float(rules.get("review_points", 10))

        if positive_rate >= float(rules.get("good_positive_rate", 0.95)):
            score += float(rules.get("positive_rate_points", 10))
            reasons.append("好评率较高，用户反馈基础较好")

        if product.stock_status == "stable" or stock >= 500:
            score += float(rules.get("stock_points", 10))
            reasons.append("库存状态相对稳定")

        if product.last_updated_at:
            days = (datetime.utcnow() - product.last_updated_at).days
            details["days_since_update"] = days
            if days <= 30:
                score += float(rules.get("updated_points", 5))
                reasons.append("商品近期有更新，活跃度较好")

        return ScorePluginResult(
            plugin_name=self.name,
            score=self.clamp_score(score),
            details=details,
            reasons=reasons,
            risks=risks,
        )

