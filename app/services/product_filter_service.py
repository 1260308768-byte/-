"""商品采集过滤规则服务。"""

from __future__ import annotations

from typing import Any


SOURCE_FACTORY_KEYWORDS = (
    "源头工厂",
    "超级工厂",
)


def is_source_factory_product(crawled_product: Any) -> bool:
    """判断采集商品是否具备明确的 1688 源头工厂标识。"""
    shop_level = str(getattr(crawled_product, "shop_level", "") or "")
    return any(keyword in shop_level for keyword in SOURCE_FACTORY_KEYWORDS)


def is_drop_shipping_product(crawled_product: Any) -> bool:
    """判断采集商品是否明确支持一件代发。"""
    return bool(getattr(crawled_product, "support_drop_shipping", False))


def is_qualified_supply_product(crawled_product: Any) -> bool:
    """判断商品是否满足当前采集条件：支持一件代发。"""
    return is_drop_shipping_product(crawled_product)
