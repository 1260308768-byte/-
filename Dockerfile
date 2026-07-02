# 使用 Python 3.12 官方精简镜像。
FROM python:3.12-slim

# 设置容器内工作目录。
WORKDIR /app

# 避免 Python 写入 pyc 文件，并让日志实时输出。
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 先复制依赖文件，利用 Docker 构建缓存。
COPY requirements.txt .

# 安装 Python 依赖和 Playwright Chromium 浏览器依赖。
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

# 复制项目代码。
COPY . .

# 暴露 FastAPI 默认服务端口。
EXPOSE 8000

# 启动 FastAPI 应用。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

