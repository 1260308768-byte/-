"""AI 推荐等级计算模块。"""

from __future__ import annotations

from typing import Any


def get_recommendation_level(ai_score: float, rules: dict[str, Any]) -> str:
    """根据 AI Score 返回推荐等级。"""
    levels = rules.get("recommendation_levels", {})
    sorted_levels = sorted(
        levels.items(),
        key=lambda item: float(item[1].get("min", 0)),
        reverse=True,
    )

    for level, config in sorted_levels:
        if ai_score >= float(config.get("min", 0)):
            return f"{level}级：{config.get('label', '')}"

    return "D级：不推荐"

