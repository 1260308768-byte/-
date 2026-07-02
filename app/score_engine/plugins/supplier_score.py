"""供应商评分插件。"""

from __future__ import annotations

from app.score_engine.base import BaseScorePlugin
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult


class SupplierScorePlugin(BaseScorePlugin):
    """评估供应商资质、履约基础和定制能力。"""

    name = "supplier_score"
    display_name = "Supplier Score"
    version = "1.0.0"
    weight_key = "supplier_score"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """计算供应商分数。"""
        rules = context.rules.get(self.name, {})
        supplier = context.supplier
        product = context.product
        details: dict[str, object] = {}
        reasons: list[str] = []
        risks: list[str] = []
        score = float(rules.get("base_score", 20))

        if supplier is None:
            risks.append("供应商信息不足，供应商评分保守处理")
            return ScorePluginResult(
                plugin_name=self.name,
                score=self.clamp_score(score),
                details={"missing_supplier": True},
                reasons=reasons,
                risks=risks,
            )

        score += self.add_boolean_score(
            supplier.is_factory,
            float(rules.get("factory_points", 12)),
            "供应商具备源头工厂特征",
            "is_factory",
            details,
            reasons,
        )
        score += self.add_boolean_score(
            supplier.is_powerful_merchant,
            float(rules.get("powerful_merchant_points", 10)),
            "店铺具备实力商家标识",
            "is_powerful_merchant",
            details,
            reasons,
        )
        score += self.add_boolean_score(
            supplier.has_deep_factory_inspection,
            float(rules.get("deep_factory_points", 10)),
            "供应商具备深度验厂信息",
            "has_deep_factory_inspection",
            details,
            reasons,
        )
        score += self.add_boolean_score(
            supplier.ships_in_48h,
            float(rules.get("ships_48h_points", 6)),
            "支持 48 小时发货",
            "ships_in_48h",
            details,
            reasons,
        )
        score += self.add_boolean_score(
            supplier.support_drop_shipping or product.support_drop_shipping,
            float(rules.get("drop_shipping_points", 5)),
            "支持一件代发，适合低库存测试",
            "support_drop_shipping",
            details,
            reasons,
        )
        score += self.add_boolean_score(
            supplier.support_oem or product.support_oem,
            float(rules.get("oem_points", 4)),
            "支持 OEM，后续可做差异化",
            "support_oem",
            details,
            reasons,
        )
        score += self.add_boolean_score(
            supplier.support_logo_custom or product.support_logo_custom,
            float(rules.get("logo_custom_points", 3)),
            "支持 LOGO 定制",
            "support_logo_custom",
            details,
            reasons,
        )

        trust_years = supplier.trustpass_years or 0
        open_years = supplier.open_years or 0
        rating = supplier.shop_rating or 0
        repurchase = supplier.repurchase_rate or 0
        response = supplier.response_speed or 0
        moq = product.moq or 1

        details.update(
            {
                "trustpass_years": trust_years,
                "open_years": open_years,
                "shop_rating": rating,
                "repurchase_rate": repurchase,
                "response_speed": response,
                "moq": moq,
            }
        )

        score += min(trust_years / 5, 1) * float(rules.get("trustpass_points", 10))
        score += min(open_years / 5, 1) * float(rules.get("open_years_points", 8))
        score += min(rating / 5, 1) * float(rules.get("rating_points", 10))
        score += min(repurchase / 0.3, 1) * float(rules.get("repurchase_points", 6))
        score += min(response / 1, 1) * float(rules.get("response_points", 6))

        if moq <= int(rules.get("max_good_moq", 10)):
            score += float(rules.get("moq_points", 4))
            reasons.append("MOQ 较低，适合小批量验证")
        else:
            risks.append("MOQ 偏高，可能增加压货风险")

        return ScorePluginResult(
            plugin_name=self.name,
            score=self.clamp_score(score),
            details=details,
            reasons=reasons,
            risks=risks,
        )

