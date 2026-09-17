"""角色卡契约（Step 10 形象定制预留）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CharacterStyle = Literal["2d_static", "2d_animated", "lip_sync", "live2d", "3d"]
AvatarDriver = Literal["procedural_2d", "video_stream"]


class CharacterConfig(BaseModel):
    """角色卡的基础配置，V1 只支持 2d_static 和 2d_animated。"""

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=40)
    style: CharacterStyle = "2d_static"
    avatar_driver: AvatarDriver = "procedural_2d"
    avatar_asset: str = ""          # 静态图片路径或占位符
    animation_set: str = ""         # 动画集名称（用于 2d_animated）
    lip_sync_model: str | None = None  # 口型同步模型（未来）
    training_status: str = "none"   # none | pending | training | ready | failed
    training_progress: float = 0.0  # 0.0 ~ 1.0
    reference_images: list[str] = Field(default_factory=list)
    voice_match: str | None = None  # 匹配的音色 ID

    model_config = {"extra": "forbid"}
