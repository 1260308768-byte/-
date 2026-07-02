"""项目日志配置模块。"""

import logging
from logging.handlers import RotatingFileHandler

from app.config.settings import BASE_DIR, get_settings


def get_logger() -> logging.Logger:
    """获取项目统一日志对象。"""
    settings = get_settings()
    logger = logging.getLogger("product_finder")

    # 避免模块多次导入时重复添加 handler，导致日志重复写入。
    if logger.handlers:
        return logger

    log_path = BASE_DIR / settings.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger

