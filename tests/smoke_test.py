"""项目烟测脚本。"""

from __future__ import annotations

import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


BASE_URL = "http://127.0.0.1:8000"


def request_text(path: str, timeout: int = 5) -> str:
    """请求本地服务并返回文本内容。"""
    with urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
        return response.read().decode("utf-8")


def wait_until_ready() -> None:
    """等待本地 FastAPI 服务启动完成。"""
    deadline = time.time() + 20
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            request_text("/health", timeout=2)
            return
        except URLError as exc:
            last_error = exc
            time.sleep(1)

    raise RuntimeError(f"服务启动超时：{last_error}")


def assert_contains(value: str, expected: str) -> None:
    """断言响应文本包含指定内容。"""
    if expected not in value:
        raise AssertionError(f"响应中没有找到内容：{expected}")


def main() -> None:
    """启动服务并验证核心页面。"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_until_ready()
        assert_contains(request_text("/health"), '"status":"ok"')
        assert_contains(request_text("/"), "1688选品助手")
        assert_contains(request_text("/products"), "商品列表")
        print("烟测通过：/health、/、/products 均可访问")
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


if __name__ == "__main__":
    main()

