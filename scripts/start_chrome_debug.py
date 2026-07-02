"""启动可被采集器接管的 Chrome 调试浏览器。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def find_chrome() -> Path:
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


def main() -> None:
    """启动 Chrome 调试实例。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9223)
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    profile_dir = project_root / "data" / "market_price_chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    chrome_path = find_chrome()
    command = [
            str(chrome_path),
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "--window-size=1440,1000",
    ]
    if args.login:
        command.append("https://login.1688.com/")
    if args.headless:
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
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" and args.headless else 0,
    )

    print(f"Chrome 调试浏览器已启动：http://127.0.0.1:{args.port}")
    if args.login:
        print("请在打开的 Chrome 窗口里登录 1688。登录完成后不要关闭这个窗口。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
