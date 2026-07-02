"""AI 选品服务测试脚本。"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


# 允许直接执行 python tests/ai_selection_test.py 时导入 app 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app.services.ai_selection_service as ai_selection_service
from app.crawler.product_crawler import CrawledProduct
from app.database.db import Base
from app.models.ai_selection import Recommendation
from app.models.ai_selection import ScoreRecord
from app.models.ai_selection import SelectionReport
from app.models.ai_selection import SelectionTask
from app.models.ai_selection import Supplier
from app.models.product import Product


class FakeCrawler:
    """用于测试的假采集器。"""

    def __init__(self, max_products: int | None = None) -> None:
        """初始化假采集器。"""
        self.max_products = max_products or 60

    async def crawl(self, keyword: str) -> list[CrawledProduct]:
        """返回少量商品，让服务层自动补足样本。"""
        return [
            CrawledProduct(
                keyword=keyword,
                title="测试收纳盒",
                price="9.9",
                sales="1200件",
                shop_name="测试源头工厂",
                shop_level="实力商家",
                province="浙江",
                support_drop_shipping=True,
                image_url=None,
                product_url="https://detail.1688.com/offer/100000001.html",
            )
        ]


def create_test_session() -> Session:
    """创建内存 SQLite 测试会话。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def test_run_ai_selection_task() -> None:
    """测试 AI 选品完整流程。"""
    db = create_test_session()
    original_crawler = ai_selection_service.ProductCrawler
    ai_selection_service.ProductCrawler = FakeCrawler

    try:
        task = asyncio.run(
            ai_selection_service.run_ai_selection_task(
                db=db,
                keyword="收纳盒",
                pages=1,
                top_count=20,
            )
        )

        assert task.status == "done"
        assert db.query(SelectionTask).count() == 1
        product_count = db.query(Product).count()
        assert product_count >= 1
        assert db.query(Supplier).count() > 0
        assert db.query(ScoreRecord).count() == product_count
        assert db.query(Recommendation).count() == min(20, product_count)
        assert db.query(SelectionReport).count() == 1
    finally:
        ai_selection_service.ProductCrawler = original_crawler
        db.close()


def test_purchase_price_search_filter() -> None:
    """测试创建任务时的采购价搜索筛选。"""
    task = SelectionTask(
        keyword="收纳盒",
        min_purchase_price=5,
        max_purchase_price=10,
    )

    assert ai_selection_service._matches_task_purchase_price_filter(task, 5)
    assert ai_selection_service._matches_task_purchase_price_filter(task, 9.9)
    assert not ai_selection_service._matches_task_purchase_price_filter(task, 4.99)
    assert not ai_selection_service._matches_task_purchase_price_filter(task, 10.01)


def main() -> None:
    """运行 AI 选品服务测试。"""
    test_run_ai_selection_task()
    test_purchase_price_search_filter()
    print("AI 选品服务测试通过")


if __name__ == "__main__":
    main()
