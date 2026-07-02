"""服务层测试脚本。"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


# 允许直接执行 python tests/service_test.py 时导入 app 包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app.services.product_service as product_service
from app.crawler.product_crawler import CrawledProduct, ProductCrawler
from app.database.db import Base
from app.models.product import Product


class FakeCrawler:
    """用于测试的假采集器。"""

    async def crawl(self, keyword: str) -> list[CrawledProduct]:
        """返回固定商品数据，避免测试访问外部网站。"""
        return [
            CrawledProduct(
                keyword=keyword,
                title="桌面收纳盒",
                price="9.90",
                sales="100件",
                shop_name="测试工厂",
                shop_level="源头工厂",
                province="浙江",
                support_drop_shipping=True,
                image_url="https://example.com/image.jpg",
                product_url="https://detail.1688.com/offer/123.html",
            ),
            CrawledProduct(
                keyword=keyword,
                title="桌面收纳盒重复",
                price="9.90",
                sales="100件",
                shop_name="测试工厂",
                shop_level="源头工厂",
                province="浙江",
                support_drop_shipping=True,
                image_url="https://example.com/image.jpg",
                product_url="https://detail.1688.com/offer/123.html",
            ),
        ]


def create_test_session() -> Session:
    """创建内存 SQLite 测试会话。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def test_collect_and_save_products() -> None:
    """测试采集保存和链接去重。"""
    db = create_test_session()
    original_crawler = product_service.ProductCrawler
    product_service.ProductCrawler = FakeCrawler

    try:
        first_count = asyncio.run(
            product_service.collect_and_save_products(db, "收纳盒")
        )
        second_count = asyncio.run(
            product_service.collect_and_save_products(db, "收纳盒")
        )

        products = db.query(Product).all()
        assert first_count == 1
        assert second_count == 0
        assert len(products) == 1
        assert products[0].shop_name == "测试工厂"
        assert products[0].support_drop_shipping is True
    finally:
        product_service.ProductCrawler = original_crawler
        db.close()


def test_get_products_page() -> None:
    """测试商品分页查询。"""
    db = create_test_session()
    for index in range(12):
        db.add(
            Product(
                keyword="收纳盒",
                title=f"商品 {index}",
                product_url=f"https://detail.1688.com/offer/{index}.html",
            )
        )
    db.commit()

    page_data = product_service.get_products_page(db, page=2, page_size=10)

    assert page_data["total"] == 12
    assert page_data["page"] == 2
    assert page_data["total_pages"] == 2
    assert len(page_data["products"]) == 2
    db.close()


def test_crawler_normalize_filters_invalid_products() -> None:
    """测试采集结果清洗会过滤风控反馈链接。"""
    crawler = ProductCrawler()
    products = crawler._normalize_products(
        "收纳盒",
        [
            {
                "title": "点我反馈",
                "product_url": "https://s.1688.com/feedback?x5secdata=abc",
            },
            {
                "title": "有效商品",
                "product_url": "https://detail.1688.com/offer/456.html",
                "price": "12.00",
                "sales": "20件",
                "shop_name": "测试商行",
                "shop_level": "3年",
                "province": "广东",
                "support_drop_shipping": False,
                "image_url": "https://example.com/456.jpg",
            },
        ],
    )

    assert len(products) == 1
    assert products[0].title == "有效商品"
    assert products[0].province == "广东"


def main() -> None:
    """运行服务层测试。"""
    test_collect_and_save_products()
    test_get_products_page()
    test_crawler_normalize_filters_invalid_products()
    print("服务层测试通过")


if __name__ == "__main__":
    main()
