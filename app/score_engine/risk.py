"""AI 选品风险识别模块。"""

from __future__ import annotations

from typing import Any

from app.models.product import Product


def build_risk_tips(
    product: Product,
    ai_score: float,
    roi: float | None,
    estimated_profit: float | None,
    rules: dict[str, Any],
) -> list[str]:
    """根据商品和评分结果生成风险提示。"""
    risk_rules = rules.get("risk", {})
    risks: list[str] = []

    if ai_score < float(risk_rules.get("low_ai_score", 60)):
        risks.append("AI Score 偏低，需要谨慎验证供应链和市场需求")

    if roi is not None and roi < float(risk_rules.get("low_roi", 0.5)):
        risks.append("ROI 偏低，投放和平台成本上升时容易压缩利润")

    if estimated_profit is not None and estimated_profit <= 0:
        risks.append("预计利润为负，不建议进入 Top 推荐池")

    if product.sales_count is not None and product.sales_count < int(
        risk_rules.get("low_sales", 100)
    ):
        risks.append("销量基础较弱，需要进一步验证真实需求")

    if product.moq is not None and product.moq > int(risk_rules.get("high_moq", 100)):
        risks.append("MOQ 较高，可能增加首批压货风险")

    if not risks:
        risks.append("未发现明显高风险项，仍建议小批量测试")

    return risks

