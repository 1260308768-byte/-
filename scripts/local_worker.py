"""本地采集 Worker：从服务器领取任务，在本机采集 1688 后回传结果。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import BASE_DIR
from app.crawler.product_crawler import ProductCrawler
from app.services.market_price_service import clear_market_price_cache
from app.services.market_price_service import collect_product_market_price
from app.services.market_price_service import open_market_login_browser
from app.services.market_price_service import serialize_market_price_analysis


load_dotenv(BASE_DIR / ".env")

SERVER_URL = os.getenv("WORKER_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
WORKER_CLIENT_ID = os.getenv("WORKER_CLIENT_ID", "").strip().lower()
POLL_INTERVAL_SECONDS = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用服务器 Worker API 并返回 JSON。"""
    body = None
    headers = {
        "Accept": "application/json",
        "X-Worker-Token": WORKER_TOKEN,
    }
    if WORKER_CLIENT_ID:
        headers["X-Worker-Client-ID"] = WORKER_CLIENT_ID
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    request = Request(
        f"{SERVER_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=60) as response:
        content = response.read().decode("utf-8")
    return json.loads(content) if content else {}


async def run_task(task: dict[str, Any]) -> None:
    """执行单个服务器任务并回传采集结果。"""
    task_id = int(task["id"])
    keyword = str(task["keyword"])
    pages = int(task.get("total_pages") or 10)
    target_count = min(max(pages * 60, 30), 600)
    crawler = ProductCrawler(max_products=target_count)

    print(f"[worker] 开始采集任务 {task_id}：{keyword}，目标 {target_count} 条")
    products = await crawler.crawl(keyword)
    payload = {"products": [asdict(product) for product in products]}
    result = request_json("POST", f"/api/worker/tasks/{task_id}/complete", payload)
    print(
        "[worker] 任务完成："
        f"{task_id}，采集 {len(products)} 条，服务器状态 {result.get('status')}"
    )


def mark_task_failed(task_id: int, error: Exception) -> None:
    """通知服务器当前任务采集失败。"""
    try:
        request_json(
            "POST",
            f"/api/worker/tasks/{task_id}/fail",
            {"error_message": str(error)},
        )
    except Exception as notify_error:
        print(f"[worker] 回传失败状态也失败：{notify_error}")


def build_market_product(product_payload: dict[str, Any]) -> SimpleNamespace:
    """把服务器下发的商品快照转换为市场价采集可读取的对象。"""
    return SimpleNamespace(
        id=int(product_payload.get("id") or 0),
        keyword=product_payload.get("keyword"),
        title=product_payload.get("title"),
        price=product_payload.get("price"),
        purchase_price=product_payload.get("purchase_price"),
        suggested_price=product_payload.get("suggested_price"),
        image_url=product_payload.get("image_url"),
        product_url=product_payload.get("product_url"),
    )


async def run_market_price_task(task: dict[str, Any]) -> None:
    """执行单个淘宝市场价格采集任务并回传前三条价格。"""
    task_id = int(task["id"])
    product = build_market_product(task.get("product") or {})
    print(f"[worker] 开始采集淘宝市场价：任务 {task_id}，商品 {product.id}")
    clear_market_price_cache(product.id)
    analysis = await collect_product_market_price(product)
    payload = {"analysis": serialize_market_price_analysis(analysis)}
    result = request_json(
        "POST",
        f"/api/worker/market-price-tasks/{task_id}/complete",
        payload,
    )
    print(
        "[worker] 淘宝市场价采集完成："
        f"任务 {task_id}，服务器状态 {result.get('status')}"
    )


def mark_market_price_task_failed(task_id: int, error: Exception) -> None:
    """通知服务器当前市场价格采集任务失败。"""
    try:
        request_json(
            "POST",
            f"/api/worker/market-price-tasks/{task_id}/fail",
            {"error_message": str(error)},
        )
    except Exception as notify_error:
        print(f"[worker] 市场价失败状态回传失败：{notify_error}")


async def run_market_login_task(task: dict[str, Any]) -> None:
    """在本机打开淘宝登录浏览器并把结果回传服务器。"""
    task_id = int(task["id"])
    platform = str(task.get("platform") or "taobao")
    print(f"[worker] 正在打开{platform}登录浏览器：任务 {task_id}")
    result = await open_market_login_browser(platform)
    request_json(
        "POST",
        f"/api/worker/market-login-tasks/{task_id}/complete",
        {"result": result},
    )
    print(f"[worker] 登录浏览器请求已处理：任务 {task_id}")


def mark_market_login_task_failed(task_id: int, error: Exception) -> None:
    """通知服务器当前登录浏览器请求失败。"""
    try:
        request_json(
            "POST",
            f"/api/worker/market-login-tasks/{task_id}/fail",
            {"error_message": str(error)},
        )
    except Exception as notify_error:
        print(f"[worker] 登录请求失败状态回传失败：{notify_error}")


async def try_run_market_login_task() -> bool:
    """尝试领取并执行一个市场平台登录请求。"""
    response = request_json("GET", "/api/worker/market-login-tasks/next")
    if response.get("status") == "empty":
        return False

    task = response.get("task") or {}
    task_id = int(task["id"])
    try:
        await run_market_login_task(task)
    except Exception as task_error:
        print(f"[worker] 登录浏览器请求失败：{task_id}，{task_error}")
        mark_market_login_task_failed(task_id, task_error)
    return True


async def try_run_market_price_task() -> bool:
    """尝试领取并执行一个淘宝市场价格采集任务。"""
    response = request_json("GET", "/api/worker/market-price-tasks/next")
    if response.get("status") == "empty":
        return False

    task = response.get("task") or {}
    task_id = int(task["id"])
    try:
        await run_market_price_task(task)
    except Exception as task_error:
        print(f"[worker] 市场价采集失败：{task_id}，{task_error}")
        mark_market_price_task_failed(task_id, task_error)
    return True


async def try_run_selection_task() -> bool:
    """尝试领取并执行一个 AI 选品采集任务。"""
    response = request_json("GET", "/api/worker/tasks/next")
    if response.get("status") == "empty":
        return False

    task = response.get("task") or {}
    task_id = int(task["id"])
    try:
        await run_task(task)
    except Exception as task_error:
        print(f"[worker] AI 选品采集失败：{task_id}，{task_error}")
        mark_task_failed(task_id, task_error)
    return True


async def main() -> None:
    """持续轮询服务器任务。"""
    if not WORKER_TOKEN:
        raise RuntimeError("请先在 .env 中配置 WORKER_TOKEN")
    if not WORKER_CLIENT_ID:
        raise RuntimeError("请先在 .env 中配置 WORKER_CLIENT_ID，例如 buyer-001")

    print(f"[worker] 本地采集 Worker 已启动，服务器：{SERVER_URL}，客户端：{WORKER_CLIENT_ID}")
    while True:
        try:
            handled = (
                await try_run_market_login_task()
                or await try_run_market_price_task()
                or await try_run_selection_task()
            )
            if not handled:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

        except (HTTPError, URLError, TimeoutError) as network_error:
            print(f"[worker] 暂时无法连接服务器：{network_error}")
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("[worker] 已退出")
            return


if __name__ == "__main__":
    asyncio.run(main())
