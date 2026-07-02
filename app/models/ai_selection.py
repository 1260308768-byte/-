"""AI 选品相关数据模型。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class SelectionTask(Base):
    """AI 选品任务表。"""

    __tablename__ = "selection_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    keyword: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    total_pages: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    total_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deduped_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deduped_suppliers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    top_count: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    min_purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Supplier(Base):
    """供应商表。"""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    platform: Mapped[str] = mapped_column(String(50), default="1688", nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    shop_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    shop_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_factory: Mapped[bool] = mapped_column(Boolean, default=False)
    is_powerful_merchant: Mapped[bool] = mapped_column(Boolean, default=False)
    has_deep_factory_inspection: Mapped[bool] = mapped_column(Boolean, default=False)
    trustpass_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shop_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    repurchase_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    ships_in_48h: Mapped[bool] = mapped_column(Boolean, default=False)
    support_drop_shipping: Mapped[bool] = mapped_column(Boolean, default=False)
    support_oem: Mapped[bool] = mapped_column(Boolean, default=False)
    support_logo_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ScoreConfig(Base):
    """AI Score 配置表。"""

    __tablename__ = "score_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    config_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    config_value_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ScoreRule(Base):
    """AI Score 规则表。"""

    __tablename__ = "score_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plugin_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_value_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ScoreRecord(Base):
    """商品评分记录表。"""

    __tablename__ = "score_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ai_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    recommendation_level: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    product_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    profit_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    price_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fulfillment_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    competition_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    supplier_stability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    risk_detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason_detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    weights_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    rules_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class Recommendation(Base):
    """AI 推荐结果表。"""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    score_record_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_level: Mapped[str] = mapped_column(String(50), nullable=False)
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class SelectionReport(Base):
    """AI 选品分析报告表。"""

    __tablename__ = "selection_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    top_products_json: Mapped[str] = mapped_column(Text, nullable=False)
    score_distribution_json: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_analysis_json: Mapped[str] = mapped_column(Text, nullable=False)
    price_analysis_json: Mapped[str] = mapped_column(Text, nullable=False)
    risk_analysis_json: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ScoreLog(Base):
    """评分过程日志表。"""

    __tablename__ = "score_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plugin_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    input_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    score_result_json: Mapped[str] = mapped_column(Text, nullable=False)
    weight_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
