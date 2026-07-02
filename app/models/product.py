"""商品数据模型。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class Product(Base):
    """商品表模型。"""

    __tablename__ = "products"

    # 商品主键 ID。
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # AI 选品任务 ID，旧采集数据允许为空。
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 供应商 ID，旧采集数据允许为空。
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 商品来源平台，当前默认 1688，后续可扩展到其他平台。
    platform: Mapped[str] = mapped_column(String(50), default="1688", nullable=False)

    # 用户输入的搜索关键词，例如：收纳盒。
    keyword: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # 商品标题。
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 商品价格保留为字符串，兼容价格区间、起批价等 1688 常见格式。
    price: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 采购价数值，用于利润和价格评分。
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 销量通常包含中文单位或描述，因此保留为字符串。
    sales: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 销量数值，用于商品评分。
    sales_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 销量增长率，暂由规则或后续采集补充。
    sales_growth_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 收藏人数。
    favorite_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 评价数量。
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 好评率，范围 0 到 1。
    positive_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 库存数量或估算库存。
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 库存状态，例如 stable、unknown。
    stock_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 店铺名称。
    shop_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 店铺等级。
    shop_level: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 商品或店铺所在省份。
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 城市信息。
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 是否支持一件代发。
    support_drop_shipping: Mapped[bool] = mapped_column(Boolean, default=False)

    # 是否支持 OEM。
    support_oem: Mapped[bool] = mapped_column(Boolean, default=False)

    # 是否支持 LOGO 定制。
    support_logo_custom: Mapped[bool] = mapped_column(Boolean, default=False)

    # 最小起订量。
    moq: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 运费。
    shipping_fee: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 是否包邮。
    free_shipping: Mapped[bool] = mapped_column(Boolean, default=False)

    # 建议售价。
    suggested_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 包装成本。
    packaging_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 平台佣金率，范围 0 到 1。
    platform_commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 商品主图地址。
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 商品详情页地址。
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 商品更新时间。
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 数据入库时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # 数据更新时间。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
