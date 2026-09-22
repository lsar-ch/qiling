"""技能注册表：扫描内置与用户目录，解析 SKILL.md。

目录约定见 docs/EXTENSION-SKELETON-PLAN.md：
- 内置：skills/builtin/<id>/SKILL.md（随仓库，不可删）
- 用户：data/skills/<id>/SKILL.md（运行时）
"""

from __future__ import annotations

import re
import json
import io
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from deskmate_contracts import SkillDetail, SkillInfo


class SkillRegistryError(RuntimeError):
    """技能目录缺失或 SKILL.md 不合法。"""


@dataclass(frozen=True)
class LoadedSkill:
    """已加载技能：契约数据 + 源目录。"""

    info: SkillInfo
    body: str
    path: Path


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def load_skill_markdown(path: Path, source: str) -> LoadedSkill:
    """读取并解析单个 SKILL.md。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillRegistryError(f"SKILL.md 读取失败（{path}）：{exc}") from exc

    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillRegistryError(f"SKILL.md 缺少 frontmatter（{path}）")

    try:
        header = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillRegistryError(f"SKILL.md frontmatter 解析失败（{path}）：{exc}") from exc
    if not isinstance(header, dict):
        raise SkillRegistryError(f"SKILL.md frontmatter 必须是映射（{path}）")

    raw_id = header.get("name")
    skill_id = str(raw_id).strip() if raw_id else ""
    if not skill_id:
        raise SkillRegistryError(f"SKILL.md 缺少 name（{path}）")
    raw_desc = header.get("description")
    description = str(raw_desc).strip() if raw_desc else ""
    if not description:
        raise SkillRegistryError(f"SKILL.md 缺少 description（{path}）")

    def as_str_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    body = match.group(2).strip()
    scripts_dir = path.parent / "scripts"
    has_scripts = scripts_dir.is_dir() and any(scripts_dir.iterdir())
    info = SkillInfo(
        id=skill_id,
        name=skill_id,
        description=description,
        source=source,
        enabled=bool(header.get("enabled", True)),
        triggers=as_str_list(header.get("triggers")),
        tools=as_str_list(header.get("tools")),
        has_scripts=has_scripts,
    )
    return LoadedSkill(info=info, body=body, path=path.parent)


def _scan(directory: Path, source: str) -> dict[str, LoadedSkill]:
    skills: dict[str, LoadedSkill] = {}
    if not directory.is_dir():
        return skills
    for child in sorted(directory.iterdir()):
        skill_md = child / "SKILL.md"
        if not child.is_dir() or not skill_md.is_file():
            continue
        loaded = load_skill_markdown(skill_md, source)
        if loaded.info.id in skills:
            raise SkillRegistryError(f"技能 id 重复：{loaded.info.id}（{directory}）")
        skills[loaded.info.id] = loaded
    return skills


class SkillRegistry:
    """内存态技能注册表；启动时构建，P2 起供分流选择。"""

    def __init__(
        self,
        builtin_dir: Path,
        user_dir: Path,
        state_path: Path | None = None,
    ) -> None:
        state = _read_state(state_path)
        disabled = _read_disabled(state)
        external = _read_external(state)
        self._builtin = _apply_enabled(_scan(builtin_dir, "builtin"), disabled)
        self._user = _apply_enabled(_scan(user_dir, "user"), disabled)
        for skill_id, directory in external.items():
            skill_md = directory / "SKILL.md"
            if directory.is_dir() and skill_md.is_file():
                loaded = load_skill_markdown(skill_md, "user")
                self._user[loaded.info.id] = loaded
        self._user = _apply_enabled(self._user, disabled)
        self._state_path = state_path
        self._user_root = user_dir

    def list(self) -> list[SkillInfo]:
        """摘要列表：内置在前，用户追加。"""
        builtin = [item.info for item in self._builtin.values()]
        user = [item.info for item in self._user.values()]
        return builtin + user

    def enabled(self) -> list[SkillInfo]:
        return [item for item in self.list() if item.enabled]

    def get(self, skill_id: str) -> LoadedSkill | None:
        return self._user.get(skill_id) or self._builtin.get(skill_id)

    def detail(self, skill_id: str) -> SkillDetail | None:
        loaded = self.get(skill_id)
        if loaded is None:
            return None
        data = loaded.info.model_dump()
        return SkillDetail(**data, body=loaded.body)

    def select(self, message: str) -> LoadedSkill | None:
        """按触发词在已启用技能中选择；多个命中取第一个。"""
        text = message.lower()
        for loaded in [*self._builtin.values(), *self._user.values()]:
            if not loaded.info.enabled:
                continue
            triggers = [item.lower() for item in loaded.info.triggers if item.strip()]
            if any(item in text for item in triggers):
                return loaded
        return None

    def set_enabled(self, skill_id: str, enabled: bool) -> SkillInfo:
        """写入启停覆盖并就地更新；抛错表示技能不存在。"""
        loaded = self.get(skill_id)
        if loaded is None:
            raise SkillRegistryError(f"技能不存在：{skill_id}")
        state = _read_state(self._state_path)
        disabled = set(state.get("disabled", []))
        if enabled:
            disabled.discard(skill_id)
        else:
            disabled.add(skill_id)
        state["disabled"] = sorted(disabled)
        _write_state(self._state_path, state)
        self._builtin = _apply_enabled(self._builtin, disabled)
        self._user = _apply_enabled(self._user, disabled)
        updated = self.get(skill_id)
        assert updated is not None
        return updated.info

    def register_directory(self, directory: Path) -> SkillInfo:
        """登记本地技能目录（不搬文件）；目录必须含 SKILL.md。"""
        directory = directory.expanduser().resolve()
        skill_md = directory / "SKILL.md"
        if not directory.is_dir() or not skill_md.is_file():
            raise SkillRegistryError(f"目录中未找到 SKILL.md：{directory}")
        loaded = load_skill_markdown(skill_md, "user")
        if loaded.info.id in self._builtin:
            raise SkillRegistryError(f"技能 id 与内置技能冲突：{loaded.info.id}")
        state = _read_state(self._state_path)
        external = state.get("external", {})
        if not isinstance(external, dict):
            external = {}
        external[loaded.info.id] = str(directory)
        state["external"] = external
        _write_state(self._state_path,state)
        self._user[loaded.info.id] = loaded
        return loaded.info

    def install_zip(self, data: bytes) -> SkillInfo:
        """解压技能包到 data/skills/<id>/；整体替换同名用户技能。"""
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise SkillRegistryError("不是有效的 zip 包") from exc
        skill_entry = next(
            (item for item in archive.namelist() if item.endswith("SKILL.md")),
            None,
        )
        if skill_entry is None:
            raise SkillRegistryError("zip 内未找到 SKILL.md")
        prefix = skill_entry[: -len("SKILL.md")]
        for name in archive.namelist():
            part = name[len(prefix):] if prefix and name.startswith(prefix) else name
            if part.startswith("/") or ".." in part.split("/"):
                raise SkillRegistryError(f"zip 内含非法路径：{name}")
        header_text = archive.read(skill_entry).decode("utf-8")
        skill_id = _peek_skill_id(header_text)
        if skill_id in self._builtin:
            raise SkillRegistryError(f"技能 id 与内置技能冲突：{skill_id}")

        target = self._user_root / skill_id
        staging = target.with_name(f".{skill_id}.tmp")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for name in archive.namelist():
            part = name[len(prefix):] if prefix and name.startswith(prefix) else name
            if not part or name.endswith("/"):
                continue
            out_path = (staging / part).resolve()
            if not str(out_path).startswith(str(staging.resolve())):
                raise SkillRegistryError(f"zip 内含非法路径：{name}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(archive.read(name))
        if not (staging / "SKILL.md").is_file():
            shutil.rmtree(staging)
            raise SkillRegistryError("技能包结构不完整")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staging), str(target))

        loaded = load_skill_markdown(target / "SKILL.md", "user")
        self._user[loaded.info.id] = loaded
        return loaded.info

    def remove(self, skill_id: str) -> None:
        """删除用户技能；内置技能不可删。"""
        if skill_id in self._builtin:
            raise SkillRegistryError("内置技能不能删除")
        if skill_id not in self._user:
            raise SkillRegistryError(f"技能不存在：{skill_id}")
        state = _read_state(self._state_path)
        external = state.get("external", {})
        if isinstance(external, dict) and skill_id in external:
            del external[skill_id]
            state["external"] = external
            _write_state(self._state_path, state)
        directory = self._user_root / skill_id
        if directory.is_dir():
            shutil.rmtree(directory)
        self._user.pop(skill_id, None)


def _read_state(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_disabled(state: dict) -> set[str]:
    raw = state.get("disabled", [])
    return {str(item) for item in raw} if isinstance(raw, list) else set()


def _read_external(state: dict) -> dict[str, Path]:
    raw = state.get("external", {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Path] = {}
    for skill_id, directory in raw.items():
        if isinstance(skill_id, str) and isinstance(directory, str):
            out[skill_id] = Path(directory).expanduser()
    return out


def _peek_skill_id(text: str) -> str:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillRegistryError("SKILL.md 缺少 frontmatter")
    header = yaml.safe_load(match.group(1)) or {}
    raw_id = header.get("name") if isinstance(header, dict) else None
    skill_id = str(raw_id).strip() if raw_id else ""
    if not skill_id:
        raise SkillRegistryError("SKILL.md 缺少 name")
    return skill_id


def _write_state(path: Path | None, state: dict) -> None:
    if path is None:
        raise SkillRegistryError("技能状态文件未配置")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _apply_enabled(
    skills: dict[str, LoadedSkill],
    disabled: set[str],
) -> dict[str, LoadedSkill]:
    if not disabled:
        return dict(skills)
    from dataclasses import replace

    out: dict[str, LoadedSkill] = {}
    for skill_id, loaded in skills.items():
        if skill_id in disabled and loaded.info.enabled:
            info = replace(loaded.info, enabled=False)
            out[skill_id] = replace(loaded, info=info)
        else:
            out[skill_id] = loaded
    return out
