"""1688 商品采集模块。"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import urlopen

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.config.settings import get_settings
from app.config.settings import BASE_DIR
from app.utils.browser_path import find_chromium_browser_path
from app.utils.logger import get_logger


logger = get_logger()


@dataclass(slots=True)
class CrawledProduct:
    """采集到的商品数据结构。"""

    keyword: str
    title: str | None
    price: str | None
    sales: str | None
    shop_name: str | None
    shop_level: str | None
    province: str | None
    support_drop_shipping: bool
    image_url: str | None
    product_url: str | None


class ProductCrawler:
    """1688 商品采集器。"""

    def __init__(self, max_products: int | None = None) -> None:
        """初始化采集器配置。"""
        self.settings = get_settings()
        self.max_products = max_products or self.settings.crawler_max_products

    async def crawl(self, keyword: str) -> list[CrawledProduct]:
        """根据关键词采集 1688 商品列表。"""
        normalized_keyword = keyword.strip()
        if not normalized_keyword:
            logger.warning("采集关键词为空，已跳过")
            return []

        logger.info("开始采集 1688 商品，关键词：%s", normalized_keyword)

        try:
            products = await self._crawl_with_browser(normalized_keyword)
        except PlaywrightTimeoutError:
            logger.exception("采集超时，关键词：%s", normalized_keyword)
            return []
        except Exception:
            logger.exception("采集异常，关键词：%s", normalized_keyword)
            return []

        logger.info(
            "结束采集 1688 商品，关键词：%s，采集数量：%s",
            normalized_keyword,
            len(products),
        )
        return products

    async def _crawl_with_browser(self, keyword: str) -> list[CrawledProduct]:
        """启动浏览器并执行真实页面采集。"""
        search_url = self._build_search_url(keyword)

        async with async_playwright() as playwright:
            if self.settings.crawler_cdp_url:
                return await self._crawl_with_cdp_or_autostart(
                    playwright,
                    keyword,
                    search_url,
                )

            user_data_dir = BASE_DIR / self.settings.crawler_user_data_dir
            user_data_dir.mkdir(parents=True, exist_ok=True)

            context = await self._launch_persistent_context(playwright, user_data_dir)
            try:
                page = await context.new_page()
                page.set_default_timeout(self.settings.crawler_timeout_ms)

                await page.goto(search_url, wait_until="domcontentloaded")
                if await self._is_blocked_page(page):
                    if self.settings.crawler_manual_mode:
                        await self._wait_for_manual_verification(page)
                        if await self._is_blocked_page(page):
                            await self._save_blocked_page_debug(page)
                            logger.warning("手动处理后仍处于风控页面，关键词：%s", keyword)
                            return []
                    else:
                        await self._save_blocked_page_debug(page)
                        logger.warning("1688 返回风控或反馈页面，关键词：%s", keyword)
                        return []

                await self._wait_for_products(page)
                await self._load_more_products(page)

                raw_products = await self._extract_products(page)
                return self._normalize_products(keyword, raw_products)
            finally:
                # 关闭上下文会保留持久化用户目录中的 Cookie 和本地状态。
                await context.close()

    async def _launch_persistent_context(self, playwright: Any, user_data_dir: Any) -> Any:
        """启动持久化浏览器上下文，优先复用本机 Chrome 登录态目录。"""
        launch_options = {
            "user_data_dir": str(user_data_dir),
            "headless": self.settings.crawler_headless
            and not self.settings.crawler_manual_mode,
            "viewport": {"width": 1440, "height": 1000},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "locale": "zh-CN",
            "timeout": self.settings.crawler_timeout_ms,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--start-maximized",
            ],
        }

        browser_path = find_chromium_browser_path(
            preferred_path=self.settings.crawler_browser_executable_path,
            use_default_browser=self.settings.crawler_use_default_browser,
        )
        if browser_path:
            try:
                logger.info("使用本机浏览器启动采集：%s", browser_path)
                return await playwright.chromium.launch_persistent_context(
                    executable_path=str(browser_path),
                    **launch_options,
                )
            except PlaywrightError:
                logger.exception("本机浏览器启动失败，继续尝试浏览器通道")

        if self.settings.crawler_browser_channel:
            try:
                logger.info("使用浏览器通道启动采集：%s", self.settings.crawler_browser_channel)
                return await playwright.chromium.launch_persistent_context(
                    channel=self.settings.crawler_browser_channel,
                    **launch_options,
                )
            except PlaywrightError:
                logger.exception("本机 Chrome 启动失败，回退 Playwright Chromium")

        return await playwright.chromium.launch_persistent_context(**launch_options)

    async def _crawl_with_cdp_or_autostart(
        self,
        playwright: Any,
        keyword: str,
        search_url: str,
    ) -> list[CrawledProduct]:
        """优先连接 CDP 浏览器，关闭后自动重新启动再采集。"""
        try:
            return await self._crawl_with_cdp_browser(playwright, keyword, search_url)
        except PlaywrightError:
            if not self.settings.crawler_auto_start_cdp:
                raise

            logger.warning("CDP 浏览器未连接，正在自动启动 Chrome 调试浏览器")
            await self._ensure_cdp_browser_started()
            return await self._crawl_with_cdp_browser(playwright, keyword, search_url)

    async def _ensure_cdp_browser_started(self) -> None:
        """确保可复用登录态的 Chrome 调试浏览器处于运行状态。"""
        if await self._is_cdp_endpoint_ready():
            return

        chrome_path = self._find_chrome_path()
        profile_dir = BASE_DIR / self.settings.crawler_cdp_user_data_dir
        profile_dir.mkdir(parents=True, exist_ok=True)

        command = [
            str(chrome_path),
            f"--remote-debugging-port={self.settings.crawler_cdp_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1440,1000",
        ]

        if self.settings.crawler_cdp_background:
            command.extend(
                [
                    "--headless=new",
                    "--disable-gpu",
                ]
            )

        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=self._chrome_creation_flags(),
        )

        for _ in range(30):
            await asyncio.sleep(1)
            if await self._is_cdp_endpoint_ready():
                logger.info("Chrome 调试浏览器已启动，端口：%s", self.settings.crawler_cdp_port)
                return

        raise RuntimeError("Chrome 调试浏览器启动超时，请手动打开 1688 登录窗口")

    async def _is_cdp_endpoint_ready(self) -> bool:
        """检测 CDP 调试端口是否可用。"""
        if not self.settings.crawler_cdp_url:
            return False

        version_url = self.settings.crawler_cdp_url.rstrip("/") + "/json/version"

        def check() -> bool:
            try:
                with urlopen(version_url, timeout=2) as response:
                    return response.status == 200
            except (OSError, URLError):
                return False

        return await asyncio.to_thread(check)

    @staticmethod
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

    def _chrome_creation_flags(self) -> int:
        """生成 Chrome 后台启动参数，避免采集窗口显示到前端。"""
        if os.name != "nt" or not self.settings.crawler_cdp_background:
            return 0

        return subprocess.CREATE_NO_WINDOW

    async def _crawl_with_cdp_browser(
        self,
        playwright: Any,
        keyword: str,
        search_url: str,
    ) -> list[CrawledProduct]:
        """连接用户已登录的远程调试浏览器并执行采集。"""
        browser = await playwright.chromium.connect_over_cdp(
            self.settings.crawler_cdp_url
        )
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = self._find_existing_search_page(context.pages, search_url)
        created_page = page is None

        if page is None:
            page = await context.new_page()

        page.set_default_timeout(self.settings.crawler_timeout_ms)

        try:
            logger.info("通过 CDP 复用用户浏览器登录态访问：%s", search_url)
            await page.goto(search_url, wait_until="domcontentloaded")

            if await self._is_blocked_page(page):
                if self.settings.crawler_manual_mode and not self.settings.crawler_cdp_background:
                    await self._wait_for_manual_verification(page)
                    if await self._is_blocked_page(page):
                        await self._save_blocked_page_debug(page)
                        logger.warning("CDP 浏览器手动处理后仍返回风控页面，关键词：%s", keyword)
                        return []
                else:
                    await self._save_blocked_page_debug(page)
                    logger.warning("CDP 浏览器仍返回风控页面，关键词：%s", keyword)
                    return []

            await self._wait_for_products(page)
            await self._load_more_products(page)
            raw_products = await self._extract_products(page)
            return self._normalize_products(keyword, raw_products)
        finally:
            # CDP 模式连接的是用户浏览器，只关闭本次新建的采集页面。
            if created_page:
                await page.close()

    @staticmethod
    def _find_existing_search_page(pages: list[Any], search_url: str) -> Any | None:
        """查找浏览器中已经打开的 1688 搜索结果页。"""
        for page in pages:
            if page.is_closed():
                continue

            if "s.1688.com/selloffer/offer_search.htm" not in page.url:
                continue

            if "keywords=" in page.url:
                return page

        return None

    def _build_search_url(self, keyword: str) -> str:
        """构建 1688 搜索结果页地址。"""
        # 1688 老搜索页按 GBK 解码关键词，使用 UTF-8 会导致搜索框中文乱码。
        encoded_keyword = quote_plus(keyword, encoding="gbk", errors="ignore")
        search_url = f"{self.settings.crawler_search_url}?keywords={encoded_keyword}"
        logger.info("1688 搜索地址：%s", search_url)
        return search_url

    async def _wait_for_products(self, page: Any) -> None:
        """等待商品列表加载完成。"""
        # 1688 页面由前端渲染，先等待主体完成，再等待商品链接或商品卡片出现。
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(3000)

        # 不等待普通 offer 链接，避免顶部菜单、收藏、采购链接误判为商品。
        logger.info("页面加载完成，当前标题：%s，URL：%s", await page.title(), page.url)

    async def _load_more_products(self, page: Any) -> None:
        """滚动页面以触发 1688 商品懒加载。"""
        previous_count = 0
        stable_rounds = 0

        for _ in range(12):
            current_count = await page.evaluate(
                """() => document.querySelectorAll(".search-offer-item, .i18n-card-wrap, .i18n-card-wrap-p4p, .zr-render-container").length"""
            )

            if current_count >= self.max_products:
                break

            if current_count == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0

            if stable_rounds >= 3:
                break

            previous_count = current_count
            await page.mouse.wheel(0, 1400)
            await page.wait_for_timeout(1200)

        final_count = await page.evaluate(
            """() => document.querySelectorAll(".search-offer-item, .i18n-card-wrap, .i18n-card-wrap-p4p, .zr-render-container").length"""
        )
        logger.info("滚动加载后商品卡片数量：%s", final_count)

    async def _is_blocked_page(self, page: Any) -> bool:
        """判断当前页面是否为 1688 风控、验证码或反馈页。"""
        current_url = page.url.lower()
        page_text = await page.locator("body").inner_text(timeout=5000)
        blocked_keywords = (
            "点我反馈",
            "验证码",
            "安全验证",
            "访问受限",
            "ncinit",
            "x5sec",
        )

        if "____tmd____" in current_url or "x5secdata" in current_url:
            return True

        return any(keyword in page_text for keyword in blocked_keywords)

    async def _save_blocked_page_debug(self, page: Any) -> None:
        """保存风控页面诊断信息，方便本地排查。"""
        debug_dir = BASE_DIR / "logs"
        debug_dir.mkdir(parents=True, exist_ok=True)

        html_path = debug_dir / "blocked_page.html"
        screenshot_path = debug_dir / "blocked_page.png"

        try:
            html_path.write_text(await page.content(), encoding="utf-8")
            await page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(
                "已保存风控页面诊断文件：%s，%s",
                html_path,
                screenshot_path,
            )
        except Exception:
            logger.exception("保存风控页面诊断文件失败")

    async def _wait_for_manual_verification(self, page: Any) -> None:
        """手动模式下等待用户处理 1688 验证页面。"""
        logger.warning("检测到 1688 风控页面，请在浏览器中完成验证")
        logger.warning("手动模式等待 %s 毫秒后继续采集", self.settings.crawler_manual_wait_ms)
        deadline = self.settings.crawler_manual_wait_ms
        elapsed = 0

        while elapsed < deadline:
            await page.wait_for_timeout(3000)
            elapsed += 3000
            if not await self._is_blocked_page(page):
                logger.info("手动验证已完成，继续采集")
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(1500)
                return

        logger.warning("手动验证等待超时，将尝试继续采集")

    async def _extract_products(self, page: Any) -> list[dict[str, Any]]:
        """从页面 DOM 中提取原始商品数据。"""
        max_products = self.max_products

        # 使用浏览器端 JS 遍历 DOM，比固定单一选择器更能适应 1688 页面小幅改版。
        return await page.evaluate(
            """
            (maxProducts) => {
                const normalizeText = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const extractOfferId = (value) => {
                    if (!value) {
                        return null;
                    }

                    let decoded = String(value);
                    try {
                        decoded = decodeURIComponent(decoded);
                    } catch (error) {
                        decoded = String(value);
                    }
                    const offerIdsMatch = decoded.match(/[?&]offerIds?=([0-9]{8,})/);
                    if (offerIdsMatch) {
                        return offerIdsMatch[1];
                    }

                    const detailMatch = decoded.match(/detail\\.1688\\.com\\/offer\\/([0-9]{8,})\\.html/);
                    if (detailMatch) {
                        return detailMatch[1];
                    }

                    return null;
                };
                const isProductUrl = (href) => {
                    if (!href) {
                        return false;
                    }

                    const lowered = href.toLowerCase();
                    const blocked = lowered.includes("feedback")
                        || lowered.includes("____tmd____")
                        || lowered.includes("x5secdata")
                        || lowered.includes("offer_search")
                        || lowered.includes("favorite_offer")
                        || lowered.includes("purchase.1688.com")
                        || lowered.includes("work.1688.com");

                    return !blocked && /detail\\.1688\\.com\\/offer\\/\\d+\\.html/.test(lowered);
                };
                const products = [];
                const seen = new Set();

                const cards = Array.from(document.querySelectorAll(".search-offer-item, .i18n-card-wrap, .i18n-card-wrap-p4p, .zr-render-container"));
                for (const card of cards) {
                    if (products.length >= maxProducts) {
                        break;
                    }

                    const text = normalizeText(card.innerText);
                    const hrefs = Array.from(card.querySelectorAll("a[href]")).map((anchor) => anchor.href);
                    const offerId = hrefs.map(extractOfferId).find(Boolean) || extractOfferId(card.outerHTML);
                    if (!offerId) {
                        continue;
                    }

                    const url = `https://detail.1688.com/offer/${offerId}.html`;
                    if (seen.has(url)) {
                        continue;
                    }

                    const image = card.querySelector("img");
                    const imageUrl = image ? (image.currentSrc || image.src || image.getAttribute("data-src")) : null;
                    const titleNode = card.querySelector(".title-text, .offer-title-row, [class*='title']");
                    const title = normalizeText(titleNode ? titleNode.innerText : text.split(" ¥ ")[0]);
                    const priceMatch = text.match(/(?:¥|￥)\\s*([0-9]+(?:\\s*\\.\\s*[0-9]+)?)/);
                    const salesMatch = text.match(/(?:已售|月销|全网)\\s*([0-9.]+\\s*[万千]?\\+?\\s*件?)/);
                    const provinceMatch = text.match(/(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门)/);
                    const shopNode = card.querySelector(".offer-shop-row, .zr-company-info, [class*='company'], [class*='shop']");
                    const shopText = normalizeText(shopNode ? shopNode.innerText : "");
                    const shopMatch = shopText.match(/([^\\s｜|]+(?:公司|工厂|商行|店|厂|贸易|百货|用品)[^\\s｜|]*)/);
                    const shopLevelMatch = text.match(/(源头工厂|超级工厂|实力商家|诚信通|金牌卖家|\\d+\\s*年)/);
                    const dropShipping = /(一件代发|支持一件代发|支持代发|先采后付)/.test(text)
                        && !/(不支持一件代发|不支持代发)/.test(text);

                    products.push({
                        title,
                        price: priceMatch ? priceMatch[1].replace(/\\s+/g, "") : null,
                        sales: salesMatch ? salesMatch[1].replace(/\\s+/g, "") : null,
                        shop_name: shopMatch ? shopMatch[1] : null,
                        shop_level: shopLevelMatch ? shopLevelMatch[1].replace(/\\s+/g, "") : null,
                        province: provinceMatch ? provinceMatch[1] : null,
                        support_drop_shipping: dropShipping,
                        image_url: imageUrl,
                        product_url: url,
                        raw_text: text,
                    });
                    seen.add(url);
                }

                const anchors = Array.from(document.querySelectorAll("a[href]"))
                    .filter((anchor) => isProductUrl(anchor.href));

                for (const anchor of anchors) {
                    if (products.length >= maxProducts) {
                        break;
                    }

                    const url = anchor.href;
                    if (seen.has(url)) {
                        continue;
                    }

                    const card = anchor.closest("div[class*='offer'], div[class*='item'], div[class*='card'], li")
                        || anchor.parentElement;
                    const scope = card || anchor;
                    const text = normalizeText(scope.innerText);
                    const anchorText = normalizeText(anchor.innerText || anchor.title);

                    const image = scope.querySelector("img");
                    const imageUrl = image ? (image.currentSrc || image.src || image.getAttribute("data-src")) : null;

                    const priceMatch = text.match(/(?:¥|￥)\\s*([0-9]+(?:\\.[0-9]+)?(?:\\s*-\\s*[0-9]+(?:\\.[0-9]+)?)?)/);
                    const salesMatch = text.match(/(?:成交|已售|销量|付款|售出)\\s*[:：]?\\s*([0-9.]+\\s*[万千]?\\+?\\s*件?)/);
                    const provinceMatch = text.match(/(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门)/);
                    const shopLevelMatch = text.match(/(源头工厂|超级工厂|实力商家|诚信通|金牌卖家|\\d+\\s*年)/);
                    const dropShipping = /(一件代发|支持一件代发|支持代发|先采后付)/.test(text)
                        && !/(不支持一件代发|不支持代发)/.test(text);

                    const lines = text.split(" ").filter(Boolean);
                    const title = anchorText || lines.find((line) => line.length >= 6) || null;
                    const shopLink = Array.from(scope.querySelectorAll("a[href]"))
                        .map((link) => normalizeText(link.innerText || link.title))
                        .find((value) => /(店|厂|公司|商行|贸易|旗舰|专营|批发)/.test(value) && value !== title);
                    const shopLine = lines.find((line) => /(店|厂|公司|商行|贸易|旗舰|专营|批发)/.test(line) && line !== title);

                    products.push({
                        title,
                        price: priceMatch ? priceMatch[1] : null,
                        sales: salesMatch ? salesMatch[1] : null,
                        shop_name: shopLink || shopLine || null,
                        shop_level: shopLevelMatch ? shopLevelMatch[1].replace(/\\s+/g, "") : null,
                        province: provinceMatch ? provinceMatch[1] : null,
                        support_drop_shipping: dropShipping,
                        image_url: imageUrl,
                        product_url: url,
                        raw_text: text,
                    });
                    seen.add(url);
                }

                if (products.length < maxProducts) {
                    const html = document.documentElement.outerHTML;
                    const idMatches = Array.from(
                        html.matchAll(/(?:"offerId"|"offer_id"|"id")\\s*[:=]\\s*"?([0-9]{8,})"?/g)
                    );

                    for (const match of idMatches) {
                        if (products.length >= maxProducts) {
                            break;
                        }

                        const offerId = match[1];
                        const url = `https://detail.1688.com/offer/${offerId}.html`;
                        if (seen.has(url)) {
                            continue;
                        }

                        products.push({
                            title: null,
                            price: null,
                            sales: null,
                            shop_name: null,
                            shop_level: null,
                            province: null,
                            support_drop_shipping: false,
                            image_url: null,
                            product_url: url,
                            raw_text: "",
                        });
                        seen.add(url);
                    }
                }

                return products;
            }
            """,
            max_products,
        )

    def _normalize_products(
        self,
        keyword: str,
        raw_products: list[dict[str, Any]],
    ) -> list[CrawledProduct]:
        """清洗并限制采集结果数量。"""
        products: list[CrawledProduct] = []

        for raw_product in raw_products[: self.max_products]:
            title = self._clean_text(raw_product.get("title"))
            product_url = self._clean_text(raw_product.get("product_url"))

            # 没有标题和链接的记录通常不是有效商品，直接跳过。
            if not title and not product_url:
                continue

            if self._is_invalid_product(title, product_url):
                continue

            products.append(
                CrawledProduct(
                    keyword=keyword,
                    title=title,
                    price=self._clean_text(raw_product.get("price")),
                    sales=self._clean_text(raw_product.get("sales")),
                    shop_name=self._clean_text(raw_product.get("shop_name")),
                    shop_level=self._clean_text(raw_product.get("shop_level")),
                    province=self._clean_text(raw_product.get("province")),
                    support_drop_shipping=bool(
                        raw_product.get("support_drop_shipping", False)
                    ),
                    image_url=self._clean_text(raw_product.get("image_url")),
                    product_url=product_url,
                )
            )

        return products

    @staticmethod
    def _clean_text(value: Any) -> str | None:
        """清洗页面提取出的文本。"""
        if value is None:
            return None

        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _is_invalid_product(title: str | None, product_url: str | None) -> bool:
        """判断提取结果是否明显不是商品。"""
        invalid_title_keywords = ("点我反馈", "验证码", "安全验证", "访问受限")
        invalid_url_keywords = ("feedback", "____tmd____", "x5secdata", "offer_search")

        if title and any(keyword in title for keyword in invalid_title_keywords):
            return True

        if product_url:
            lowered_url = product_url.lower()
            if any(keyword in lowered_url for keyword in invalid_url_keywords):
                return True

            return "detail.1688.com/offer/" not in lowered_url and "/offer/" not in lowered_url

        return False
