"""本地任务分流规则。

Step 6 的最小实现：先稳定把输入分到四类，不接真实执行器。
"""

from __future__ import annotations

import re

from deskmate_contracts.task import Task

_HIGH_RISK_PATTERNS = (
    r"删除",
    r"移除",
    r"清空",
    r"清除",
    r"支付",
    r"付款",
    r"转账",
    r"提交",
    r"发送",
    r"发布",
    r"发给",
    r"修改.*配置",
    r"更改.*配置",
    r"修改.*设置",
    r"更改.*设置",
    r"改.*密钥",
    r"改.*密码",
    r"改.*权限",
    r"delete",
    r"remove",
    r"pay",
    r"transfer",
    r"submit",
    r"send",
    r"publish",
    r"delete files?",
    r"change settings?",
    r"update config",
)

_ANSWER_HINTS = (
    r"是什么",
    r"怎么",
    r"为什么",
    r"解释",
    r"说明",
    r"总结",
    r"分析",
    r"对比",
    r"列出",
    r"介绍",
    r"聊聊",
    r"整理",
    r"what is",
    r"how to",
    r"why",
    r"explain",
    r"summarize",
    r"在吗",
    r"你好",
    r"嗨",
    r"什么意思",
    r"啥意思",
    r"在干嘛",
    r"干嘛呢",
    r"hey",
)

_FRONTEND_HINTS = (
    r"打开(网页|浏览器|链接)",
    r"搜索",
    r"查找",
    r"点击",
    r"切换",
    r"滚动",
    r"复制",
    r"粘贴",
    r"输入",
    r"展示",
    r"查看页面",
    r"打开页面",
    r"浏览一下",
    r"look up",
    r"search",
    r"click",
    r"open",
    r"scroll",
)

_BACKEND_HINTS = (
    r"代码",
    r"项目",
    r"仓库",
    r"文件",
    r"测试",
    r"修复",
    r"重构",
    r"实现",
    r"生成",
    r"整理",
    r"批量",
    r"部署",
    r"日志",
    r"代码结构",
    r"技术方案",
    r"错别字",
    r"文档",
    r"排版",
    r"依赖",
    r"版本",
    r"构建",
    r"任务",
    r"agent",
    r"codex",
    r"claude",
)

# 真实指令的动词特征：用于把「顺口一说」和「真让它干活」分开。
# 只影响风险档位（是否会自动起跑）与短句判定，不改变四类的匹配顺序。
# 刻意不收「帮我 / 请帮 / 给我」这类泛化前缀——「帮我倒杯水」仍是闲聊。
_ACTION_HINTS = (
    r"查一下",
    r"查查",
    r"看一下",
    r"改一下",
    r"写一下",
    r"做一下",
    r"跑一下",
    r"整理",
    r"检查",
    r"修复",
    r"优化",
)
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _guess_permission_gate(permission_level: str, category: str, risk_level: str) -> bool:
    permission = (permission_level or "confirm_risky").strip().lower()
    if permission in {"confirm_all", "read_only"}:
        return category != "answer"
    if permission == "confirm_risky":
        return risk_level == "high"
    return category != "answer"


def classify_task_input(text: str, permission_level: str = "confirm_risky") -> Task:
    """把输入分到 answer / execute_frontend / delegate_backend / request_approval。"""
    normalized = normalize_text(text)
    compact = normalized.replace(" ", "")

    if _matches_any(normalized, _HIGH_RISK_PATTERNS):
        category = "request_approval"
        risk_level = "high"
        complexity = "complex"
        estimated_duration = "long"
        preferred_executor = None
    elif (
        _matches_any(normalized, _ANSWER_HINTS)
        or "?" in normalized
        or "？" in normalized
        or (
            len(compact) <= 12
            and not _matches_any(normalized, _BACKEND_HINTS)
            and not _matches_any(normalized, _ACTION_HINTS)
        )
    ) and not _matches_any(normalized, _FRONTEND_HINTS) and not (
        _matches_any(normalized, _BACKEND_HINTS)
        and _matches_any(normalized, (r"整理", r"修改", r"帮我", r"更新", r"新建"))
    ):
        category = "answer"
        risk_level = "low"
        complexity = "simple"
        estimated_duration = "short"
        preferred_executor = None
    elif _matches_any(normalized, _FRONTEND_HINTS):
        category = "execute_frontend"
        risk_level = "low"
        complexity = "simple"
        estimated_duration = "short"
        preferred_executor = "frontend"
    else:
        category = "delegate_backend"
        risk_level = (
            "medium"
            if _matches_any(normalized, _BACKEND_HINTS) or _matches_any(normalized, _ACTION_HINTS)
            else "low"
        )
        complexity = "complex" if _matches_any(normalized, (r"批量", r"多步", r"多阶段", r"项目", r"代码", r"测试", r"分析")) else "medium"
        estimated_duration = "long" if complexity == "complex" else "medium"
        # 分流器不指定具体执行器：由 config/agents.yaml 的 default_executor 决定，
        # 避免把某个后端工具硬编码进路由逻辑（旧值 "codex" 会让默认执行器配置失效）。
        preferred_executor = None

    required_approval = _guess_permission_gate(permission_level, category, risk_level)
    if required_approval:
        category = "request_approval"
        risk_level = "high" if risk_level == "high" else "medium"
        complexity = "complex" if complexity == "complex" else "medium"
        estimated_duration = "long" if estimated_duration == "long" else "medium"
        preferred_executor = None

    return Task(
        input=text,
        category=category,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        complexity=complexity,  # type: ignore[arg-type]
        estimated_duration=estimated_duration,  # type: ignore[arg-type]
        required_approval=required_approval,
        preferred_executor=preferred_executor,
        status="awaiting_approval" if category == "request_approval" else "queued",
    )
