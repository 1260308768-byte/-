# 1688选品助手

1688选品助手是一个第一阶段原型项目：输入 1688 搜索关键词，使用 Playwright 采集前 30 个商品，保存到 SQLite，并通过 FastAPI + Jinja2 + Bootstrap 页面展示。

## 当前功能

- 首页关键词搜索。
- Playwright 访问 1688 搜索结果页。
- 采集商品标题、价格、销量、店铺、地区、图片、商品链接等字段。
- SQLAlchemy 保存到 SQLite。
- 商品列表分页展示。
- 日志写入 `logs/app.log`。
- Docker 和 docker-compose 运行。

## 项目结构

```text
app/
├── api/
│   └── routes.py
├── crawler/
│   └── product_crawler.py
├── database/
│   ├── db.py
│   └── init_db.py
├── models/
│   └── product.py
├── services/
│   └── product_service.py
├── templates/
│   ├── index.html
│   └── products.html
├── static/
│   └── css/
│       └── style.css
├── utils/
│   └── logger.py
├── config/
│   └── settings.py
└── main.py
logs/
│   └── app.log
data/
└── products.db
requirements.txt
Dockerfile
docker-compose.yml
README.md
.env.example
```

## 本地运行

先安装依赖：

```bash
pip install -r requirements.txt
playwright install chromium
```

复制环境变量文件：

```bash
copy .env.example .env
```

初始化数据库：

```bash
python -m app.database.init_db
```

启动服务：

```bash
uvicorn app.main:app --reload
```

访问：

```text
http://127.0.0.1:8000
```

运行烟测：

```bash
python tests/smoke_test.py
```

运行服务层测试：

```bash
python tests/service_test.py
```

## Docker 运行

复制环境变量文件：

```bash
copy .env.example .env
```

启动：

```bash
docker compose up --build
```

访问：

```text
http://127.0.0.1:8000
```

## 生产部署

推荐使用一台 Linux VPS，通过 Docker Compose + Caddy 部署。Caddy 会负责反向代理；如果配置了域名，会自动申请 HTTPS 证书。

服务器需要安装：

```bash
docker
docker compose
git
```

首次部署：

```bash
git clone <你的仓库地址> ai-commerce-os
cd ai-commerce-os
cp .env.production.example .env.production
```

如果暂时没有域名，保持：

```text
DOMAIN=:80
```

如果已经有域名，例如 `ai.example.com`，先把域名 A 记录解析到服务器 IP，然后修改：

```text
DOMAIN=ai.example.com
```

启动生产服务：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

查看状态：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f app
```

更新部署：

```bash
git pull
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

生产数据会持久化在服务器项目目录：

```text
data/
logs/
tmp/
```

注意：线上 Docker 默认使用无头浏览器采集。1688、淘宝等平台可能触发登录、验证码或风控；这类登录态更适合在本地手动浏览器模式调试，线上环境建议先作为后台系统和结果展示服务运行。

### 本地采集 Worker 模式

如果服务器 IP 被 1688 风控，可以让服务器只负责网站和任务队列，本地电脑负责真实采集。

服务器 `.env` 开启：

```text
REMOTE_WORKER_ENABLED=true
WORKER_TOKEN=替换成一段足够长的随机字符串
```

本地电脑 `.env` 配置：

```text
WORKER_SERVER_URL=http://服务器公网IP:8000
WORKER_TOKEN=和服务器一致的随机字符串
WORKER_CLIENT_ID=网页右上角显示的采集端 ID
CRAWLER_HEADLESS=false
CRAWLER_MANUAL_MODE=true
CRAWLER_BROWSER_CHANNEL=msedge
CRAWLER_TIMEOUT_MS=180000
CRAWLER_MANUAL_WAIT_MS=180000
CRAWLER_USER_DATA_DIR=data/playwright_profile
```

多人使用时，每个用户都应该使用自己的 `WORKER_CLIENT_ID`。网页右上角会显示当前浏览器的采集端 ID，本地 Worker 的 `.env` 必须配置成同一个值，这样该用户创建的任务才会派发到自己的电脑。

本地启动 Worker：

```bash
python scripts/local_worker.py
```

之后用户在公网网站创建 AI 选品任务，服务器会显示等待/采集中；本地 Worker 领取任务、使用本地浏览器采集 1688，并把结果回传服务器进行去重、评分、推荐和报告生成。

AI 选品结果页中的淘宝市场价采集也复用同一个 Worker。用户点击“登录淘宝”时，服务器会通知本地 Worker 在本机打开淘宝登录浏览器；用户完成登录后点击“采集市场价”，本地 Worker 会用商品图片搜索淘宝同款，并回传当前页面前三条价格。

## 环境变量

```text
APP_NAME=1688选品助手
DATABASE_URL=sqlite:///data/products.db
LOG_FILE=logs/app.log
CRAWLER_SEARCH_URL=https://s.1688.com/selloffer/offer_search.htm
CRAWLER_MAX_PRODUCTS=30
CRAWLER_TIMEOUT_MS=30000
CRAWLER_HEADLESS=true
CRAWLER_MANUAL_MODE=false
CRAWLER_MANUAL_WAIT_MS=60000
CRAWLER_USER_DATA_DIR=data/playwright_profile
CRAWLER_CDP_URL=
REMOTE_WORKER_ENABLED=false
WORKER_SERVER_URL=http://127.0.0.1:8000
WORKER_TOKEN=change-me
WORKER_CLIENT_ID=client-demo
WORKER_POLL_INTERVAL_SECONDS=5
```

`DATABASE_URL` 使用相对路径时，会自动按项目根目录解析。

## 注意事项

1688 可能出现验证码、登录提示或风控页面。当前版本会识别常见风控和反馈页面，并返回 0 条采集结果，避免把无效页面写入数据库。检测到风控时，会保存 `logs/blocked_page.html` 和 `logs/blocked_page.png` 方便排查。

如果需要本地手动处理 1688 验证，可以在 `.env` 中设置：

```text
CRAWLER_HEADLESS=false
CRAWLER_MANUAL_MODE=true
```

然后从终端启动服务。触发采集后，Playwright 会打开一个独立 Chromium。请在这个 Chromium 里登录 1688 或完成验证；登录状态会保存在 `data/playwright_profile`，后续采集会复用。

如果想复用你自己的浏览器登录态，需要先用远程调试端口启动 Chrome 或 Edge，然后设置：

```text
CRAWLER_CDP_URL=http://127.0.0.1:9222
```

Windows 示例：

```powershell
Start-Process "msedge.exe" -ArgumentList "--remote-debugging-port=9222"
```

浏览器打开后，在这个带调试端口的窗口里登录 1688，再启动采集。

第一阶段只实现基础采集、异常处理、日志记录、数据库保存和页面展示，不包含登录系统、复杂反爬、AI 分析、利润分析或图片处理。
