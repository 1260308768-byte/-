"""市场价格远程 Worker 任务服务。"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market_price import MarketLoginTask
from app.models.market_price import MarketPriceTask
from app.models.product import Product


def get_latest_market_price_task(
    db: Session,
    product_id: int,
) -> MarketPriceTask | None:
    """读取商品最近一次市场价格采集任务。"""
    return db.scalar(
        select(MarketPriceTask)
        .where(MarketPriceTask.product_id == product_id)
        .order_by(MarketPriceTask.created_at.desc())
    )


def queue_market_price_task(
    db: Session,
    product: Product,
    force_refresh: bool = False,
) -> MarketPriceTask:
    """创建或复用一个等待本地 Worker 执行的市场价格采集任务。"""
    latest_task = get_latest_market_price_task(db, product.id)
    if (
        latest_task
        and latest_task.status in {"pending", "collecting"}
        and not force_refresh
    ):
        return latest_task

    task = MarketPriceTask(
        product_id=product.id,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def claim_next_market_price_task(db: Session) -> tuple[MarketPriceTask, Product] | None:
    """领取一个等待本地 Worker 采集淘宝价格的任务。"""
    task = db.scalar(
        select(MarketPriceTask)
        .where(MarketPriceTask.status == "pending")
        .order_by(MarketPriceTask.created_at.asc())
    )
    if not task:
        return None

    product = db.get(Product, task.product_id)
    if not product:
        task.status = "failed"
        task.error_message = "商品不存在，无法采集市场价"
        task.finished_at = datetime.utcnow()
        db.commit()
        return None

    task.status = "collecting"
    task.started_at = datetime.utcnow()
    task.error_message = None
    db.commit()
    db.refresh(task)
    return task, product


def complete_market_price_task(
    db: Session,
    task_id: int,
    analysis: dict[str, Any],
) -> MarketPriceTask:
    """保存本地 Worker 回传的市场价格分析结果。"""
    task = db.get(MarketPriceTask, task_id)
    if not task:
        raise ValueError("市场价格任务不存在")

    task.status = "done"
    task.result_json = json.dumps(analysis, ensure_ascii=False)
    task.error_message = None
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def fail_market_price_task(
    db: Session,
    task_id: int,
    error_message: str,
) -> MarketPriceTask:
    """保存本地 Worker 回传的市场价格采集失败原因。"""
    task = db.get(MarketPriceTask, task_id)
    if not task:
        raise ValueError("市场价格任务不存在")

    task.status = "failed"
    task.error_message = error_message[:2000]
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def serialize_market_price_task(task: MarketPriceTask) -> dict[str, Any]:
    """把市场价格任务状态转换为 API 响应。"""
    result = json.loads(task.result_json) if task.result_json else None
    return {
        "status": "ok" if task.status == "done" else task.status,
        "task_id": task.id,
        "product_id": task.product_id,
        "analysis": result,
        "message": task.error_message,
    }


def build_market_worker_product_payload(product: Product) -> dict[str, Any]:
    """构建发给本地 Worker 的商品快照，避免 Worker 依赖服务器数据库。"""
    return {
        "id": product.id,
        "keyword": product.keyword,
        "title": product.title,
        "price": product.price,
        "purchase_price": product.purchase_price,
        "suggested_price": product.suggested_price,
        "image_url": product.image_url,
        "product_url": product.product_url,
    }


def queue_market_login_task(db: Session, platform: str) -> MarketLoginTask:
    """登记一个本地 Worker 打开平台登录浏览器的请求。"""
    task = MarketLoginTask(platform=platform or "taobao", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def claim_next_market_login_task(db: Session) -> MarketLoginTask | None:
    """领取一个等待本地 Worker 打开登录浏览器的请求。"""
    task = db.scalar(
        select(MarketLoginTask)
        .where(MarketLoginTask.status == "pending")
        .order_by(MarketLoginTask.created_at.asc())
    )
    if not task:
        return None

    task.status = "collecting"
    task.started_at = datetime.utcnow()
    task.error_message = None
    db.commit()
    db.refresh(task)
    return task


def complete_market_login_task(
    db: Session,
    task_id: int,
    result: dict[str, Any],
) -> MarketLoginTask:
    """保存本地 Worker 打开登录浏览器的结果。"""
    task = db.get(MarketLoginTask, task_id)
    if not task:
        raise ValueError("登录请求不存在")

    task.status = "done" if result.get("ready") else "failed"
    task.result_json = json.dumps(result, ensure_ascii=False)
    task.error_message = None if result.get("ready") else str(result.get("message") or "")
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def fail_market_login_task(
    db: Session,
    task_id: int,
    error_message: str,
) -> MarketLoginTask:
    """保存本地 Worker 打开登录浏览器失败原因。"""
    task = db.get(MarketLoginTask, task_id)
    if not task:
        raise ValueError("登录请求不存在")

    task.status = "failed"
    task.error_message = error_message[:2000]
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task
