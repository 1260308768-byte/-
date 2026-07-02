"""AI Score 插件注册器。"""

from __future__ import annotations

from app.score_engine.base import ScorePlugin
from app.score_engine.plugins.fulfillment_score import FulfillmentScorePlugin
from app.score_engine.plugins.price_score import PriceScorePlugin
from app.score_engine.plugins.product_score import ProductScorePlugin
from app.score_engine.plugins.profit_score import ProfitScorePlugin
from app.score_engine.plugins.supplier_score import SupplierScorePlugin


class PluginRegistry:
    """管理评分插件注册和加载。"""

    def __init__(self) -> None:
        """初始化默认插件列表。"""
        self._plugins: dict[str, ScorePlugin] = {}
        self.register(SupplierScorePlugin())
        self.register(ProductScorePlugin())
        self.register(ProfitScorePlugin())
        self.register(PriceScorePlugin())
        self.register(FulfillmentScorePlugin())

    def register(self, plugin: ScorePlugin) -> None:
        """注册一个评分插件。"""
        self._plugins[plugin.name] = plugin

    def get_enabled_plugins(self) -> list[ScorePlugin]:
        """获取启用中的插件。"""
        return [plugin for plugin in self._plugins.values() if plugin.enabled]

    def get_all_plugins(self) -> list[ScorePlugin]:
        """获取全部已注册插件。"""
        return list(self._plugins.values())

