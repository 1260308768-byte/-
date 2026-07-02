"""数据库连接与会话管理模块。"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import get_settings


# 读取统一配置，避免数据库地址散落在多个文件里。
settings = get_settings()

# SQLite 文件数据库需要先确保父目录存在。
if settings.database_url.startswith("sqlite:///"):
    database_path = settings.database_url.replace("sqlite:///", "", 1)
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)

# SQLite 需要关闭同线程检查，方便 FastAPI 请求中复用会话。
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

# 数据库会话工厂，后续路由和服务层都通过它创建 Session。
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    """所有 SQLAlchemy 模型的基类。"""


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话，并在请求结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
