"""Agent catalog：从 YAML 构建可扩展执行器目录。

默认读取 config/agents.yaml；支持同目录 agents.local.yaml 按 name 覆盖/追加。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import repo_root


class AgentCatalogError(RuntimeError):
    """Agent catalog 缺失、解析失败或结构不符合约定。"""


@dataclass
class AgentCatalogEntry:
    name: str
    label: str
    adapter: str
    enabled: bool
    commands: list[str]
    protocol: str | None
    capabilities: list[str]
    source_url: str | None
    tags: list[str]
    detail: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCatalog:
    version: str = "1"
    default_executor: str = "codex"
    executors: list[AgentCatalogEntry] = field(default_factory=list)


def load_agent_catalog(path: Path | None = None) -> AgentCatalog:
    """加载 AgentCatalog，并按需合并同一目录下的 agents.local.yaml。"""
    if path is None:
        configured_path = os.environ.get("DESKMATE_AGENTS_CONFIG")
        path = Path(configured_path) if configured_path else repo_root() / "config" / "agents.yaml"

    catalog_path = path.expanduser().resolve()
    data = _read_yaml_file(catalog_path)
    entries = _parse_executors(data, catalog_path)
    entries = _merge_local_executors(catalog_path, entries)

    raw_version = data.get("version", "1")
    raw_default = data.get("default_executor") or "codex"
    return AgentCatalog(
        version=str(raw_version),
        default_executor=str(raw_default),
        executors=entries,
    )


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AgentCatalogError(
            f"Agent catalog 配置文件不存在：{path}。"
            "请检查 config/agents.yaml，或设置 DESKMATE_AGENTS_CONFIG 指定目录。"
        )

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise AgentCatalogError(f"Agent catalog 配置文件读取失败（{path}）：{exc}") from exc

    if not isinstance(data, dict):
        raise AgentCatalogError(f"Agent catalog 顶层必须是映射（{path}）。")
    return data


def _parse_executors(data: dict[str, Any], source: Path) -> list[AgentCatalogEntry]:
    raw_executors = data.get("executors")
    if not isinstance(raw_executors, list):
        raise AgentCatalogError(
            f"Agent catalog 结构错误：缺少 executors 列表（{source}）。"
        )

    entries: list[AgentCatalogEntry] = []
    seen: set[str] = set()
    for raw in raw_executors:
        entry = _entry_from_dict(raw, source)
        if entry.name in seen:
            raise AgentCatalogError(f"Agent catalog 存在重复执行器 name={entry.name}（{source}）。")
        seen.add(entry.name)
        entries.append(entry)
    return entries


def _merge_local_executors(
    catalog_path: Path,
    entries: list[AgentCatalogEntry],
) -> list[AgentCatalogEntry]:
    local_path = catalog_path.with_name("agents.local.yaml")
    if not local_path.exists():
        return entries

    data = _read_yaml_file(local_path)
    raw_executors = data.get("executors")
    if not isinstance(raw_executors, list):
        raise AgentCatalogError(
            f"Agent local catalog 结构错误：缺少 executors 列表（{local_path}）。"
        )

    merged = {entry.name: asdict(entry) for entry in entries}
    order = list(entries)
    order_index: dict[str, int] = {entry.name: index for index, entry in enumerate(order)}
    for raw in raw_executors:
        if not isinstance(raw, dict) or not raw.get("name"):
            raise AgentCatalogError(
                f"Agent local catalog 条目缺少 name（{local_path}）。"
            )
        name = str(raw["name"]).strip()
        if not name:
            raise AgentCatalogError(f"Agent local catalog 条目 name 不能为空（{local_path}）。")

        base = merged.get(name)
        merged_raw = {**(base or {}), **raw}
        entry = _entry_from_dict(merged_raw, local_path)
        merged[name] = asdict(entry)
        if name not in order_index:
            order_index[name] = len(order)
            order.append(entry)
        else:
            order[order_index[name]] = entry

    return order


def _entry_from_dict(raw: object, source: Path) -> AgentCatalogEntry:
    if not isinstance(raw, dict):
        raise AgentCatalogError(f"Agent catalog 执行器条目必须是映射（{source}）。")

    name = str(raw.get("name") or "").strip()
    if not name:
        raise AgentCatalogError(f"Agent catalog 执行器条目缺少 name（{source}）。")

    commands = _as_string_list(raw.get("commands"), f"name={name} commands", source)
    if not commands:
        raise AgentCatalogError(
            f"Agent catalog 执行器 name={name} 的 commands 为空或缺失（{source}）。"
        )

    return AgentCatalogEntry(
        name=name,
        label=str(raw.get("label") or name),
        adapter=str(raw.get("adapter") or "pending"),
        enabled=_as_bool(raw.get("enabled", True), f"name={name} enabled", source),
        commands=commands,
        protocol=_as_optional_string(raw.get("protocol"), f"name={name} protocol", source),
        capabilities=_as_string_list(raw.get("capabilities"), f"name={name} capabilities", source),
        source_url=_as_optional_string(raw.get("source_url"), f"name={name} source_url", source),
        tags=_as_string_list(raw.get("tags"), f"name={name} tags", source),
        detail=str(raw.get("detail") or ""),
        config=_as_mapping(raw.get("config"), f"name={name} config", source),
    )


def _as_string_list(value: object, label: str, source: Path) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AgentCatalogError(f"Agent catalog {label} 必须是字符串列表（{source}）。")
    if not all(isinstance(item, str) for item in value):
        raise AgentCatalogError(f"Agent catalog {label} 只能包含字符串（{source}）。")
    return [item.strip() for item in value if item.strip()]


def _as_optional_string(value: object, label: str, source: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AgentCatalogError(f"Agent catalog {label} 必须是字符串或 null（{source}）。")
    return value.strip() or None


def _as_mapping(value: object, label: str, source: Path) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AgentCatalogError(f"Agent catalog {label} 必须是映射或 null（{source}）。")
    return value


def _as_bool(value: object, label: str, source: Path) -> bool:
    if isinstance(value, bool):
        return value
    raise AgentCatalogError(f"Agent catalog {label} 必须是布尔值（{source}）。")


__all__ = [
    "AgentCatalog",
    "AgentCatalogEntry",
    "AgentCatalogError",
    "load_agent_catalog",
]
