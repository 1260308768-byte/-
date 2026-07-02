"""竞争指数预留插件。"""

from __future__ import annotations

from app.score_engine.base import BaseScorePlugin
from app.score_engine.base import ScoreContext
from app.score_engine.base import ScorePluginResult


class CompetitionScorePlugin(BaseScorePlugin):
    """V1 预留竞争指数插件，默认不参与总分。"""

    name = "competition_score"
    display_name = "Competition Score"
    version = "0.1.0"
    enabled = False
    included_in_total = False
    weight_key = "competition_score"

    def calculate(self, context: ScoreContext) -> ScorePluginResult:
        """返回预留插件的占位评分。"""
        return ScorePluginResult(
            plugin_name=self.name,
            score=0,
            details={"reserved": True},
            reasons=["竞争指数插件已预留，V1 暂不启用"],
            risks=[],
        )

