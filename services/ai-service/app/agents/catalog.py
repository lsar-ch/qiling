"""Agent catalog：从 YAML 构建可扩展执行器目录。

默认读取 config/agents.yaml；支持同目录 agents.local.yaml 按 name 覆盖/追加。
"""

from __future__ import annotations

import os
import tempfile
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


def default_catalog_path() -> Path:
    """默认执行器目录路径（支持 QILING_AGENTS_CONFIG 覆盖）。"""
    configured_path = os.environ.get("QILING_AGENTS_CONFIG")
    return Path(configured_path) if configured_path else repo_root() / "config" / "agents.yaml"


def local_catalog_path(catalog_path: Path) -> Path:
    """同一目录下的用户配置覆盖层文件。"""
    return catalog_path.with_name("agents.local.yaml")


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写入文本文件，失败时清理临时文件并上抛。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".agents-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_LOCAL_HEADER = (
    "# 栖灵 用户配置覆盖层：由「我的智能体」页面写入，请勿手改。\n"
    "# 默认目录见 agents.yaml；覆盖优先级：agents.local.yaml > agents.yaml。\n"
)


def _read_local_overlay(local_path: Path) -> tuple[str | None, list[dict[str, Any]]]:
    """读取覆盖层，返回 (default_executor, executors)；缺失或损坏按空处理。"""
    if not local_path.exists():
        return None, []
    try:
        data = _read_yaml_file(local_path)
    except AgentCatalogError:
        return None, []
    raw_default = data.get("default_executor")
    default_name = str(raw_default).strip() if raw_default else ""
    raw_executors = data.get("executors")
    executors = (
        [entry for entry in raw_executors if isinstance(entry, dict)]
        if isinstance(raw_executors, list)
        else []
    )
    return (default_name or None), executors


def _write_local_overlay(
    local_path: Path,
    default_executor: str | None,
    executors: list[dict[str, Any]],
) -> None:
    """整体重写覆盖层：default_executor 为空则不落该键。"""
    payload: dict[str, Any] = {"version": 1}
    if default_executor:
        payload["default_executor"] = default_executor
    payload["executors"] = executors
    _atomic_write_text(
        local_path,
        _LOCAL_HEADER
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
    )


