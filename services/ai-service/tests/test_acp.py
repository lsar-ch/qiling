"""ACP 客户端最小协议测试：登录态错误必须与普通协议错误分开。"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from app.agents.acp import AcpClient, AcpRequestError


def test_acp_reader_survives_oversized_line() -> None:
    """单行 JSON-RPC 超过 asyncio 默认 64 KiB 时，reader 仍要能继续分发。

    回归：长任务里 ACP 端会吐超长单行，默认 limit 会让 readline() 抛
    ValueError，reader 停摆后整条会话被判成「ACP process exited」。
    """

    async def scenario() -> list[dict]:
        seen: list[dict] = []

        async def on_update(update: dict) -> None:
            seen.append(update)

        blob = "x" * (200 * 1024)
        script = (
            "import json, sys\n"
            f"msg = {{'jsonrpc': '2.0', 'method': 'session/update', "
            f"'params': {{'update': {{'blob': '{blob}'}}}}}}\n"
            "sys.stdout.write(json.dumps(msg) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        client = await AcpClient.spawn(
            sys.executable,
            args=["-c", script],
            cwd=os.getcwd(),
            env=dict(os.environ),
            on_update=on_update,
        )
        try:
            for _ in range(50):
                if seen:
                    break
                await asyncio.sleep(0.1)
        finally:
            await client.close()
        return seen

    seen = asyncio.run(scenario())
    assert seen, "超过 64 KiB 的单行被 reader 丢弃了"
    assert len(seen[0]["blob"]) == 200 * 1024


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
