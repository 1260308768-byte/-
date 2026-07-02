"""项目配置读取模块。"""

from dataclasses import dataclass
from pathlib import Path
import os
import sys

from dotenv import load_dotenv


# 项目根目录；打包成 EXE 后使用 EXE 所在目录保存配置、日志和浏览器登录态。
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)

# 优先读取项目根目录下的 .env 文件，方便本地和 Docker 环境统一配置。
load_dotenv(BASE_DIR / ".env")


def normalize_database_url(database_url: str) -> str:
    """规范化数据库地址，确保 SQLite 相对路径基于项目根目录。"""
    sqlite_prefix = "sqlite:///"

    if not database_url.startswith(sqlite_prefix):
        return database_url

    database_path = database_url.removeprefix(sqlite_prefix)
    path = Path(database_path)

    # Windows 绝对路径和 Linux 绝对路径都保持原样。
    if path.is_absolute() or database_path.startswith("/"):
        return database_url

    return f"{sqlite_prefix}{(BASE_DIR / path).as_posix()}"


@dataclass(frozen=True)
class Settings:
    """应用配置对象。"""

    # 应用名称，用于 FastAPI 文档标题和后续页面展示。
    app_name: str = os.getenv("APP_NAME", "1688选品助手")

    # SQLite 默认数据库文件，后续可以通过 .env 中的 DATABASE_URL 覆盖。
    database_url: str = normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "sqlite:///data/products.db",
        )
    )

    # 日志文件路径，相对于项目根目录。
    log_file: str = os.getenv("LOG_FILE", "logs/app.log")

    # 1688 搜索页基础地址。
    crawler_search_url: str = os.getenv(
        "CRAWLER_SEARCH_URL",
        "https://s.1688.com/selloffer/offer_search.htm",
    )

    # 单次采集的最大商品数量。
    crawler_max_products: int = int(os.getenv("CRAWLER_MAX_PRODUCTS", "30"))

    # Playwright 操作超时时间，单位毫秒。
    crawler_timeout_ms: int = int(os.getenv("CRAWLER_TIMEOUT_MS", "30000"))

    # 是否使用无头浏览器，默认适合服务端运行。
    crawler_headless: bool = os.getenv("CRAWLER_HEADLESS", "true").lower() == "true"

    # 浏览器通道，设置为 chrome 时优先使用本机 Chrome，失败后自动回退 Playwright Chromium。
    crawler_browser_channel: str | None = os.getenv("CRAWLER_BROWSER_CHANNEL") or None

    # 是否启用 Playwright 手动接管模式，用于本地处理 1688 验证页。
    crawler_manual_mode: bool = (
        os.getenv("CRAWLER_MANUAL_MODE", "false").lower() == "true"
    )

    # 手动接管模式下等待用户处理验证的时间，单位毫秒。
    crawler_manual_wait_ms: int = int(os.getenv("CRAWLER_MANUAL_WAIT_MS", "60000"))

    # Playwright 持久化用户目录，用于保存 1688 登录态。
    crawler_user_data_dir: str = os.getenv(
        "CRAWLER_USER_DATA_DIR",
        "data/playwright_profile",
    )

    # 已登录浏览器的 Chrome DevTools Protocol 地址，设置后优先复用该浏览器。
    crawler_cdp_url: str | None = os.getenv("CRAWLER_CDP_URL") or None

    # CDP 调试浏览器关闭后是否自动重新拉起。
    crawler_auto_start_cdp: bool = (
        os.getenv("CRAWLER_AUTO_START_CDP", "true").lower() == "true"
    )

    # 自动拉起 CDP 浏览器时使用的调试端口。
    crawler_cdp_port: int = int(os.getenv("CRAWLER_CDP_PORT", "9223"))

    # 自动拉起 CDP 浏览器时保存登录态的目录。
    crawler_cdp_user_data_dir: str = os.getenv(
        "CRAWLER_CDP_USER_DATA_DIR",
        "data/chrome_debug_profile",
    )

    # 自动拉起 CDP 浏览器时是否隐藏窗口，真实采集默认在后台执行。
    crawler_cdp_background: bool = (
        os.getenv("CRAWLER_CDP_BACKGROUND", "true").lower() == "true"
    )

    # AI 选品真实试用时关闭演示样本补齐，避免把本地模拟数据误当真实采集结果。
    ai_selection_demo_fallback: bool = (
        os.getenv("AI_SELECTION_DEMO_FALLBACK", "false").lower() == "true"
    )

    # 远程 Worker 模式：服务器只创建任务，本地采集 Worker 轮询并回传结果。
    remote_worker_enabled: bool = (
        os.getenv("REMOTE_WORKER_ENABLED", "false").lower() == "true"
    )

    # 本地采集 Worker 调用服务器接口时使用的简单令牌。
    worker_token: str | None = os.getenv("WORKER_TOKEN") or None


def get_settings() -> Settings:
    """获取应用配置。"""
    return Settings()
