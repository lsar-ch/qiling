"""浏览器执行器适配器：Playwright headless、只读网页任务。

V1.1 窄场景：打开搜索、读页面、翻页。本版本只实现「搜索一个主题并返回
前几条摘要」，作为端到端验收的代表任务。登录/提交/删除等敏感动作在
prompt 出现时直接拒绝，不进入浏览器。
"""

from __future__ import annotations

import asyncio
import logging
import re
import webbrowser
from pathlib import Path

from deskmate_contracts.agent import AgentInfo

from app.agents.base import (
    AgentAdapter,
    AgentExecutionError,
    AgentTaskRequest,
    AgentTaskResult,
)
from app.agents.catalog import AgentCatalogEntry

logger = logging.getLogger(__name__)

_LIMIT_HINTS = re.compile(r"前\s*(\d+)\s*条")
_SENSITIVE = re.compile(r"登录|验证码|提交|发送|删除|支付|付款|转账|下载|购买|注册|填写.*表单")
_DEFAULT_LIMIT = 5
_BACKEND_TOPIC = re.compile(r"代码|项目|仓库|重构|部署|接口|报错|函数|api|sdk")
_OPEN_VERBS = re.compile(r"打开|访问|进入")
# 常见站点直连表：分词不可靠的中文站名直接走官方域名，兜底才用搜索。
# 打开新站时在这里加一行即可。
_KNOWN_SITES: dict[str, str] = {
    "闲鱼": "https://www.goofish.com",
    "咸鱼": "https://www.goofish.com",
    "淘宝": "https://www.taobao.com",
    "天猫": "https://www.tmall.com",
    "京东": "https://www.jd.com",
    "拼多多": "https://www.pinduoduo.com",
    "知乎": "https://www.zhihu.com",
    "微博": "https://weibo.com",
    "抖音": "https://www.douyin.com",
    "百度": "https://www.baidu.com",
    "哔哩哔哩": "https://www.bilibili.com",
    "bilibili": "https://www.bilibili.com",
    "b站": "https://www.bilibili.com",
    "小红书": "https://www.xiaohongshu.com",
    "github": "https://github.com",
}
_SEARCH_VERBS = re.compile(
    r"^(你|帮我|帮|请|麻烦|给我)?\s*(搜索一下|搜索|搜一下|搜搜|搜|查一下|查查|查一查|查询|查找|找一下|看看|看一下|浏览一下)?\s*"
)
_TRAILING_NOISE = re.compile(
    r"(并返回.*|返回.*|前\s*\d+\s*条.*|的摘要.*|摘要.*|帮我打开.*|帮我看看.*|帮我查.*|帮我搜.*|打开.*|访问.*|，.*|。.*)$"
)
# 动作连词：「搜索并打开 xx」「然后打开 xx」等，先归一为空白再剥离。
_ACTION_JOINERS = re.compile(
    r"搜索并打开|打开并搜索|搜索、打开|并打开|然后打开|再打开|顺便打开|然后搜索|再搜索|并搜索"
)


def is_browser_task(text: str) -> bool:
    """搜索/打开网页类输入交给浏览器执行器；代码/项目类主题仍走默认执行器。"""
    has_action = bool(
        re.search(r"搜索|搜一下|搜搜|查一下|查查|查询|查找|找一下|浏览一下", text)
        or _OPEN_VERBS.search(text)
    )
    return has_action and not _BACKEND_TOPIC.search(text)


def _parse_search_request(text: str) -> tuple[str, int]:
    """把「搜索/打开 某某主题 …」拆成 (query, limit)，剥离语气词与承接词。"""
    limit = _DEFAULT_LIMIT
    matched = _LIMIT_HINTS.search(text)
    if matched:
        limit = max(1, min(int(matched.group(1)), 10))
    query = _ACTION_JOINERS.sub(" ", text).strip()
    for _ in range(3):
        prev = query
        query = _SEARCH_VERBS.sub("", query)
        query = _TRAILING_NOISE.sub("", query)
        if query == prev:
            break
    query = re.sub(r"\s+", " ", query).strip()
    return query or text.strip(), limit


def _known_site(query: str) -> tuple[str, str] | None:
    """已知站点直连：返回 (名称, 官方 URL)，None 表示需要搜索兜底。"""
    for name, url in sorted(_KNOWN_SITES.items(), key=lambda kv: -len(kv[0])):
        if name in query:
            return name, url
    return None


