"""市场价格分析服务。"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict, dataclass
import json
import mimetypes
import os
from pathlib import Path
import re
from statistics import mean
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from app.config.settings import BASE_DIR, get_settings
from app.models.product import Product
from app.utils.logger import get_logger


logger = get_logger()


@dataclass(slots=True)
class MarketPlatformConfig:
    """市场平台配置，后续新增平台时优先扩展配置和适配器。"""

    code: str
    display_name: str
    search_url_template: str
    alternate_search_url_templates: tuple[str, ...] = ()
    image_search_url: str | None = None
    file_input_selector: str | None = None
    login_url: str | None = None
    supports_image_search: bool = False
    enabled: bool = True


@dataclass(slots=True)
class MarketPlatformPrice:
    """单个平台的同款价格分析结果。"""

    code: str
    display_name: str
    search_url: str
    matched: bool
    price_samples: list[float] | None = None
    min_price: float | None = None
    max_price: float | None = None
    average_price: float | None = None
    confidence: float = 0.0
    message: str = "未匹配到可信同款"


@dataclass(slots=True)
class MarketPriceAnalysis:
    """单个商品的市场价格分析结果。"""

    product_id: int
    platforms: list[MarketPlatformPrice]
    market_average_price: float | None
    competitiveness_label: str
    competitiveness_class: str
    competitiveness_percent: float | None
    has_trusted_match: bool


MARKET_PLATFORM_CONFIGS: tuple[MarketPlatformConfig, ...] = (
    MarketPlatformConfig(
        code="taobao",
        display_name="淘宝",
        search_url_template="https://s.taobao.com/search?q={keyword}",
        image_search_url="https://s.taobao.com/search",
        file_input_selector="#image-search-custom-file-input",
        login_url="https://s.taobao.com/search?q=%E6%94%B6%E7%BA%B3%E7%9B%92",
        supports_image_search=True,
    ),
    MarketPlatformConfig(
        code="douyin",
        display_name="抖音商城",
        search_url_template="https://www.douyin.com/search/{keyword}?type=goods",
        alternate_search_url_templates=(
            "https://www.douyin.com/search/{keyword}?type=general",
            "https://www.douyin.com/root/search/{keyword}",
        ),
        image_search_url=None,
        file_input_selector=None,
        login_url="https://www.douyin.com/search/%E6%94%B6%E7%BA%B3%E7%9B%92?type=goods",
        supports_image_search=False,
        enabled=False,
    ),
)

MARKET_PRICE_CACHE: dict[int, tuple[float, MarketPriceAnalysis]] = {}
MARKET_PRICE_CACHE_TTL_SECONDS = 60 * 30
MARKET_PRICE_TOP_MATCH_LIMIT = 3
MARKET_IMAGE_DIR = BASE_DIR / "tmp" / "market_images"
TAOBAO_IMAGE_SEARCH_LOCK = asyncio.Lock()
LAST_TAOBAO_IMAGE_SEARCH_AT = 0.0
TAOBAO_IMAGE_SEARCH_INTERVAL_SECONDS = 2.5
MARKET_LOGIN_PLAYWRIGHT: Any | None = None
MARKET_LOGIN_CONTEXT: Any | None = None
MARKET_PRICE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def build_market_price_analyses(
    recommendation_rows: list[dict[str, object]],
) -> dict[int, MarketPriceAnalysis]:
    """为推荐商品批量构建市场价格分析占位结果。"""
    analyses: dict[int, MarketPriceAnalysis] = {}
    for row in recommendation_rows:
        product = row.get("product")
        if isinstance(product, Product):
            analyses[product.id] = analyze_product_market_price(product)
    return analyses


def analyze_product_market_price(product: Product) -> MarketPriceAnalysis:
    """生成单个商品的市场价格分析占位，不伪造任何市场价格。"""
    platform_prices = [
        _build_empty_platform_price(product, config, "等待图片搜同款采集")
        for config in MARKET_PLATFORM_CONFIGS
        if config.enabled
    ]
    return _build_market_analysis(product, platform_prices)


async def collect_product_market_price(product: Product) -> MarketPriceAnalysis:
    """实时用商品主图采集各市场平台的同款价格。"""
    cached = MARKET_PRICE_CACHE.get(product.id)
    now = time.time()
    if cached and now - cached[0] <= MARKET_PRICE_CACHE_TTL_SECONDS:
        return cached[1]

    image_path = await _download_product_image(product)
    if not image_path:
        platform_prices = [
            _build_empty_platform_price(product, config, "商品缺少主图，无法图片搜同款")
            for config in MARKET_PLATFORM_CONFIGS
            if config.enabled
        ]
        analysis = _build_market_analysis(product, platform_prices)
        MARKET_PRICE_CACHE[product.id] = (now, analysis)
        return analysis

    platform_prices: list[MarketPlatformPrice] = []
    settings = get_settings()

    try:
        async with async_playwright() as playwright:
            browser = None
            context = None
            context_is_persistent = False
            should_close_browser = True
            try:
                (
                    browser,
                    context,
                    context_is_persistent,
                    should_close_browser,
                ) = await _open_market_browser_context(
                    playwright,
                    settings,
                )
                page, created_page = await _get_or_create_market_page(
                    context,
                    preferred_hosts=("taobao.com",),
                )
                known_pages = set(context.pages)
                try:
                    for config in MARKET_PLATFORM_CONFIGS:
                        if not config.enabled:
                            continue
                        platform_prices.append(
                            await _collect_platform_price_by_image(
                                page=page,
                                product=product,
                                config=config,
                                image_path=image_path,
                            )
                        )
                finally:
                    await _close_extra_market_pages(context, known_pages, keep_page=page)
                    if created_page and not page.is_closed():
                        await page.close()
            finally:
                if context and context_is_persistent:
                    await context.close()
                if browser and should_close_browser:
                    await browser.close()
    except Exception as exc:
        logger.exception("市场价格图片搜同款异常，商品ID：%s", product.id)
        error_text = str(exc)
        message = (
            "请保持淘宝/抖音登录浏览器窗口打开，再点击采集市场价"
            if "user data directory" in error_text.lower()
            or "process singleton" in error_text.lower()
            or "profile" in error_text.lower()
            else "图片搜同款采集异常"
        )
        platform_prices = [
            _build_empty_platform_price(product, config, message)
            for config in MARKET_PLATFORM_CONFIGS
            if config.enabled
        ]

    analysis = _build_market_analysis(product, platform_prices)
    if analysis.has_trusted_match:
        MARKET_PRICE_CACHE[product.id] = (now, analysis)
    return analysis


async def open_market_login_browser(platform_code: str = "taobao") -> dict[str, Any]:
    """打开市场价格采集专用登录浏览器，并保持登录态目录。"""
    settings = get_settings()
    platform = _get_market_platform_config(platform_code) or MARKET_PLATFORM_CONFIGS[0]
    login_url = platform.login_url or platform.search_url_template.format(keyword="")
    try:
        if settings.crawler_cdp_url and await _is_cdp_ready(settings.crawler_cdp_url):
            opened = await _open_cdp_tab(settings.crawler_cdp_url, login_url)
            if not opened:
                await _ensure_market_cdp_browser_started(settings, login_url)
        else:
            await _ensure_market_cdp_browser_started(settings, login_url)
    except Exception:
        logger.exception("市场价平台登录浏览器打开失败")
        return {
            "ready": False,
            "platform": platform.code,
            "cdp_url": settings.crawler_cdp_url,
            "profile_dir": str(BASE_DIR / settings.crawler_cdp_user_data_dir),
            "headless": False,
            "message": f"{platform.display_name}登录浏览器启动失败，请关闭已有采集Chrome后重试",
        }

    return {
        "ready": True,
        "platform": platform.code,
        "cdp_url": settings.crawler_cdp_url,
        "profile_dir": str(BASE_DIR / settings.crawler_cdp_user_data_dir),
        "headless": False,
        "message": f"已打开{platform.display_name}登录窗口；登录完成后不要关闭该窗口，直接回系统采集市场价",
    }

def serialize_market_price_analysis(analysis: MarketPriceAnalysis) -> dict[str, Any]:
    """把市场价格分析结果转换为 API 可返回的字典。"""
    return asdict(analysis)


def _get_market_platform_config(platform_code: str) -> MarketPlatformConfig | None:
    """根据平台编码读取市场平台配置。"""
    normalized_code = (platform_code or "").strip().lower()
    for config in MARKET_PLATFORM_CONFIGS:
        if config.code == normalized_code:
            return config
    return None


async def _open_market_browser_context(
    playwright: Any,
    settings: Any,
) -> tuple[Any | None, Any, bool, bool]:
    """打开用于市场价格采集的浏览器上下文，优先复用登录用 CDP Chrome。"""
    if MARKET_LOGIN_CONTEXT:
        return None, MARKET_LOGIN_CONTEXT, False, False

    if settings.crawler_cdp_url:
        try:
            if (
                not await _is_cdp_ready(settings.crawler_cdp_url)
                and settings.crawler_auto_start_cdp
            ):
                await _ensure_market_cdp_browser_started(settings)

            if await _is_cdp_ready(settings.crawler_cdp_url):
                cdp_info = await _get_cdp_version_info(settings.crawler_cdp_url)
                if not _is_headless_cdp(cdp_info):
                    browser = await playwright.chromium.connect_over_cdp(
                        settings.crawler_cdp_url
                    )
                    context = (
                        browser.contexts[0]
                        if browser.contexts
                        else await browser.new_context(locale="zh-CN")
                    )
                    return browser, context, False, False
        except Exception:
            logger.exception("CDP登录浏览器不可用，无法采集市场价")

    raise RuntimeError("请先点击登录淘宝，使用固定登录浏览器后再采集市场价")


async def _get_or_create_market_page(
    context: Any,
    preferred_hosts: tuple[str, ...] = (),
) -> tuple[Any, bool]:
    """复用匹配平台域名的采集页面，避免一次采集打开多个无关标签页。"""
    for page in reversed(context.pages):
        if not page.is_closed():
            page_url = (page.url or "").lower()
            if preferred_hosts and not any(host in page_url for host in preferred_hosts):
                continue
            page.set_default_timeout(22000)
            return page, False

    page = await context.new_page()
    page.set_default_timeout(22000)
    return page, True


async def _close_extra_market_pages(context: Any, known_pages: set[Any], keep_page: Any) -> None:
    """关闭本次市场价采集过程中平台额外弹出的页面，保留用户原有登录页。"""
    for page in list(context.pages):
        if page == keep_page or page.is_closed():
            continue
        page_url = (page.url or "").strip().lower()
        if page in known_pages and page_url not in {"", "about:blank"}:
            continue
        try:
            await page.close()
        except Exception:
            logger.exception("关闭市场价采集新增页面失败：%s", getattr(page, "url", ""))


async def _collect_platform_price_by_image(
    page: Any,
    product: Product,
    config: MarketPlatformConfig,
    image_path: Path,
) -> MarketPlatformPrice:
    """通过商品主图采集单个平台的同款价格区间。"""
    if not config.supports_image_search:
        return await _collect_platform_price_by_keyword(
            page=page,
            product=product,
            config=config,
            reason="平台暂未开放稳定图搜入口，使用搜索结果前三价",
        )

    if not config.image_search_url or not config.file_input_selector:
        return _build_empty_platform_price(product, config, "平台图片搜索配置不完整")

    if config.code == "taobao":
        return await _collect_taobao_price_by_image(
            page=page,
            product=product,
            config=config,
            image_path=image_path,
        )

    return _build_empty_platform_price(product, config, "平台图片搜索适配器未启用")


async def _collect_taobao_price_by_image(
    page: Any,
    product: Product,
    config: MarketPlatformConfig,
    image_path: Path,
) -> MarketPlatformPrice:
    """使用淘宝图片搜索入口上传商品主图并提取同款价格。"""
    page.set_default_timeout(22000)
    search_url = _build_platform_search_url(product, config)

    try:
        async with TAOBAO_IMAGE_SEARCH_LOCK:
            await _wait_taobao_rate_limit()
            await page.goto(
                config.image_search_url or search_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await _dispatch_taobao_image_search(page, image_path)
            await _wait_for_image_search_result(page)
            await _light_scroll(page)

        candidates = await _extract_market_candidates(page)
        price_values = _match_image_search_candidate_prices(product, candidates)
        if not price_values:
            return _build_empty_platform_price(
                product,
                config,
                "当前淘宝图搜页未提取到前三个价格，请确认页面已显示商品价格后重试",
            )

        return _build_platform_price_from_samples(
            product=product,
            config=config,
            search_url=page.url or search_url,
            price_values=price_values,
            message=f"图片搜同款参考前 {len(price_values)} 条结果",
        )
    except PlaywrightTimeoutError as exc:
        logger.exception("淘宝图片搜同款超时或受限，商品ID：%s", product.id)
        message = str(exc)
        if "访问" in message or "验证" in message or "受限" in message:
            return _build_empty_platform_price(
                product,
                config,
                "淘宝触发访问限制，请在调试Chrome中确认淘宝可正常访问后重试",
            )
        return _build_empty_platform_price(product, config, "淘宝当前图搜页等待超时，未继续搜索其它页面")
    except PlaywrightError:
        logger.exception("淘宝图片搜同款失败，商品ID：%s", product.id)
        return _build_empty_platform_price(product, config, "淘宝图片搜索入口不可用")


async def _wait_taobao_rate_limit() -> None:
    """限制淘宝图搜调用频率，降低连续请求触发风控的概率。"""
    global LAST_TAOBAO_IMAGE_SEARCH_AT

    now = time.time()
    elapsed = now - LAST_TAOBAO_IMAGE_SEARCH_AT
    if elapsed < TAOBAO_IMAGE_SEARCH_INTERVAL_SECONDS:
        await asyncio.sleep(TAOBAO_IMAGE_SEARCH_INTERVAL_SECONDS - elapsed)
    LAST_TAOBAO_IMAGE_SEARCH_AT = time.time()


async def _dispatch_taobao_image_search(page: Any, image_path: Path) -> None:
    """调用淘宝页面内置图片搜索事件，避免文件选择弹层卡住。"""
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    image_base64 = await asyncio.to_thread(
        lambda: base64.b64encode(image_path.read_bytes()).decode("ascii")
    )
    data_url = f"data:{mime_type};base64,{image_base64}"

    await page.locator(".search-suggest-image-search-out-icon").first.wait_for(
        state="attached",
        timeout=30000,
    )
    await page.wait_for_timeout(800)
    await page.evaluate(
        """
        (imgUrl) => {
            window.dispatchEvent(new CustomEvent("START_IMG_SEARCH_OUTSIDE", {
                detail: {
                    imgUrl,
                    freshFilter: true,
                    imgFrom: "codex_product_image"
                }
            }));
        }
        """,
        data_url,
    )


async def _wait_for_image_search_result(page: Any) -> None:
    """等待图片搜索结果页出现价格或平台验证状态。"""
    deadline = time.time() + 24
    while time.time() < deadline:
        text = await page.locator("body").inner_text(timeout=6000)
        if _has_market_price_text(text):
            return
        if _has_platform_block_text(text):
            raise PlaywrightTimeoutError("淘宝图片搜索触发验证或访问受限")
        await page.wait_for_timeout(1800)

    raise PlaywrightTimeoutError("淘宝图片搜索结果等待超时")


async def _collect_platform_price_by_keyword(
    page: Any,
    product: Product,
    config: MarketPlatformConfig,
    reason: str,
) -> MarketPlatformPrice:
    """在图片搜索不可用时，使用平台搜索结果页提取前三个真实价格。"""
    search_urls = _build_platform_search_urls(product, config)
    try:
        for index, search_url in enumerate(search_urls):
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
            if config.code in {"taobao", "douyin"}:
                await _light_scroll(page)

            candidates = await _extract_market_candidates(page)
            if config.code == "douyin":
                candidates.extend(await _extract_douyin_market_candidates(page))

            price_values = _match_image_search_candidate_prices(
                product,
                candidates,
                strict_title=False,
            )
            if price_values:
                return _build_platform_price_from_samples(
                    product=product,
                    config=config,
                    search_url=page.url or search_url,
                    price_values=price_values,
                    message=reason,
                )

            if config.code != "douyin" or index >= len(search_urls) - 1:
                break

        if config.code == "douyin":
            await _save_market_debug_page(page, product, config)
        return _build_empty_platform_price(
            product,
            config,
            "未提取到平台前三个商品价格，请确认抖音搜索结果页已显示商城商品价",
        )
    except Exception:
        logger.exception("市场价格搜索页兜底失败，平台：%s，商品ID：%s", config.code, product.id)
        return _build_empty_platform_price(product, config, "搜索结果页采集失败")


async def _download_product_image(product: Product) -> Path | None:
    """下载商品主图到本地临时目录，供平台图片搜索上传。"""
    image_url = (product.image_url or "").strip()
    if not image_url:
        return None

    MARKET_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    download_urls = _build_image_download_urls(image_url)
    suffix = _guess_image_suffix(download_urls[0])
    image_path = MARKET_IMAGE_DIR / f"product_{product.id}{suffix}"

    if image_path.exists() and image_path.stat().st_size > 0:
        return image_path

    def download() -> Path | None:
        for current_url in download_urls:
            request = UrlRequest(
                current_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": "https://s.1688.com/",
                },
            )
            try:
                with urlopen(request, timeout=20) as response:
                    content = response.read(8_000_000)
                if len(content) < 1024:
                    continue
                image_path.write_bytes(content)
                return image_path
            except Exception:
                logger.exception(
                    "商品主图下载失败，商品ID：%s，图片：%s",
                    product.id,
                    current_url,
                )
        return None

    return await asyncio.to_thread(download)


async def _save_market_debug_page(
    page: Any,
    product: Product,
    config: MarketPlatformConfig,
) -> None:
    """保存平台市场价采集失败时的页面文本和截图。"""
    debug_dir = BASE_DIR / "logs"
    debug_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"market_{config.code}_{product.id}"
    try:
        text = await page.locator("body").inner_text(timeout=5000)
        (debug_dir / f"{prefix}.txt").write_text(text[:8000], encoding="utf-8")
        await page.screenshot(path=str(debug_dir / f"{prefix}.png"), full_page=True)
        logger.info("已保存市场价采集诊断页面：%s", prefix)
    except Exception:
        logger.exception("保存市场价采集诊断页面失败：%s", prefix)


def _build_image_download_urls(image_url: str) -> list[str]:
    """构建图片下载候选地址，优先使用 1688 原始 JPG 图。"""
    urls: list[str] = []
    normalized = image_url.strip()
    match = re.match(r"^(https?://.+?\.(?:jpg|jpeg|png))(?:_.+)?$", normalized, re.I)
    if match:
        urls.append(match.group(1))
    urls.append(normalized)
    return list(dict.fromkeys(urls))


def _guess_image_suffix(image_url: str) -> str:
    """根据图片地址推断本地临时文件后缀。"""
    path = urlparse(image_url).path.lower()
    positions = [
        (path.rfind(suffix), suffix)
        for suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif")
        if path.rfind(suffix) >= 0
    ]
    if positions:
        return max(positions)[1]
    return ".jpg"


async def _light_scroll(page: Any) -> None:
    """轻量滚动市场搜索页，触发商品卡片懒加载。"""
    for _ in range(3):
        await page.mouse.wheel(0, 1000)
        await page.wait_for_timeout(900)


async def _extract_market_candidates(page: Any) -> list[dict[str, Any]]:
    """从图片搜索结果页提取包含价格的候选商品卡片。"""
    return await page.evaluate(
        """
        () => {
            const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
            const normalizeUrl = (value) => {
                if (!value) {
                    return "";
                }
                try {
                    const url = new URL(value, location.href);
                    url.hash = "";
                    return url.href.replace(/([?&])spm=[^&]+/g, "$1").replace(/[?&]$/, "");
                } catch {
                    return String(value).trim();
                }
            };
            const extractPrices = (text) => {
                const prices = [];
                const normalized = normalize(text).replace(/,/g, "");
                const patterns = [
                    /[¥￥]\\s*([0-9]{1,5})(?:\\s*\\.\\s*([0-9]{1,2}))?/g,
                    /(?:价格|到手价|券后|促销价|售价)\\s*[:：]?\\s*([0-9]{1,5})(?:\\s*\\.\\s*([0-9]{1,2}))?/g,
                ];

                for (const pattern of patterns) {
                    for (const match of normalized.matchAll(pattern)) {
                        const price = Number(match[2] ? `${match[1]}.${match[2]}` : match[1]);
                        if (price > 0 && price < 100000) {
                            prices.push(price);
                        }
                    }
                }

                return prices;
            };
            const pickTitle = (node, text) => {
                const titleNode = node.querySelector("[title], h3, h4, [class*='title'], [class*='Title']");
                const title = titleNode
                    ? normalize(titleNode.getAttribute("title") || titleNode.innerText)
                    : "";
                if (title && !/[¥￥]/.test(title)) {
                    return title;
                }
                return normalize(text.replace(/[¥￥]\\s*[0-9]{1,5}(?:\\s*\\.\\s*[0-9]{1,2})?/g, " ")).slice(0, 120);
            };
            const buildCandidate = (node) => {
                const text = normalize(node.innerText);
                if (!text || text.length < 3 || text.length > 900) {
                    return null;
                }
                const prices = extractPrices(text);
                if (!prices.length) {
                    return null;
                }

                const link = node.matches("a[href]")
                    ? node
                    : node.querySelector("a[href*='item'], a[href*='detail'], a[href*='auction'], a[href]");
                const image = node.querySelector("img");
                const href = link ? normalizeUrl(link.href || link.getAttribute("href")) : "";
                const imageUrl = image
                    ? normalizeUrl(image.currentSrc || image.src || image.getAttribute("data-src") || image.getAttribute("src"))
                    : "";
                const title = pickTitle(node, text);

                if (!href && !imageUrl && title.length < 8) {
                    return null;
                }

                return {
                    text,
                    title,
                    prices,
                    href: href || null,
                    image_url: imageUrl || null,
                };
            };
            const pushCandidate = (candidate, seen) => {
                if (!candidate) {
                    return false;
                }
                const key = candidate.href
                    || candidate.image_url
                    || candidate.title.slice(0, 80);
                if (!key || seen.has(key)) {
                    return false;
                }
                seen.add(key);
                candidates.push(candidate);
                return true;
            };

            const candidates = [];
            const seen = new Set();
            const primaryNodes = Array.from(document.querySelectorAll([
                "a[href*='item']",
                "a[href*='detail']",
                "a[href*='auction']",
                "[class*='item']:has(img)",
                "[class*='Item']:has(img)",
                "[class*='card']:has(img)",
                "[class*='Card']:has(img)",
                "[class*='product']:has(img)",
                "[class*='Product']:has(img)"
            ].join(",")));

            for (const node of primaryNodes) {
                pushCandidate(buildCandidate(node), seen);
                if (candidates.length >= 80) {
                    return candidates;
                }
            }

            const fallbackNodes = Array.from(document.querySelectorAll([
                "[class*='item']",
                "[class*='Item']",
                "[class*='card']",
                "[class*='Card']",
                "[class*='product']",
                "[class*='Product']",
                "a[href*='item']",
                "a[href*='detail']",
                "li",
                "section"
            ].join(",")));

            for (const node of fallbackNodes) {
                pushCandidate(buildCandidate(node), seen);
                if (candidates.length >= 80) {
                    break;
                }
            }

            return candidates;
        }
        """
    )


async def _extract_douyin_market_candidates(page: Any) -> list[dict[str, Any]]:
    """从抖音搜索页的可见文本和脚本数据中提取前三个价格候选。"""
    return await page.evaluate(
        """
        () => {
            const candidates = [];
            const seen = new Set();
            const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
            const normalizePrice = (value) => {
                if (value === null || value === undefined) {
                    return null;
                }
                const raw = Number(String(value).replace(/[^0-9.]/g, ""));
                if (!Number.isFinite(raw) || raw <= 0) {
                    return null;
                }
                if (raw >= 1000 && Number.isInteger(raw)) {
                    return raw / 100;
                }
                return raw;
            };
            const pushPrice = (price, title = "", href = location.href) => {
                const normalized = normalizePrice(price);
                if (!normalized || normalized <= 0 || normalized >= 100000) {
                    return;
                }
                const key = `${title.slice(0, 80)}-${normalized}`;
                if (seen.has(key)) {
                    return;
                }
                seen.add(key);
                candidates.push({
                    text: title || String(normalized),
                    title: title || "抖音商城商品",
                    prices: [normalized],
                    href,
                    image_url: null,
                });
            };
            const extractPrices = (text) => {
                const prices = [];
                const normalized = normalize(text).replace(/,/g, "");
                const patterns = [
                    /[¥￥]\\s*([0-9]{1,5})(?:\\s*\\.\\s*([0-9]{1,2}))?/g,
                    /(?:到手价|券后|售价|价格)\\s*[:：]?\\s*([0-9]{1,5})(?:\\s*\\.\\s*([0-9]{1,2}))?/g,
                ];
                for (const pattern of patterns) {
                    for (const match of normalized.matchAll(pattern)) {
                        prices.push(match[2] ? `${match[1]}.${match[2]}` : match[1]);
                    }
                }
                return prices;
            };

            const nodes = Array.from(document.querySelectorAll([
                "[class*='goods']",
                "[class*='Goods']",
                "[class*='product']",
                "[class*='Product']",
                "[class*='commodity']",
                "[class*='Commodity']",
                "[class*='card']",
                "[class*='Card']",
                "a[href*='haohuo']",
                "a[href*='ecom']",
                "a[href*='item']"
            ].join(",")));
            for (const node of nodes) {
                const blockText = normalize(node.innerText);
                if (!blockText || blockText.length > 900 || !/[¥￥]|到手价|券后|售价|价格/.test(blockText)) {
                    continue;
                }
                const link = node.closest("a[href]") || node.querySelector("a[href]");
                const titleNode = node.querySelector("[title], h3, h4, span, div");
                const title = titleNode
                    ? normalize(titleNode.getAttribute("title") || titleNode.innerText)
                    : blockText;
                for (const price of extractPrices(blockText)) {
                    pushPrice(price, title, link ? link.href : location.href);
                    if (candidates.length >= 20) {
                        return candidates;
                    }
                }
            }

            const text = document.body ? document.body.innerText : "";
            for (const match of text.matchAll(/(?:¥|￥|到手价|券后|售价|价格)\\s*([0-9]{1,5})(?:\\.([0-9]{1,2}))?/g)) {
                pushPrice(match[2] ? `${match[1]}.${match[2]}` : match[1], text.slice(Math.max(match.index - 80, 0), match.index + 80));
            }

            const scripts = Array.from(document.scripts)
                .map((script) => script.textContent || "")
                .filter((content) => /price|sellPrice|minPrice|promotionPrice|amount|商品|product|goods/i.test(content));
            const priceRegex = /"(?:price|sellPrice|minPrice|maxPrice|promotionPrice|originPrice|discountPrice|amount|payAmount)"\\s*:\\s*"?([0-9]{2,8}(?:\\.[0-9]{1,2})?)"?/gi;
            const titleRegex = /"(?:title|name|productName|goodsName|shopName)"\\s*:\\s*"([^"]{2,120})"/i;
            for (const content of scripts) {
                const titleMatch = content.match(titleRegex);
                const title = titleMatch ? titleMatch[1].replace(/\\\\u([0-9a-fA-F]{4})/g, (_, code) => String.fromCharCode(parseInt(code, 16))) : "抖音商城商品";
                for (const match of content.matchAll(priceRegex)) {
                    pushPrice(match[1], title);
                    if (candidates.length >= 20) {
                        return candidates;
                    }
                }
            }

            return candidates;
        }
        """
    )


def _match_image_search_candidate_prices(
    product: Product,
    candidates: list[dict[str, Any]],
    strict_title: bool = True,
) -> list[float]:
    """按图片搜索结果顺序提取前三个不重复的可信商品价格。"""
    query = _build_market_search_keyword(product)
    matched_prices: list[float] = []
    seen_candidate_keys: set[str] = set()
    seen_price_values: set[int] = set()

    for candidate in candidates:
        if len(matched_prices) >= MARKET_PRICE_TOP_MATCH_LIMIT:
            break

        text = str(candidate.get("title") or candidate.get("text") or "")
        if _looks_like_platform_noise(text):
            continue
        candidate_key = (
            str(candidate.get("href") or "")
            or str(candidate.get("image_url") or "")
            or text[:80]
        )
        if candidate_key and candidate_key in seen_candidate_keys:
            continue
        if candidate_key:
            seen_candidate_keys.add(candidate_key)

        similarity = _title_similarity(query, text)
        # 图片搜索已经承担主匹配，标题只做二次排除，因此阈值不能过高。
        if strict_title and similarity < 0.035:
            continue

        price_value = None
        for price in candidate.get("prices") or []:
            try:
                price_value = float(price)
            except (TypeError, ValueError):
                continue

            if _is_reasonable_market_price(product, price_value):
                break
            price_value = None

        if price_value is not None:
            rounded_price = round(price_value, 2)
            price_key = int(round(rounded_price * 100))
            if price_key in seen_price_values:
                continue
            seen_price_values.add(price_key)
            matched_prices.append(rounded_price)

    return matched_prices


def _build_platform_price_from_samples(
    product: Product,
    config: MarketPlatformConfig,
    search_url: str,
    price_values: list[float],
    message: str,
) -> MarketPlatformPrice:
    """把平台前三个价格样本整理成统一返回结构。"""
    samples = [round(float(value), 2) for value in price_values[:MARKET_PRICE_TOP_MATCH_LIMIT]]
    if not samples:
        return _build_empty_platform_price(product, config, message)

    min_price = round(min(samples), 2)
    max_price = round(max(samples), 2)
    average_price = round(mean(samples), 2)
    confidence = min(0.9, 0.58 + len(samples) * 0.08)
    return MarketPlatformPrice(
        code=config.code,
        display_name=config.display_name,
        search_url=search_url,
        matched=True,
        price_samples=samples,
        min_price=min_price,
        max_price=max_price,
        average_price=average_price,
        confidence=round(confidence, 2),
        message=message,
    )


def _looks_like_platform_noise(text: str) -> bool:
    """判断候选文本是否更像平台导航、验证或广告噪声。"""
    normalized = re.sub(r"\s+", "", text)
    if not normalized:
        return True
    noise_words = ("登录", "验证码", "滑块", "安全验证", "购物车", "我的淘宝", "客服", "反馈")
    return any(word in normalized for word in noise_words)


def _has_market_price_text(text: str) -> bool:
    """判断页面文本中是否已经出现市场价格。"""
    return bool(re.search(r"[¥￥]\s*[0-9]+", text or ""))


def _has_platform_block_text(text: str) -> bool:
    """判断页面是否出现平台验证、访问受限或空结果拦截。"""
    normalized = re.sub(r"\s+", "", text or "")
    block_words = (
        "访问被拒绝",
        "验证码",
        "安全验证",
        "滑块",
        "访问受限",
        "亲，访问被拒绝",
    )
    return any(word in normalized for word in block_words)


def _title_similarity(query: str, text: str) -> float:
    """计算标题与候选文本的轻量语义相似度。"""
    query_tokens = _text_features(query)
    text_tokens = _text_features(text)
    if not query_tokens or not text_tokens:
        return 0.0

    overlap = query_tokens & text_tokens
    return len(overlap) / max(len(query_tokens), 1)


def _text_features(value: str) -> set[str]:
    """提取中文标题匹配特征。"""
    normalized = re.sub(r"\s+", "", value.lower())
    normalized = re.sub(r"[^\u4e00-\u9fa5a-z0-9]", "", normalized)
    if not normalized:
        return set()

    features = {
        normalized[index : index + 2]
        for index in range(max(len(normalized) - 1, 0))
    }
    features.update(
        token
        for token in re.split(r"[^a-z0-9\u4e00-\u9fa5]+", value.lower())
        if len(token) >= 2
    )
    return features


def _is_reasonable_market_price(product: Product, price: float) -> bool:
    """过滤明显异常的市场价格。"""
    purchase_price = product.purchase_price or _parse_float(product.price) or 0
    if price <= 0 or price > 100000:
        return False
    if purchase_price <= 0:
        return True

    return 1 <= price <= max(purchase_price * 50, 100000)


def _build_market_analysis(
    product: Product,
    platform_prices: list[MarketPlatformPrice],
) -> MarketPriceAnalysis:
    """根据平台价格构建综合市场分析。"""
    trusted_prices = [
        price.average_price
        for price in platform_prices
        if price.matched and price.average_price is not None
    ]
    market_average = round(mean(trusted_prices), 2) if trusted_prices else None
    competitiveness_label, competitiveness_class, competitiveness_percent = (
        _build_competitiveness(product.suggested_price, market_average)
    )

    return MarketPriceAnalysis(
        product_id=product.id,
        platforms=platform_prices,
        market_average_price=market_average,
        competitiveness_label=competitiveness_label,
        competitiveness_class=competitiveness_class,
        competitiveness_percent=competitiveness_percent,
        has_trusted_match=bool(trusted_prices),
    )


def _build_empty_platform_price(
    product: Product,
    config: MarketPlatformConfig,
    message: str,
) -> MarketPlatformPrice:
    """构建未匹配平台价格结果。"""
    return MarketPlatformPrice(
        code=config.code,
        display_name=config.display_name,
        search_url=_build_platform_search_url(product, config),
        matched=False,
        price_samples=[],
        message=message,
    )


def _build_platform_search_url(product: Product, config: MarketPlatformConfig) -> str:
    """构建用于人工复核的平台搜索入口链接。"""
    return _build_platform_search_urls(product, config)[0]


def _build_platform_search_urls(product: Product, config: MarketPlatformConfig) -> list[str]:
    """构建平台搜索入口候选列表，采集时始终复用同一个页面依次访问。"""
    keyword = quote_plus(_build_market_search_keyword(product))
    templates = (config.search_url_template, *config.alternate_search_url_templates)
    urls = [template.format(keyword=keyword) for template in templates if template]
    return list(dict.fromkeys(urls))


async def _is_cdp_ready(cdp_url: str) -> bool:
    """检测 CDP 调试端口是否可用于市场采集。"""
    version_url = cdp_url.rstrip("/") + "/json/version"

    def check() -> bool:
        try:
            with urlopen(version_url, timeout=2) as response:
                return response.status == 200
        except (OSError, URLError):
            return False

    return await asyncio.to_thread(check)


async def _get_cdp_version_info(cdp_url: str) -> dict[str, Any]:
    """读取 Chrome DevTools 调试端口的浏览器版本信息。"""
    version_url = cdp_url.rstrip("/") + "/json/version"

    def read_version() -> dict[str, Any]:
        try:
            with urlopen(version_url, timeout=2) as response:
                payload = response.read(20_000).decode("utf-8", errors="ignore")
            data = json.loads(payload)
            return data if isinstance(data, dict) else {}
        except (OSError, URLError, json.JSONDecodeError):
            return {}

    return await asyncio.to_thread(read_version)


async def _open_cdp_tab(cdp_url: str, target_url: str) -> bool:
    """在已启动的 Chrome 调试浏览器中打开新的平台登录页。"""
    new_tab_url = cdp_url.rstrip("/") + "/json/new?" + quote_plus(target_url, safe=":/?=&%")

    def open_tab() -> bool:
        try:
            request = UrlRequest(new_tab_url, method="PUT")
            with urlopen(request, timeout=3) as response:
                return response.status in {200, 201}
        except (OSError, URLError):
            return False

    return await asyncio.to_thread(open_tab)


def _is_headless_cdp(cdp_info: dict[str, Any]) -> bool:
    """判断当前 CDP 浏览器是否为无头模式。"""
    browser = str(cdp_info.get("Browser") or "")
    user_agent = str(cdp_info.get("User-Agent") or "")
    return "HeadlessChrome" in browser or "HeadlessChrome" in user_agent


async def _open_market_profile_browser(settings: Any, start_url: str) -> None:
    """使用市场价专用用户目录打开普通 Chrome 登录窗口。"""
    chrome_path = _find_chrome_path()
    profile_dir = BASE_DIR / settings.crawler_cdp_user_data_dir
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(chrome_path),
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "--window-size=1440,1000",
        start_url,
    ]

    def start_browser() -> None:
        logger.info("打开市场价平台登录浏览器：%s", " ".join(command))
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0,
        )

    await asyncio.to_thread(start_browser)


async def _ensure_market_cdp_browser_started(
    settings: Any,
    start_url: str = "https://s.taobao.com/",
) -> None:
    """为市场价采集启动可复用登录态的 Chrome 调试浏览器。"""
    chrome_path = _find_chrome_path()
    profile_dir = BASE_DIR / settings.crawler_cdp_user_data_dir
    profile_dir.mkdir(parents=True, exist_ok=True)

    command = [
        str(chrome_path),
        f"--remote-debugging-port={settings.crawler_cdp_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "--window-size=1440,1000",
        start_url,
    ]

    def start_browser() -> None:
        logger.info("启动市场价采集Chrome调试浏览器：%s", " ".join(command))
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0,
        )

    await asyncio.to_thread(start_browser)
    for _ in range(20):
        await asyncio.sleep(1)
        if settings.crawler_cdp_url and await _is_cdp_ready(settings.crawler_cdp_url):
            logger.info("市场价采集Chrome调试浏览器已启动，端口：%s", settings.crawler_cdp_port)
            return

    logger.warning("市场价采集Chrome调试浏览器启动后端口仍不可用")


def _find_chrome_path() -> Path:
    """查找本机 Chrome 可执行文件。"""
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError("未找到 Chrome，请先安装 Google Chrome。")


def _build_market_search_keyword(product: Product) -> str:
    """构建市场平台人工复核搜索关键词。"""
    title = (product.title or product.keyword or "").strip()
    if not title:
        return "同款商品"

    return title[:80]


def _parse_float(value: str | None) -> float | None:
    """从字符串中提取浮点数。"""
    if not value:
        return None

    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def _build_competitiveness(
    suggested_price: float | None,
    market_average_price: float | None,
) -> tuple[str, str, float | None]:
    """根据建议售价与市场均价判断价格竞争力。"""
    if not suggested_price or not market_average_price:
        return "未匹配到可信同款", "unknown", None

    diff_rate = (market_average_price - suggested_price) / market_average_price
    diff_percent = round(abs(diff_rate) * 100, 1)

    if diff_rate >= 0.08:
        return f"低于市场均价{diff_percent}%", "good", diff_percent
    if diff_rate <= -0.08:
        return f"高于市场均价{diff_percent}%", "bad", diff_percent
    return "接近市场均价", "neutral", diff_percent
