"""本机浏览器路径识别工具。"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys


def find_chromium_browser_path(
    preferred_path: str | None = None,
    use_default_browser: bool = True,
) -> Path | None:
    """查找可用于 Playwright 自动化的 Chromium 系浏览器路径。"""
    candidates: list[Path] = []
    if preferred_path:
        candidates.append(Path(preferred_path.strip().strip('"')))

    if use_default_browser:
        default_browser = get_windows_default_browser_path()
        if default_browser:
            candidates.append(default_browser)

    candidates.extend(_known_chromium_browser_paths())
    for candidate in candidates:
        if candidate and candidate.exists() and candidate.is_file():
            return candidate
    return None


def get_windows_default_browser_path() -> Path | None:
    """读取 Windows 默认 https 浏览器的可执行文件路径。"""
    if sys.platform != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    prog_id = _read_registry_value(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        "ProgId",
    )
    if not prog_id:
        return None

    command = (
        _read_registry_value(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{prog_id}\shell\open\command",
            "",
        )
        or _read_registry_value(
            winreg.HKEY_LOCAL_MACHINE,
            rf"Software\Classes\{prog_id}\shell\open\command",
            "",
        )
        or _read_registry_value(
            winreg.HKEY_CLASSES_ROOT,
            rf"{prog_id}\shell\open\command",
            "",
        )
    )
    return _extract_executable_path(command)


def _read_registry_value(root: object, path: str, name: str) -> str | None:
    """安全读取注册表字符串。"""
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return None


def _extract_executable_path(command: str | None) -> Path | None:
    """从注册表 open command 中提取 exe 路径。"""
    if not command:
        return None

    quoted = re.match(r'^"([^"]+\.exe)"', command, flags=re.I)
    if quoted:
        return Path(quoted.group(1))

    unquoted = re.match(r"^([^\s]+\.exe)", command, flags=re.I)
    if unquoted:
        return Path(unquoted.group(1))

    return None


def _known_chromium_browser_paths() -> list[Path]:
    """返回常见 Chrome 和 Edge 安装路径。"""
    return [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
