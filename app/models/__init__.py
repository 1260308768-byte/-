"""数据模型模块包。"""

from app.models.ai_selection import Recommendation
from app.models.ai_selection import ScoreConfig
from app.models.ai_selection import ScoreLog
from app.models.ai_selection import ScoreRecord
from app.models.ai_selection import ScoreRule
from app.models.ai_selection import SelectionReport
from app.models.ai_selection import SelectionTask
from app.models.ai_selection import Supplier
from app.models.product import Product

__all__ = [
    "Product",
    "Recommendation",
    "ScoreConfig",
    "ScoreLog",
    "ScoreRecord",
    "ScoreRule",
    "SelectionReport",
    "SelectionTask",
    "Supplier",
]
