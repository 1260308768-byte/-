"""FastAPI 应用入口。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config.settings import get_settings
from app.database.init_db import init_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """管理 FastAPI 应用启动和关闭生命周期。"""
    # 启动时自动初始化数据库表，保证首次运行时不需要手动建表。
    init_database()
    yield


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings = get_settings()

    # 创建 FastAPI 应用，标题会显示在自动生成的接口文档中。
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # 挂载静态文件目录，后续 Bootstrap 自定义样式会放在 app/static 下。
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    # 注册项目主路由。
    app.include_router(router)

    return app


# ASGI 服务器会加载这个 app 对象，例如：uvicorn app.main:app。
app = create_app()
