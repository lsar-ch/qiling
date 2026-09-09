"""录制接口 stub（Step 10 预留，HTTP 200 + TODO）。

契约见 packages/contracts/py/deskmate_contracts/recording.py；
真实录制（屏幕/音频/数字人）在后续版本接入，V1 只保证端点可用。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["recording"])


@router.get("/recording/status")
async def recording_status(request: Request) -> dict:
    """当前是否有活跃录制会话。"""
    # TODO: 接入实际录制管理器
    return {"active_session": None, "message": "录制功能待实现"}


@router.post("/recording/start")
async def recording_start(request: Request, body: dict) -> dict:
    """开始录制。"""
    # TODO: 接入实际录制管理器
    return {"status": "not_implemented", "message": "录制功能待实现"}


@router.post("/recording/stop")
async def recording_stop(request: Request) -> dict:
    """停止录制并导出。"""
    # TODO: 接入实际录制管理器
    return {"status": "not_implemented", "message": "录制功能待实现"}
