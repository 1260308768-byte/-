"""AI 选品分析报告生成模块。"""

from __future__ import annotations

from statistics import mean
from typing import Any


def build_report_markdown(
    keyword: str,
    recommendations: list[dict[str, Any]],
    score_records: list[dict[str, Any]],
) -> str:
    """生成 AI 选品分析报告 Markdown。"""
    avg_score = round(mean([item["ai_score"] for item in score_records]), 2) if score_records else 0
    top_lines = []

    for item in recommendations[:20]:
        product = item["product"]
        score = item["score_record"]
        rank = item.get("rank")
        if rank is None and item.get("recommendation"):
            rank = item["recommendation"].rank
        top_lines.append(
            f"- {rank}. {product.title or '未命名商品'}：AI Score {score.ai_score}，"
            f"预计利润 {score.estimated_profit or 0:.2f}，ROI {score.roi or 0:.2f}"
        )

    top_text = "\n".join(top_lines) if top_lines else "- 暂无推荐商品"

    return (
        f"# {keyword} AI选品分析报告\n\n"
        f"## 总览\n\n"
        f"- 平均 AI Score：{avg_score}\n"
        f"- 推荐商品数量：{len(recommendations)}\n"
        f"- 策略：优先选择供应商稳定、利润率健康、支持一件代发的商品。\n\n"
        f"## Top20 推荐\n\n"
        f"{top_text}\n\n"
        f"## 风险提示\n\n"
        f"- 1688 页面数据存在动态变化，建议在实际采购前二次核验价格、库存和发货能力。\n"
        f"- 当前 V1 评分以可采集字段和默认规则为主，后续可接入竞争指数与供应稳定性插件。\n"
    )