class BrowserAdapter(AgentAdapter):
    name: str = "browser"
    adapter_id: str = "browser"
    display_name: str = "浏览器"
    executable: bool = True

    def __init__(self, catalog_entry: AgentCatalogEntry) -> None:
        self._entry = catalog_entry
        self._cancel_events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------ 探测

    async def detect(self) -> AgentInfo:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return self._info("not_installed", False, detail="Python 环境未安装 playwright，请先 pip install playwright")
        try:
            async with async_playwright() as pw:
                path = Path(pw.chromium.executable_path)
            ok = path.exists()
        except Exception as exc:  # noqa: BLE001
            return self._info("error", False, detail=f"浏览器探测失败：{exc}")
        if not ok:
            return self._info(
                "not_installed",
                False,
                detail="playwright 包已装但 Chromium 未安装，请运行 python -m playwright install chromium",
            )
        return self._info("ready", True, version="chromium", protocol="playwright", detail="可用：只读搜索与读页面")

    def _info(self, status: str, available: bool, **extra) -> AgentInfo:
        return AgentInfo(
            name=self.name,
            label=self.display_name,
            adapter=self.adapter_id,
            enabled=self._entry.enabled,
            integration_status=status,  # type: ignore[arg-type]
            available=available,
            capabilities=self._entry.capabilities,
            tags=self._entry.tags,
            source_url=self._entry.source_url,
            detail=extra.get("detail", self._entry.detail),
            version=extra.get("version"),
            command=extra.get("command"),
            protocol=extra.get("protocol"),
        )

    # ------------------------------------------------------------------ 执行

    async def run(self, request: AgentTaskRequest, on_update) -> AgentTaskResult:
        if _SENSITIVE.search(request.prompt):
            raise AgentExecutionError(
                "这个浏览器任务可能涉及登录/提交/发送/删除/支付等敏感动作，"
                "当前版本只支持只读的搜索与读页面。"
            )
        query, limit = _parse_search_request(request.prompt)
        if not query:
            raise AgentExecutionError("没看懂要搜什么，请说清楚搜索主题。")

        self._cancel_events[request.task_id] = asyncio.Event()
        try:
            if _OPEN_VERBS.search(request.prompt):
                return await self._open_page(request, on_update, query)
            return await self._search(request, on_update, query, limit)
        except asyncio.CancelledError:
            raise
        except AgentExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._cancel_events.get(request.task_id, asyncio.Event()).is_set():
                return AgentTaskResult(status="cancelled", message="浏览器任务已取消")
            raise AgentExecutionError(f"浏览器执行失败：{exc}") from exc
        finally:
            self._cancel_events.pop(request.task_id, None)

    async def _search_items(self, query: str, limit: int) -> list[dict]:
        """Bing 搜索结果（title/url/snippet），纯只读操作。"""
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                url = f"https://www.bing.com/search?q={query}&setlang=zh-hans"
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_selector(".b_algo", state="attached", timeout=30000)
                return await page.eval_on_selector_all(
                    ".b_algo",
                    """els => els.slice(0, %d).map(el => {
                        const a = el.querySelector("h2 a");
                        const cap = el.querySelector(".b_caption p") || el.querySelector("p");
                        return {
                            title: a ? (a.textContent || "").trim() : "",
                            url: a ? a.href : "",
                            snippet: cap ? (cap.textContent || "").trim() : "",
                        };
                    })""" % limit,
                )
            finally:
                await browser.close()

    async def _search(self, request, on_update, query: str, limit: int) -> AgentTaskResult:
        await on_update("progress", {"text": f"正在搜索：{query}", "progress": f"🔍 {query}"})
        items = await self._search_items(query, limit)
        await on_update("progress", {"text": "已打开搜索结果页", "progress": "已打开搜索结果页"})
        lines = [f"{i + 1}. {item['title']}（{item['url']}）\n   {item['snippet']}" for i, item in enumerate(items)]
        message = (
            f"「{query}」搜索结果（前 {len(lines)} 条）：\n\n" + "\n\n".join(lines)
            if lines
            else f"「{query}」没有搜到结果，换个说法试试。"
        )
        await on_update("progress", {"text": "摘要提取完成", "progress": "✅ 摘要提取完成"})
        return AgentTaskResult(status="completed", message=message)

    async def _open_page(self, request, on_update, query: str) -> AgentTaskResult:
        """打开目标：搜索第一个结果 URL，用系统默认浏览器打开。"""
        await on_update("progress", {"text": f"正在找「{query}」的入口…", "progress": f"🔗 {query}"})
        known = _known_site(query)
        if known is not None:
            target = {"title": known[0], "url": known[1]}
        else:
            items = await self._search_items(query, 1)
            if not items or not items[0]["url"]:
                return AgentTaskResult(
                    status="failed",
                    message="",
                    error=f"没找到「{query}」对应的网页，请换个说法。",
                )
            target = items[0]
        await on_update("progress", {"text": "已找到入口，正在打开…", "progress": f"打开 {target['url']}"})
        await asyncio.to_thread(webbrowser.open, target["url"])
        return AgentTaskResult(
            status="completed",
            message=f"已用系统浏览器打开「{target['title'] or query}」：{target['url']}",
        )

    async def cancel(self, task_id: str, session_id: str | None = None) -> None:
        event = self._cancel_events.get(task_id)
        if event is not None:
            event.set()
