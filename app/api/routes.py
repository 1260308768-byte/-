"""FastAPI 路由定义模块。"""

import json
from typing import Any
from urllib.parse import quote_plus
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from app.database.db import get_db
from app.config.settings import get_settings
from app.crawler.product_crawler import CrawledProduct
from app.models.ai_selection import SelectionTask
from app.services.ai_selection_service import claim_next_worker_task
from app.services.ai_selection_service import complete_ai_selection_task_from_worker
from app.services.ai_selection_service import create_selection_task
from app.services.ai_selection_service import fail_ai_selection_task_from_worker
from app.services.ai_selection_service import get_selection_task
from app.services.ai_selection_service import get_task_recommendations
from app.services.ai_selection_service import get_task_report
from app.services.ai_selection_service import list_selection_tasks
from app.services.ai_selection_service import process_ai_selection_task
from app.services.ai_selection_service import run_ai_selection_task
from app.services.ai_selection_service import score_task_products
from app.services.ai_selection_service import build_recommendations
from app.services.ai_selection_service import build_selection_report
from app.services.ai_selection_service import get_task_filter_options
from app.services.ai_selection_service import list_suppliers
from app.services.market_price_service import build_market_price_analyses
from app.services.market_price_service import collect_product_market_price
from app.services.market_price_service import open_market_login_browser
from app.services.market_price_service import serialize_market_price_analysis
from app.services.market_price_task_service import build_market_worker_product_payload
from app.services.market_price_task_service import claim_next_market_login_task
from app.services.market_price_task_service import claim_next_market_price_task
from app.services.market_price_task_service import complete_market_login_task
from app.services.market_price_task_service import complete_market_price_task
from app.services.market_price_task_service import fail_market_login_task
from app.services.market_price_task_service import fail_market_price_task
from app.services.market_price_task_service import get_latest_market_price_task
from app.services.market_price_task_service import queue_market_login_task
from app.services.market_price_task_service import queue_market_price_task
from app.services.market_price_task_service import serialize_market_price_task
from app.models.product import Product
from app.services.product_service import (
    add_ai_product_to_library,
    clear_library_products,
    delete_library_product,
    delete_library_products,
    get_library_products,
    get_products_page,
)
from app.services.score_config_service import get_config_center_data
from app.services.score_config_service import get_score_rules
from app.services.score_config_service import get_score_weights
from app.services.score_config_service import update_score_rules
from app.services.score_config_service import update_score_weights
from app.services.task_service import create_crawl_task, get_crawl_task


# 统一路由入口，页面路由和采集路由都挂在这里。
router = APIRouter()

# Jinja2 模板引擎配置，模板文件统一放在 app/templates 下。
templates = Jinja2Templates(directory="app/templates")

# 模板中用于生成中文关键词分页链接。
templates.env.filters["quote_plus"] = quote_plus
templates.env.filters["loads_json"] = json.loads
templates.env.filters["money_or_dash"] = lambda value: (
    "--" if value is None else f"¥{float(value):.2f}"
)


@router.get("/", response_class=HTMLResponse)
def read_index(request: Request) -> HTMLResponse:
    """渲染首页搜索表单。"""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
