"""本地开发服务启动脚本。"""

from pathlib import Path
import sys

import uvicorn


def main() -> None:
    """启动 FastAPI 本地服务。"""
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
