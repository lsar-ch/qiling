"""离线 ACP stdio fixture：仅用于协议回归，不访问网络或本机文件。"""

from __future__ import annotations

import json
import sys


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for raw in sys.stdin:
    message = json.loads(raw)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": 1}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "offline-session"}})
    elif method == "session/prompt":
        send(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": "离线模拟结果",
                    }
                },
            }
        )
        send({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}})
    elif request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
