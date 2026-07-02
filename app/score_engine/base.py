"""AI Score 插件基类与数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.ai_selection import Supplier
from app.models.product import Product


@dataclass(slots=True)
class ScoreContext:
    """评分上下文，承载商品、供应商和规则配置。"""

    product: Product
    supplier: Supplier | None
    rules: dict[str, Any]
    settings: dict[str, Any]


@dataclass(slots=True)
class ScorePluginResult:
    """单个评分插件的输出结果。"""

    plugin_name: str
    score: float
    max_score: float = 100
    weighted_score: float = 0
    details: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


class ScorePlugin(Protocol):
    """评分插件协议，所有插件都遵循这个接口。"""

    name: str
    display_name: str
    version: str
    enabled: bool
    included_in_total: bool
    weight_key: str

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """根据评分上下文计算插件分数。"""


class BaseScorePlugin:
    """评分插件基础类，提供通用加分与限幅能力。"""

    name = "base"
    display_name = "Base Score"
    version = "1.0.0"
    enabled = True
    included_in_total = True
    weight_key = "base"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """计算插件分数，子类必须覆盖该方法。"""
        raise NotImplementedError

    @staticmethod
    def clamp_score(score: float) -> float:
        """将分数限制在 0 到 100 之间。"""
        return max(0, min(100, round(score, 2)))

    @staticmethod
    def add_boolean_score(
        enabled: bool,
        points: float,
        reason: str,
        detail_key: str,
        details: dict[str, Any],
        reasons: list[str],
    ) -> float:
        """根据布尔条件加分，并同步记录原因和明细。"""
        details[detail_key] = enabled
        if enabled:
            reasons.append(reason)
            return points
        return 0

