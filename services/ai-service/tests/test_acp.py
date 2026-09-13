"""ACP 客户端最小协议测试：登录态错误必须与普通协议错误分开。"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.acp import AcpClient, AcpRequestError


def test_acp_auth_error_is_marked_auth_required() -> None:
    async def scenario() -> None:
        client = object.__new__(AcpClient)
        client._requests = {}
        future = asyncio.get_running_loop().create_future()
        client._requests[7] = future
        await client._dispatch(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "error": {"code": -32000, "message": "Authentication required"},
            }
        )
        with pytest.raises(AcpRequestError) as exc_info:
            future.result()
        assert exc_info.value.auth_required is True

    asyncio.run(scenario())


def test_acp_other_error_is_not_auth_required() -> None:
    async def scenario() -> None:
        client = object.__new__(AcpClient)
        client._requests = {}
        future = asyncio.get_running_loop().create_future()
        client._requests[8] = future
        await client._dispatch(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "error": {"code": -32601, "message": "Method not found"},
            }
        )
        with pytest.raises(AcpRequestError) as exc_info:
            future.result()
        assert exc_info.value.auth_required is False

    asyncio.run(scenario())
