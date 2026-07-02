"""本地采集 Worker：从服务器领取任务，在本机采集 1688 后回传结果。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from app.config.settings import BASE_DIR
from app.crawler.product_crawler import ProductCrawler


load_dotenv(BASE_DIR / ".env")

SERVER_URL = os.getenv("WORKER_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
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


async def main() -> None:
    """持续轮询服务器任务。"""
    if not WORKER_TOKEN:
        raise RuntimeError("请先在 .env 中配置 WORKER_TOKEN")

    print(f"[worker] 本地采集 Worker 已启动，服务器：{SERVER_URL}")
    while True:
        try:
            response = request_json("GET", "/api/worker/tasks/next")
            if response.get("status") == "empty":
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            task = response.get("task") or {}
            task_id = int(task["id"])
            try:
                await run_task(task)
            except Exception as task_error:
                print(f"[worker] 任务失败：{task_id}，{task_error}")
                mark_task_failed(task_id, task_error)
        except (HTTPError, URLError, TimeoutError) as network_error:
            print(f"[worker] 暂时无法连接服务器：{network_error}")
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("[worker] 已退出")
            return


if __name__ == "__main__":
    asyncio.run(main())
