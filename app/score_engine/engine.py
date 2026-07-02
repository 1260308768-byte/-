"""AI Score 评分引擎。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.models.ai_selection import Supplier
from app.models.product import Product
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult
from app.score_engine.recommendation import get_recommendation_level
from app.score_engine.registry import PluginRegistry
from app.score_engine.risk import build_risk_tips
from app.score_engine.rules import DEFAULT_RULES
from app.score_engine.weights import DEFAULT_WEIGHTS
from app.score_engine.weights import normalize_weights


class ScoreEngine:
    """AI Score 核心引擎，负责加载插件、读取权重并汇总分数。"""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        rules: dict[str, Any] | None = None,
    ) -> None:
        """初始化评分引擎。"""
        self.registry = PluginRegistry()
        self.weights = normalize_weights(weights or DEFAULT_WEIGHTS)
        self.rules = rules or DEFAULT_RULES

    def calculate(self, product: Product, supplier: Supplier | None) -> dict[str, Any]:
        """计算单个商品的完整 AI Score。"""
        plugin_results: list[ScorePluginResult] = []
        context = ScoreContext(
            product=product,
            supplier=supplier,
            rules=self.rules,
            settings={},
        )

        total_score = 0.0
        for plugin in self.registry.get_enabled_plugins():
            result = plugin.calculate(context)
            weight = self.weights.get(plugin.weight_key, 0)
            result.weighted_score = round(result.score * weight, 2)
            plugin_results.append(result)

            if plugin.included_in_total:
                total_score += result.weighted_score

        ai_score = round(min(total_score, 100), 2)
        profit_result = next(
            (result for result in plugin_results if result.plugin_name == "profit_score"),
            None,
        )
        roi = profit_result.details.get("roi") if profit_result else None
        estimated_profit = (
            profit_result.details.get("estimated_profit") if profit_result else None
        )
        risks = build_risk_tips(
            product=product,
            ai_score=ai_score,
            roi=roi,
            estimated_profit=estimated_profit,
            rules=self.rules,
        )
        plugin_risks = [
            risk for result in plugin_results for risk in result.risks
        ]
        all_risks = list(dict.fromkeys([*plugin_risks, *risks]))

        return {
            "ai_score": ai_score,
            "recommendation_level": get_recommendation_level(ai_score, self.rules),
            "plugin_results": plugin_results,
            "plugin_result_dicts": [asdict(result) for result in plugin_results],
            "risks": all_risks,
            "reasons": [
                reason for result in plugin_results for reason in result.reasons
            ],
            "roi": roi,
            "estimated_profit": estimated_profit,
            "weights_snapshot": self.weights,
            "rules_snapshot": self.rules,
        }

