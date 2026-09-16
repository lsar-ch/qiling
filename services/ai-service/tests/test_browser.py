"""浏览器执行器：搜索请求解析与敏感动作拒绝（不依赖网络）。"""

from __future__ import annotations

import pytest

from app.agents.base import AgentExecutionError
from app.agents.browser import (
    BrowserAdapter,
    _known_site,
    _parse_search_request,
    is_browser_task,
)


def test_parse_search_request_extracts_query_and_limit() -> None:
    assert _parse_search_request("搜索 石家庄中考招生政策 并返回前几条摘要") == ("石家庄中考招生政策", 5)
    assert _parse_search_request("查一下 2026 苹果发布会时间") == ("2026 苹果发布会时间", 5)
    assert _parse_search_request("搜索 量子纠缠 前 3 条") == ("量子纠缠", 3)
    assert _parse_search_request("帮我搜索 python 异步编程 返回前 2 条摘要") == ("python 异步编程", 2)
    assert _parse_search_request("你搜索一下闲鱼主页帮我打开") == ("闲鱼主页", 5)
    assert _parse_search_request("搜索闲鱼主页。") == ("闲鱼主页", 5)
    assert _parse_search_request("搜索并打开闲鱼主页") == ("闲鱼主页", 5)
    assert _parse_search_request("然后打开闲鱼主页") == ("闲鱼主页", 5)


def test_is_browser_task() -> None:
    assert is_browser_task("你搜索一下闲鱼主页帮我打开")
    assert is_browser_task("打开闲鱼主页")
    assert is_browser_task("帮我查一下石家庄中考招生政策")
    assert not is_browser_task("帮我检查这个项目的代码结构")
    assert not is_browser_task("在吗")


def test_known_site_direct_open() -> None:
    assert _known_site("闲鱼主页") == ("闲鱼", "https://www.goofish.com")
    assert _known_site("你知道知乎吗") == ("知乎", "https://www.zhihu.com")
    assert _known_site("石家庄中考招生政策") is None


def test_sensitive_prompts_are_rejected_before_browser() -> None:
    entry = type("E", (), {"enabled": True, "capabilities": [], "tags": [], "source_url": None, "detail": ""})()
    adapter = BrowserAdapter(catalog_entry=entry)

    async def probe(text: str) -> None:
        with pytest.raises(AgentExecutionError, match="敏感"):
            await adapter.run(
                type("R", (), {"task_id": "t", "prompt": text, "cwd": "/"})(),
                on_update=lambda _k, _p: None,
            )

    import asyncio
    for text in ("帮我登录一下网站", "把这个页面内容发送给我", "删除搜索结果页"):
        asyncio.run(probe(text))
