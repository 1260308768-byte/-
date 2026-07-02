"""数据库初始化脚本。"""

from sqlalchemy import inspect
from sqlalchemy import text

from app.database.db import Base, engine
from app.models.ai_selection import Recommendation
from app.models.ai_selection import ScoreConfig
from app.models.ai_selection import ScoreLog
from app.models.ai_selection import ScoreRecord
from app.models.ai_selection import ScoreRule
from app.models.ai_selection import SelectionReport
from app.models.ai_selection import SelectionTask
from app.models.ai_selection import Supplier
from app.models.product import Product


def init_database() -> None:
    """创建项目所需的数据库表。"""
    # 引用所有模型，确保建表前已经被 SQLAlchemy 注册。
    _ = (
        Product,
        Recommendation,
        ScoreConfig,
        ScoreLog,
        ScoreRecord,
        ScoreRule,
        SelectionReport,
        SelectionTask,
        Supplier,
    )
    Base.metadata.create_all(bind=engine)
    ensure_product_columns()
    ensure_selection_task_columns()


def ensure_product_columns() -> None:
    """为旧版 products 表补齐 AI 选品需要的新字段。"""
    inspector = inspect(engine)
    if "products" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("products")}
    required_columns = {
        "task_id": "INTEGER",
        "supplier_id": "INTEGER",
        "platform": "VARCHAR(50) NOT NULL DEFAULT '1688'",
        "purchase_price": "FLOAT",
        "sales_count": "INTEGER",
        "sales_growth_rate": "FLOAT",
        "favorite_count": "INTEGER",
        "review_count": "INTEGER",
        "positive_rate": "FLOAT",
        "stock": "INTEGER",
        "stock_status": "VARCHAR(50)",
        "city": "VARCHAR(100)",
        "support_oem": "BOOLEAN NOT NULL DEFAULT 0",
        "support_logo_custom": "BOOLEAN NOT NULL DEFAULT 0",
        "moq": "INTEGER",
        "shipping_fee": "FLOAT",
        "free_shipping": "BOOLEAN NOT NULL DEFAULT 0",
        "suggested_price": "FLOAT",
        "packaging_cost": "FLOAT",
        "platform_commission_rate": "FLOAT",
        "last_updated_at": "DATETIME",
        "updated_at": "DATETIME",
    }

    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue

            # SQLite 支持简单 ADD COLUMN，当前字段都允许无损补齐。
            connection.execute(
                text(f"ALTER TABLE products ADD COLUMN {column_name} {column_type}")
            )

        # 旧数据补齐更新时间，避免 ORM 读取时出现空值。
        connection.execute(
            text("UPDATE products SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        )


def ensure_selection_task_columns() -> None:
    """为旧版 selection_tasks 表补齐搜索筛选字段。"""
    inspector = inspect(engine)
    if "selection_tasks" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("selection_tasks")
    }
    required_columns = {
        "min_purchase_price": "FLOAT",
        "max_purchase_price": "FLOAT",
    }

    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(
                text(f"ALTER TABLE selection_tasks ADD COLUMN {column_name} {column_type}")
            )


if __name__ == "__main__":
    # 允许直接执行 python -m app.database.init_db 初始化数据库。
    init_database()
