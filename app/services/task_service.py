"""采集任务状态服务模块。"""

from dataclasses import dataclass
from datetime import datetime
import asyncio
import uuid

from app.services.product_service import collect_and_save_products_background
from app.utils.logger import get_logger


logger = get_logger()


@dataclass
class CrawlTask:
    """采集任务状态。"""

    task_id: str
    keyword: str
    status: str
    saved_count: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None = None


TASKS: dict[str, CrawlTask] = {}


def create_crawl_task(keyword: str) -> CrawlTask:
    """创建采集任务并异步执行。"""
    task = CrawlTask(
        task_id=uuid.uuid4().hex,
        keyword=keyword,
        status="running",
        saved_count=0,
        error=None,
        created_at=datetime.utcnow(),
    )
    TASKS[task.task_id] = task
    asyncio.create_task(run_crawl_task(task.task_id))
    return task


async def run_crawl_task(task_id: str) -> None:
    """执行采集任务并更新状态。"""
    task = TASKS[task_id]
    try:
        task.saved_count = await collect_and_save_products_background(task.keyword)
        task.status = "done"
    except Exception as exc:
        logger.exception("采集任务失败，任务ID：%s", task_id)
        task.error = str(exc)
        task.status = "failed"
    finally:
        task.finished_at = datetime.utcnow()


def get_crawl_task(task_id: str) -> CrawlTask | None:
    """根据任务 ID 获取采集任务。"""
    return TASKS.get(task_id)
