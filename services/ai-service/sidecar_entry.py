"""打包入口：以冻结二进制形式启动 ai-service（开发态仍用 uvicorn 命令）。"""
from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("QILING_HOST", "127.0.0.1"),
        port=int(os.environ.get("QILING_PORT", "8736")),
        log_level="info",
    )
