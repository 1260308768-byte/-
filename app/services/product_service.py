"""商品业务服务模块。"""

from math import ceil
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.crawler.product_crawler import ProductCrawler
from app.database.db import SessionLocal
from app.models.product import Product
from app.services.product_filter_service import is_qualified_supply_product
from app.utils.logger import get_logger


logger = get_logger()


async def collect_and_save_products(db: Session, keyword: str) -> int:
    """采集指定关键词的商品并保存到数据库。"""
    crawler = ProductCrawler()
    crawled_products = await crawler.crawl(keyword)

    saved_count = 0
    filtered_count = 0
    for crawled_product in crawled_products:
        if not is_qualified_supply_product(crawled_product):
            filtered_count += 1
            continue

        # 商品链接为空时无法稳定去重，但仍允许保存基础信息。
        if crawled_product.product_url:
            existing_product = db.scalar(
                select(Product).where(
                    Product.keyword == crawled_product.keyword,
                    Product.product_url == crawled_product.product_url,
                )
            )
            if existing_product:
                continue

        product = Product(
            keyword=crawled_product.keyword,
            title=crawled_product.title,
            price=crawled_product.price,
            sales=crawled_product.sales,
            shop_name=crawled_product.shop_name,
            shop_level=crawled_product.shop_level,
            province=crawled_product.province,
            support_drop_shipping=crawled_product.support_drop_shipping,
            image_url=crawled_product.image_url,
            product_url=crawled_product.product_url,
        )
        db.add(product)
        saved_count += 1

    db.commit()
    logger.info(
        "商品保存完成，关键词：%s，新增数量：%s，过滤非一件代发数量：%s",
        keyword,
        saved_count,
        filtered_count,
    )
    return saved_count


async def collect_and_save_products_background(keyword: str) -> int:
    """后台采集指定关键词的商品并保存到数据库。"""
    db = SessionLocal()
    try:
        return await collect_and_save_products(db, keyword)
    except Exception:
        logger.exception("后台采集任务异常，关键词：%s", keyword)
        return 0
    finally:
        db.close()


def get_products_page(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
) -> dict[str, Any]:
    """分页查询商品列表。"""
    safe_page = max(page, 1)
    safe_page_size = max(page_size, 1)

    conditions = []
    conditions.append(Product.task_id.is_(None))
    if keyword:
        conditions.append(Product.keyword == keyword)

    count_statement = select(func.count()).select_from(Product)
    list_statement = select(Product).order_by(Product.created_at.desc())

    if conditions:
        count_statement = count_statement.where(*conditions)
        list_statement = list_statement.where(*conditions)

    total = db.scalar(count_statement) or 0
    total_pages = max(ceil(total / safe_page_size), 1)

    # 如果用户手动输入过大的页码，自动停留在最后一页。
    current_page = min(safe_page, total_pages)
    offset = (current_page - 1) * safe_page_size

    products = db.scalars(
        list_statement.offset(offset).limit(safe_page_size)
    ).all()

    return {
        "products": products,
        "page": current_page,
        "page_size": safe_page_size,
        "total": total,
        "total_pages": total_pages,
        "keyword": keyword,
    }


def get_library_products(db: Session) -> list[Product]:
    """查询商品库中的全部商品。"""
    return list(
        db.scalars(
            select(Product)
            .where(Product.task_id.is_(None))
            .order_by(Product.created_at.desc())
        )
    )


def clear_library_products(db: Session) -> int:
    """清空旧商品库记录，不影响 AI 选品任务结果。"""
    result = db.execute(delete(Product).where(Product.task_id.is_(None)))
    db.commit()
    deleted_count = result.rowcount or 0
    logger.info("旧商品库记录清理完成，删除数量：%s", deleted_count)
    return deleted_count


def delete_library_product(db: Session, product_id: int) -> bool:
    """删除商品库中的单个商品，不影响 AI 选品任务结果。"""
    result = db.execute(
        delete(Product).where(
            Product.id == product_id,
            Product.task_id.is_(None),
        )
    )
    db.commit()
    deleted = (result.rowcount or 0) > 0
    logger.info("商品库单个商品删除完成，商品ID：%s，是否删除：%s", product_id, deleted)
    return deleted


def delete_library_products(db: Session, product_ids: list[int]) -> int:
    """批量删除商品库商品，不影响 AI 选品任务结果。"""
    safe_ids = [product_id for product_id in product_ids if product_id > 0]
    if not safe_ids:
        return 0

    result = db.execute(
        delete(Product).where(
            Product.id.in_(safe_ids),
            Product.task_id.is_(None),
        )
    )
    db.commit()
    deleted_count = result.rowcount or 0
    logger.info("商品库批量删除完成，删除数量：%s", deleted_count)
    return deleted_count


def add_ai_product_to_library(db: Session, product_id: int) -> Product | None:
    """将 AI 选品结果商品加入用户商品库。"""
    source_product = db.get(Product, product_id)
    if not source_product:
        return None

    product_url = source_product.product_url
    if product_url and "/offer/900000000" in product_url:
        product_url = None

    if product_url:
        existing_product = db.scalar(
            select(Product).where(
                Product.task_id.is_(None),
                Product.product_url == product_url,
            )
        )
        if existing_product:
            return existing_product

    library_product = Product(
        keyword=source_product.keyword,
        title=source_product.title,
        price=source_product.price,
        purchase_price=source_product.purchase_price,
        sales=source_product.sales,
        sales_count=source_product.sales_count,
        sales_growth_rate=source_product.sales_growth_rate,
        favorite_count=source_product.favorite_count,
        review_count=source_product.review_count,
        positive_rate=source_product.positive_rate,
        stock=source_product.stock,
        stock_status=source_product.stock_status,
        shop_name=source_product.shop_name,
        shop_level=source_product.shop_level,
        province=source_product.province,
        city=source_product.city,
        support_drop_shipping=source_product.support_drop_shipping,
        support_oem=source_product.support_oem,
        support_logo_custom=source_product.support_logo_custom,
        moq=source_product.moq,
        shipping_fee=source_product.shipping_fee,
        free_shipping=source_product.free_shipping,
        suggested_price=source_product.suggested_price,
        packaging_cost=source_product.packaging_cost,
        platform_commission_rate=source_product.platform_commission_rate,
        image_url=source_product.image_url,
        product_url=product_url,
        last_updated_at=source_product.last_updated_at,
    )
    db.add(library_product)
    db.commit()
    db.refresh(library_product)
    logger.info("AI 商品加入商品库，源商品ID：%s，新商品ID：%s", product_id, library_product.id)
    return library_product