def _local_entry(executors: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """取 name 的覆盖层条目，不存在则追加一条。"""
    for entry in executors:
        if entry.get("name") == name:
            return entry
    entry = {"name": name}
    executors.append(entry)
    return entry


def update_local_executor_config(
    catalog_path: Path,
    name: str,
    config: dict[str, Any],
) -> None:
    """把 name 执行器的 config 键合并写入同目录 agents.local.yaml。

    config 中值为 None 的键会被删除；写入后由调用方重载目录生效。
    """
    local_path = local_catalog_path(catalog_path)
    default_executor, executors = _read_local_overlay(local_path)
    entry = _local_entry(executors, name)
    merged = dict(entry.get("config") or {})
    for key, value in config.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    if merged:
        entry["config"] = merged
    else:
        entry.pop("config", None)
    _write_local_overlay(local_path, default_executor, executors)


def migrate_legacy_executor_secret(
    name: str,
    store,
    catalog_path: Path | None = None,
) -> bool:
    """把旧版明文执行器 Key 迁移到安全存储；失败时保留原配置。"""
    path = (catalog_path or default_catalog_path()).expanduser().resolve()
    local_path = local_catalog_path(path)
    if not local_path.exists():
        return False
    default_executor, executors = _read_local_overlay(local_path)
    entry = next((item for item in executors if item.get("name") == name), None)
    if entry is None:
        return False
    config = dict(entry.get("config") or {})
    key_name = f"{name}_api_key"
    value = str(config.get(key_name) or "").strip()
    if not value:
        return False
    store.store(name, value)
    config.pop(key_name, None)
    if config:
        entry["config"] = config
    else:
        entry.pop("config", None)
    _write_local_overlay(local_path, default_executor, executors)
    return True


def update_local_default_executor(catalog_path: Path, name: str) -> None:
    """把 name 写成覆盖层默认执行器，压过 agents.yaml 的默认值。"""
    local_path = local_catalog_path(catalog_path)
    _, executors = _read_local_overlay(local_path)
    _write_local_overlay(local_path, name, executors)


def add_local_executor(catalog_path: Path, entry: dict[str, Any]) -> None:
    """把用户自定义执行器整条写进覆盖层；同名时整条替换。"""
    local_path = local_catalog_path(catalog_path)
    default_executor, executors = _read_local_overlay(local_path)
    name = str(entry.get("name") or "").strip()
    if not name:
        raise ValueError("自定义执行器缺少 name")
    for item in executors:
        if item.get("name") == name:
            item.clear()
            item.update(entry)
            break
    else:
        executors.append(dict(entry))
    _write_local_overlay(local_path, default_executor, executors)


def update_local_executor_enabled(catalog_path: Path, name: str, enabled: bool) -> None:
    """写 name 执行器的 enabled 开关；写入后由调用方重载目录生效。"""
    local_path = local_catalog_path(catalog_path)
    default_executor, executors = _read_local_overlay(local_path)
    entry = _local_entry(executors, name)
    entry["enabled"] = bool(enabled)
    _write_local_overlay(local_path, default_executor, executors)


def load_agent_catalog(path: Path | None = None) -> AgentCatalog:
    """加载 AgentCatalog，并按需合并同一目录下的 agents.local.yaml。"""
    if path is None:
        path = default_catalog_path()

    catalog_path = path.expanduser().resolve()
    data = _read_yaml_file(catalog_path)
    entries = _parse_executors(data, catalog_path)
    entries, local_default = _merge_local_executors(catalog_path, entries)

    raw_version = data.get("version", "1")
    raw_default = local_default or data.get("default_executor") or "codex"
    shipped_default = str(data.get("default_executor") or "codex")
    return AgentCatalog(
        version=str(raw_version),
        default_executor=_usable_default(entries, str(raw_default), shipped_default),
        executors=entries,
    )


def _usable_default(
    entries: list[AgentCatalogEntry],
    chosen: str,
    shipped: str,
) -> str:
    """默认执行器必须真实存在且处于启用态。

    覆盖层可能留下一个指向「已被停用/已移除条目」的默认值（例如某个执行器改成
    按需安装后，老用户的 agents.local.yaml 仍写着它）——那时不能让整个应用带着
    一个跑不起来的默认执行器启动，回退到出厂默认，再回退到第一个启用的条目。
    """
    by_name = {entry.name: entry for entry in entries}
    if chosen in by_name and by_name[chosen].enabled:
        return chosen
    if shipped in by_name and by_name[shipped].enabled:
        return shipped
    for entry in entries:
        if entry.enabled:
            return entry.name
    return chosen


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AgentCatalogError(
            f"Agent catalog 配置文件不存在：{path}。"
            "请检查 config/agents.yaml，或设置 QILING_AGENTS_CONFIG 指定目录。"
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
) -> tuple[list[AgentCatalogEntry], str | None]:
    """合并 local 覆盖层，并返回其默认执行器（未设置时为 None）。"""
    local_path = catalog_path.with_name("agents.local.yaml")
    if not local_path.exists():
        return entries, None

    data = _read_yaml_file(local_path)
    raw_local_default = data.get("default_executor")
    local_default = str(raw_local_default).strip() if raw_local_default else None
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
        base_config = (base or {}).get("config")
        raw_config = raw.get("config")
        if isinstance(base_config, dict) and isinstance(raw_config, dict):
            merged_raw["config"] = {**base_config, **raw_config}
        entry = _entry_from_dict(merged_raw, local_path)
        merged[name] = asdict(entry)
        if name not in order_index:
            order_index[name] = len(order)
            order.append(entry)
        else:
            order[order_index[name]] = entry

    return order, local_default


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
    "add_local_executor",
    "AgentCatalogEntry",
    "AgentCatalogError",
    "load_agent_catalog",
]