def read_dashboard(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """渲染工作台页面。"""
    tasks = list_selection_tasks(db)
    latest_task = tasks[0] if tasks else None
    recommendations = get_task_recommendations(db, latest_task.id) if latest_task else []
    return templates.TemplateResponse(
        "ai_selection_home.html",
        {
            "request": request,
            "tasks": tasks,
            "latest_task": latest_task,
            "recommendations": recommendations,
            "report": get_task_report(db, latest_task.id) if latest_task else None,
            "dashboard": _build_dashboard_summary(latest_task, recommendations),
        },
    )


@router.get("/ai-selection", response_class=HTMLResponse)
def read_ai_selection_home(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """进入 AI 选品结果页，默认跳转到最近一次任务。"""
    tasks = list_selection_tasks(db)
    latest_task = tasks[0] if tasks else None

    if latest_task:
        return RedirectResponse(
            url=f"/ai-selection/tasks/{latest_task.id}",
            status_code=303,
        )

    recommendations = get_task_recommendations(db, latest_task.id) if latest_task else []
    return templates.TemplateResponse(
        "ai_selection_entry.html",
        {
            "request": request,
            "tasks": tasks,
            "latest_task": latest_task,
            "recommendations": recommendations,
            "dashboard": _build_dashboard_summary(latest_task, recommendations),
        },
    )


@router.post("/ai-selection/tasks")
async def create_ai_selection_task(
    background_tasks: BackgroundTasks,
    keyword: str = Form(...),
    pages: int = Form(10),
    min_purchase_price: float | None = Form(None),
    max_purchase_price: float | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """创建并执行 AI 选品任务。"""
    safe_min_price = min_purchase_price if min_purchase_price and min_purchase_price >= 0 else None
    safe_max_price = max_purchase_price if max_purchase_price and max_purchase_price >= 0 else None
    if (
        safe_min_price is not None
        and safe_max_price is not None
        and safe_min_price > safe_max_price
    ):
        safe_min_price, safe_max_price = safe_max_price, safe_min_price

    task = create_selection_task(
        db=db,
        keyword=keyword,
        pages=max(1, min(pages, 10)),
        top_count=20,
        min_purchase_price=safe_min_price,
        max_purchase_price=safe_max_price,
    )
    if not get_settings().remote_worker_enabled:
        background_tasks.add_task(process_ai_selection_task, task.id)
    return RedirectResponse(url=f"/ai-selection/tasks/{task.id}", status_code=303)


@router.get("/ai-selection/tasks/{task_id}", response_class=HTMLResponse)
def read_ai_selection_task(
    task_id: int,
    request: Request,
    category: str | None = Query(None),
    min_price: str | None = Query(None),
    max_price: str | None = Query(None),
    min_roi: str | None = Query(None),
    min_score: str | None = Query(None),
    province: str | None = Query(None),
    drop_shipping: str | None = Query(None),
    level: str | None = Query(None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """渲染 AI 选品任务结果页面。"""
    task = get_selection_task(db, task_id)
    filters = {
        "category": category or "全部",
        "min_price": min_price,
        "max_price": max_price,
        "min_roi": min_roi,
        "min_score": min_score,
        "province": province or "全部",
        "drop_shipping": drop_shipping or "全部",
        "level": level or "全部",
    }
    recommendations = get_task_recommendations(db, task_id, filters=filters)
    report = get_task_report(db, task_id)
    market_analyses = build_market_price_analyses(recommendations)
    return templates.TemplateResponse(
        "ai_selection_result.html",
        {
            "request": request,
            "task": task,
            "recommendations": recommendations,
            "report": report,
            "filters": filters,
            "filter_options": get_task_filter_options(db, task_id) if task else {},
            "market_analyses": market_analyses,
        },
    )


@router.get("/suppliers", response_class=HTMLResponse)
def read_suppliers(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """渲染供应商库页面。"""
    suppliers = list_suppliers(db)
    return templates.TemplateResponse(
        "suppliers.html",
        {
            "request": request,
            "suppliers": suppliers,
        },
    )


@router.get("/data-center", response_class=HTMLResponse)
def read_data_center(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """渲染数据中心页面。"""
    tasks = list_selection_tasks(db)
    latest_task = tasks[0] if tasks else None
    recommendations = get_task_recommendations(db, latest_task.id) if latest_task else []
    report = get_task_report(db, latest_task.id) if latest_task else None
    return templates.TemplateResponse(
        "data_center.html",
        {
            "request": request,
            "tasks": tasks,
            "latest_task": latest_task,
            "recommendations": recommendations,
            "report": report,
            "dashboard": _build_dashboard_summary(latest_task, recommendations),
            "report_data": _build_report_view_data(report),
        },
    )


@router.get("/ai-selection/tasks/{task_id}/report", response_class=HTMLResponse)
def read_ai_selection_report(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """渲染 AI 选品分析报告页面。"""
    task = get_selection_task(db, task_id)
    report = get_task_report(db, task_id)
    recommendations = get_task_recommendations(db, task_id)
    return templates.TemplateResponse(
        "ai_selection_report.html",
        {
            "request": request,
            "task": task,
            "report": report,
            "recommendations": recommendations,
            "report_data": _build_report_view_data(report),
        },
    )


@router.get("/ai-score-config", response_class=HTMLResponse)
def read_ai_score_config(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """渲染 AI Score 配置中心。"""
    return templates.TemplateResponse(
        "ai_score_config.html",
        {
            "request": request,
            **get_config_center_data(db),
        },
    )


@router.post("/ai-score-config/weights")
def update_ai_score_weights(
    supplier_score: float = Form(...),
    product_score: float = Form(...),
    profit_score: float = Form(...),
    price_score: float = Form(...),
    fulfillment_score: float = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """更新 AI Score 权重配置。"""
    update_score_weights(
        db,
        {
            "supplier_score": supplier_score / 100,
            "product_score": product_score / 100,
            "profit_score": profit_score / 100,
            "price_score": price_score / 100,
            "fulfillment_score": fulfillment_score / 100,
            "competition_score": 0,
            "supplier_stability_score": 0,
        },
    )
    return RedirectResponse(url="/ai-score-config", status_code=303)


@router.post("/ai-score-config/rules")
def update_ai_score_rules_form(
    rules_json: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """通过配置中心表单更新 AI Score 评分规则。"""
    rules = json.loads(rules_json)
    update_score_rules(db, rules)
    return RedirectResponse(url="/ai-score-config", status_code=303)


@router.post("/ai-selection/tasks/{task_id}/rescore")
def rescore_ai_selection_task(
    task_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """使用当前配置重新评分并刷新推荐和报告。"""
    task = get_selection_task(db, task_id)
    if task:
        score_task_products(db, task_id)
        build_recommendations(db, task_id, top_count=task.top_count)
        build_selection_report(db, task_id)
    return RedirectResponse(url=f"/ai-selection/tasks/{task_id}", status_code=303)


@router.post("/products/add-from-ai/{product_id}")
def add_product_from_ai(
    product_id: int,
    task_id: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """将 AI 选品结果商品加入商品库。"""
    add_ai_product_to_library(db, product_id)
    return RedirectResponse(url=f"/ai-selection/tasks/{task_id}", status_code=303)


@router.get("/api/selection-tasks/{task_id}")
def read_selection_task_api(
    task_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """返回 AI 选品任务状态。"""
    task = get_selection_task(db, task_id)
    if not task:
        return {"status": "missing"}

    return {
        "task_id": task.id,
        "keyword": task.keyword,
        "status": task.status,
        "total_pages": task.total_pages,
        "total_products": task.total_products,
        "deduped_products": task.deduped_products,
        "deduped_suppliers": task.deduped_suppliers,
        "top_count": task.top_count,
        "error_message": task.error_message,
    }


@router.get("/api/worker/tasks/next")
def claim_worker_task_api(
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """本地采集 Worker 领取一个待采集任务。"""
    _verify_worker_token(x_worker_token)
    task = claim_next_worker_task(db)
    if not task:
        return {"status": "empty"}

    return {
        "status": "ok",
        "task": {
            "id": task.id,
            "keyword": task.keyword,
            "total_pages": task.total_pages,
            "top_count": task.top_count,
            "min_purchase_price": task.min_purchase_price,
            "max_purchase_price": task.max_purchase_price,
        },
    }


@router.post("/api/worker/tasks/{task_id}/complete")
def complete_worker_task_api(
    task_id: int,
    payload: dict[str, Any] = Body(...),
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """接收本地采集 Worker 回传的商品数据，并完成评分推荐。"""
    _verify_worker_token(x_worker_token)
    products_payload = payload.get("products", [])
    if not isinstance(products_payload, list):
        raise HTTPException(status_code=400, detail="products 必须是列表")

    crawled_products = [_build_crawled_product(item) for item in products_payload]
    task = complete_ai_selection_task_from_worker(db, task_id, crawled_products)
    return {
        "status": task.status,
        "task_id": task.id,
        "total_products": task.total_products,
        "deduped_products": task.deduped_products,
        "error_message": task.error_message,
    }


@router.post("/api/worker/tasks/{task_id}/fail")
def fail_worker_task_api(
    task_id: int,
    payload: dict[str, Any] = Body(...),
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """接收本地采集 Worker 的失败状态。"""
    _verify_worker_token(x_worker_token)
    error_message = str(payload.get("error_message") or "本地采集 Worker 执行失败")
    task = fail_ai_selection_task_from_worker(db, task_id, error_message)
    return {
        "status": task.status,
        "task_id": task.id,
        "error_message": task.error_message,
    }


@router.get("/api/worker/market-price-tasks/next")
def claim_market_price_worker_task_api(
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """本地 Worker 领取一个市场价格采集任务。"""
    _verify_worker_token(x_worker_token)
    claimed = claim_next_market_price_task(db)
    if not claimed:
        return {"status": "empty"}

    task, product = claimed
    return {
        "status": "ok",
        "task": {
            "id": task.id,
            "product": build_market_worker_product_payload(product),
        },
    }


@router.post("/api/worker/market-price-tasks/{task_id}/complete")
def complete_market_price_worker_task_api(
    task_id: int,
    payload: dict[str, Any] = Body(...),
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """接收本地 Worker 回传的淘宝市场价格采集结果。"""
    _verify_worker_token(x_worker_token)
    analysis = payload.get("analysis")
    if not isinstance(analysis, dict):
        raise HTTPException(status_code=400, detail="analysis 必须是对象")

    task = complete_market_price_task(db, task_id, analysis)
    return {
        "status": task.status,
        "task_id": task.id,
        "product_id": task.product_id,
    }


@router.post("/api/worker/market-price-tasks/{task_id}/fail")
def fail_market_price_worker_task_api(
    task_id: int,
    payload: dict[str, Any] = Body(...),
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """接收本地 Worker 回传的淘宝市场价格采集失败状态。"""
    _verify_worker_token(x_worker_token)
    error_message = str(payload.get("error_message") or "本地 Worker 采集市场价失败")
    task = fail_market_price_task(db, task_id, error_message)
    return {
        "status": task.status,
        "task_id": task.id,
        "product_id": task.product_id,
        "error_message": task.error_message,
    }


@router.get("/api/worker/market-login-tasks/next")
def claim_market_login_worker_task_api(
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """本地 Worker 领取一个打开淘宝登录浏览器的请求。"""
    _verify_worker_token(x_worker_token)
    task = claim_next_market_login_task(db)
    if not task:
        return {"status": "empty"}

    return {
        "status": "ok",
        "task": {
            "id": task.id,
            "platform": task.platform,
        },
    }


@router.post("/api/worker/market-login-tasks/{task_id}/complete")
def complete_market_login_worker_task_api(
    task_id: int,
    payload: dict[str, Any] = Body(...),
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """接收本地 Worker 打开淘宝登录浏览器的结果。"""
    _verify_worker_token(x_worker_token)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=400, detail="result 必须是对象")

    task = complete_market_login_task(db, task_id, result)
    return {
        "status": task.status,
        "task_id": task.id,
        "platform": task.platform,
        "error_message": task.error_message,
    }


@router.post("/api/worker/market-login-tasks/{task_id}/fail")
def fail_market_login_worker_task_api(
    task_id: int,
    payload: dict[str, Any] = Body(...),
    x_worker_token: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """接收本地 Worker 打开淘宝登录浏览器失败状态。"""
    _verify_worker_token(x_worker_token)
    error_message = str(payload.get("error_message") or "本地 Worker 打开登录浏览器失败")
    task = fail_market_login_task(db, task_id, error_message)
    return {
        "status": task.status,
        "task_id": task.id,
        "platform": task.platform,
        "error_message": task.error_message,
    }


@router.get("/api/selection-tasks/{task_id}/recommendations")
def read_recommendations_api(
    task_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """返回 AI 选品 Top 推荐结果。"""
    rows = get_task_recommendations(db, task_id)
    return {
        "task_id": task_id,
        "items": [
            {
                "rank": row["recommendation"].rank,
                "title": row["product"].title,
                "ai_score": row["score_record"].ai_score,
                "recommendation_level": row["score_record"].recommendation_level,
                "supplier_score": row["score_record"].supplier_score,
                "product_score": row["score_record"].product_score,
                "profit_score": row["score_record"].profit_score,
                "price_score": row["score_record"].price_score,
                "fulfillment_score": row["score_record"].fulfillment_score,
                "roi": row["score_record"].roi,
                "estimated_profit": row["score_record"].estimated_profit,
                "product_url": row["product"].product_url,
            }
            for row in rows
        ],
    }


@router.get("/api/products/{product_id}/market-price")
async def read_product_market_price_api(
    product_id: int,
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """实时采集并返回单个商品的市场价格分析。"""
    product = db.get(Product, product_id)
    if not product:
        return {
            "status": "missing",
            "product_id": product_id,
            "message": "商品不存在",
        }

    if get_settings().remote_worker_enabled:
        latest_task = get_latest_market_price_task(db, product_id)
        if latest_task and latest_task.status == "done" and latest_task.result_json and not refresh:
            return serialize_market_price_task(latest_task)

        task = queue_market_price_task(db, product, force_refresh=refresh)
        return {
            "status": "queued",
            "product_id": product_id,
            "task_id": task.id,
            "message": "已提交给本地 Worker，正在用本机淘宝登录态采集前三条价格",
        }

    analysis = await collect_product_market_price(product)
    return {
        "status": "ok",
        "product_id": product_id,
        "analysis": serialize_market_price_analysis(analysis),
    }


@router.get("/api/products/{product_id}/market-price/status")
def read_product_market_price_status_api(
    product_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """查询单个商品市场价格采集任务状态。"""
    task = get_latest_market_price_task(db, product_id)
    if not task:
        return {
            "status": "idle",
            "product_id": product_id,
            "message": "尚未提交市场价采集任务",
        }
    return serialize_market_price_task(task)


@router.post("/api/market-price/login-browser")
async def open_market_price_login_browser_api(
    platform: str = Query("taobao"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """打开市场价格采集专用的平台登录浏览器。"""
    if get_settings().remote_worker_enabled:
        task = queue_market_login_task(db, platform)
        return {
            "status": "queued",
            "task_id": task.id,
            "platform": platform,
            "message": "已通知本地 Worker 打开淘宝登录浏览器，请在运行 Worker 的电脑上完成登录",
        }

    result = await open_market_login_browser(platform)
    return {
        "status": "ok" if result["ready"] else "failed",
        **result,
    }


@router.get("/api/score-config/weights")
def read_score_weights_api(db: Session = Depends(get_db)) -> dict[str, object]:
    """返回当前 AI Score 权重配置。"""
    return {"weights": get_score_weights(db)}


@router.put("/api/score-config/weights")
def update_score_weights_api(
    weights: dict[str, float] = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """通过 API 更新 AI Score 权重配置。"""
    return {"weights": update_score_weights(db, weights)}


@router.get("/api/score-config/rules")
def read_score_rules_api(db: Session = Depends(get_db)) -> dict[str, object]:
    """返回当前 AI Score 评分规则。"""
    return {"rules": get_score_rules(db)}


@router.put("/api/score-config/rules")
def update_score_rules_api(
    rules: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """通过 API 更新 AI Score 评分规则。"""
    return {"rules": update_score_rules(db, rules)}


@router.get("/preview", response_class=HTMLResponse)
def read_preview(request: Request) -> HTMLResponse:
    """渲染网页首页 UI 预览。"""
    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
        },
    )


@router.post("/crawl")
async def crawl_products(
    keyword: str = Form(...),
) -> RedirectResponse:
    """接收关键词，创建采集任务并跳转到采集中页面。"""
    clean_keyword = keyword.strip()
    redirect_url = "/products"
    if clean_keyword:
        task = create_crawl_task(clean_keyword)
        redirect_url = f"/collecting/{task.task_id}"

    # 表单提交完成后使用 303，避免浏览器刷新时重复提交。
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/collecting/{task_id}", response_class=HTMLResponse)
def read_collecting(task_id: str, request: Request) -> HTMLResponse:
    """渲染采集中页面。"""
    task = get_crawl_task(task_id)
    return templates.TemplateResponse(
        "collecting.html",
        {
            "request": request,
            "task": task,
            "task_id": task_id,
        },
    )


@router.get("/api/crawl-tasks/{task_id}")
def read_crawl_task(task_id: str) -> dict[str, object]:
    """返回采集任务状态。"""
    task = get_crawl_task(task_id)
    if not task:
        return {
            "status": "missing",
        }

    return {
        "task_id": task.task_id,
        "keyword": task.keyword,
        "status": task.status,
        "saved_count": task.saved_count,
        "error": task.error,
        "redirect_url": (
            f"/products?keyword={quote_plus(task.keyword)}"
            f"&saved_count={task.saved_count}"
            if task.status in {"done", "failed"}
            else None
        ),
    }


@router.get("/products", response_class=HTMLResponse)
def read_products(
    request: Request,
    page: int = Query(1, ge=1),
    keyword: str | None = Query(None),
    saved_count: int | None = Query(None, ge=0),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """渲染商品列表页面。"""
    page_data = get_products_page(db=db, page=page, page_size=10, keyword=keyword)
    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "saved_count": saved_count,
            **page_data,
        },
    )


@router.get("/products/export")
def export_products(db: Session = Depends(get_db)) -> Response:
    """导出商品库商品为 CSV 文件。"""
    products = get_library_products(db)
    rows = [
        "标题,价格,销量,店铺,地区,商品链接",
        *[
            ",".join(
                [
                    _csv_cell(product.title),
                    _csv_cell(product.price),
                    _csv_cell(product.sales),
                    _csv_cell(product.shop_name),
                    _csv_cell(product.province),
                    _csv_cell(product.product_url),
                ]
            )
            for product in products
        ],
    ]
    content = "\ufeff" + "\n".join(rows)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=products.csv",
        },
    )


@router.post("/products/clear")
def clear_products(db: Session = Depends(get_db)) -> RedirectResponse:
    """清空旧商品库记录。"""
    clear_library_products(db)
    return RedirectResponse(url="/products", status_code=303)


@router.post("/products/batch-delete")
def batch_delete_products(
    product_ids: list[int] = Form(default=[]),
    page: int = Form(1),
    keyword: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """批量删除商品库中的商品。"""
    delete_library_products(db, product_ids)
    redirect_url = f"/products?page={page}"
    if keyword:
        redirect_url += f"&keyword={quote_plus(keyword)}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/products/{product_id}/delete")
def delete_product(
    product_id: int,
    page: int = Form(1),
    keyword: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """删除商品库中的单个商品。"""
    delete_library_product(db, product_id)
    redirect_url = f"/products?page={page}"
    if keyword:
        redirect_url += f"&keyword={quote_plus(keyword)}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/image-proxy")
def image_proxy(url: str = Query(...)) -> Response:
    """代理展示 1688 商品图片，避免浏览器热链限制。"""
    image_url = unquote(url)
    request = UrlRequest(
        image_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://s.1688.com/",
        },
    )

    with urlopen(request, timeout=15) as image_response:
        content = image_response.read()
        content_type = image_response.headers.get("Content-Type", "image/jpeg")

    return Response(content=content, media_type=content_type)


@router.get("/health")
def health_check() -> dict[str, str]:
    """返回服务健康检查结果。"""
    return {
        "status": "ok",
    }


def _build_dashboard_summary(
    latest_task: SelectionTask | None,
    recommendations: list[dict[str, Any]],
) -> dict[str, object]:
    """构建 AI 工作台首页汇总数据。"""
    score_values = [row["score_record"].ai_score for row in recommendations]
    profit_values = [
        row["score_record"].estimated_profit or 0 for row in recommendations
    ]
    roi_values = [row["score_record"].roi or 0 for row in recommendations]

    return {
        "ai_score": round(sum(score_values) / len(score_values), 2)
        if score_values
        else 0,
        "avg_profit": round(sum(profit_values) / len(profit_values), 2)
        if profit_values
        else 0,
        "avg_roi": round(sum(roi_values) / len(roi_values), 2)
        if roi_values
        else 0,
        "total_products": latest_task.deduped_products if latest_task else 0,
        "total_suppliers": latest_task.deduped_suppliers if latest_task else 0,
        "top_count": len(recommendations),
    }


def _build_report_view_data(report: Any | None) -> dict[str, Any]:
    """构建报告页面图表所需的数据。"""
    if not report:
        return {
            "distribution": {},
            "top_products": [],
            "supplier_analysis": {},
            "price_analysis": {},
            "risk_analysis": {},
        }

    return {
        "distribution": json.loads(report.score_distribution_json),
        "top_products": json.loads(report.top_products_json),
        "supplier_analysis": json.loads(report.supplier_analysis_json),
        "price_analysis": json.loads(report.price_analysis_json),
        "risk_analysis": json.loads(report.risk_analysis_json),
    }


def _csv_cell(value: Any | None) -> str:
    """转义 CSV 单元格内容。"""
    text = "" if value is None else str(value)
    escaped = text.replace('"', '""')
    return f'"{escaped}"'


def _verify_worker_token(token: str | None) -> None:
    """校验本地采集 Worker 的访问令牌。"""
    settings = get_settings()
    if not settings.remote_worker_enabled:
        raise HTTPException(status_code=403, detail="远程 Worker 模式未启用")
    if not settings.worker_token:
        raise HTTPException(status_code=503, detail="服务器未配置 WORKER_TOKEN")
    if token != settings.worker_token:
        raise HTTPException(status_code=401, detail="Worker Token 无效")


def _build_crawled_product(item: Any) -> CrawledProduct:
    """把 Worker 回传的字典转换为采集商品结构。"""
    if not isinstance(item, dict):
        raise HTTPException(status_code=400, detail="商品数据格式错误")

    return CrawledProduct(
        keyword=str(item.get("keyword") or ""),
        title=item.get("title"),
        price=item.get("price"),
        sales=item.get("sales"),
        shop_name=item.get("shop_name"),
        shop_level=item.get("shop_level"),
        province=item.get("province"),
        support_drop_shipping=bool(item.get("support_drop_shipping", False)),
        image_url=item.get("image_url"),
        product_url=item.get("product_url"),
    )
