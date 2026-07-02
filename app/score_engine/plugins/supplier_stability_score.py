"""供应稳定性预留插件。"""

from __future__ import annotations

from app.score_engine.base import BaseScorePlugin
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult


class SupplierStabilityScorePlugin(BaseScorePlugin):
    """V1 预留供应稳定性插件，默认不参与总分。"""

    name = "supplier_stability_score"
    display_name = "Supplier Stability Score"
    version = "0.1.0"
    enabled = False
    included_in_total = False
    weight_key = "supplier_stability_score"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """返回预留插件的占位评分。"""
        return ScorePluginResult(
            plugin_name=self.name,
            score=0,
            details={"reserved": True},
            reasons=["供应稳定性插件已预留，V1 暂不启用"],
            risks=[],
        )
