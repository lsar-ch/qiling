"""角色基础形象规范化：去背景、清理边缘、裁切、对齐并输出固定画布。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from statistics import median

from PIL import Image, ImageOps

MIN_SOURCE_DIM = 512
MAX_SOURCE_DIM = 4096
OUTPUT_SIZE = 1024
SAFE_MARGIN = 48
CONTENT_ALPHA_THRESHOLD = 12
BACKGROUND_MAX_DIST = 44
ALPHA_SOFT_EDGE = 20
ALPHA_HARD_EDGE = 48


@dataclass(frozen=True)
class NormalizedAvatar:
    image: Image.Image
    original_size: tuple[int, int]
    content_size: tuple[int, int]
    content_bbox: tuple[int, int, int, int]
    background_removed: bool
    processing: str


def _distance(rgb: tuple[int, int, int], reference: tuple[int, int, int]) -> float:
    return sum((channel - base) ** 2 for channel, base in zip(rgb, reference)) ** 0.5


def _background_reference(pixels: bytearray, width: int, height: int) -> tuple[int, int, int] | None:
    step = max(1, min(width, height) // 128)
    samples: list[tuple[int, int, int]] = []

    def add(x: int, y: int) -> None:
        offset = (y * width + x) * 3
        samples.append((pixels[offset], pixels[offset + 1], pixels[offset + 2]))

    for x in range(0, width, step):
        add(x, 0)
        add(x, height - 1)
    for y in range(0, height, step):
        add(0, y)
        add(width - 1, y)
    if not samples:
        return None

    reference = tuple(int(median(sample[channel] for sample in samples)) for channel in range(3))
    close = sum(_distance(sample, reference) <= BACKGROUND_MAX_DIST for sample in samples)
    if close / len(samples) < 0.7:
        return None
    return reference  # type: ignore[return-value]


def _remove_uniform_background(image: Image.Image) -> Image.Image | None:
    """移除与画布边缘连通的单色背景；无法可靠判断时返回 None。"""
    width, height = image.size
    pixels = bytearray(image.convert("RGB").tobytes())
    reference = _background_reference(pixels, width, height)
    if reference is None:
        return None

    near_background = bytearray(width * height)
    for index in range(width * height):
        offset = index * 3
        rgb = (pixels[offset], pixels[offset + 1], pixels[offset + 2])
        if _distance(rgb, reference) <= BACKGROUND_MAX_DIST:
            near_background[index] = 1

    background = bytearray(width * height)
    stack: list[int] = []

    def seed(x: int, y: int) -> None:
        index = y * width + x
        if near_background[index] and not background[index]:
            background[index] = 1
            stack.append(index)

    for x in range(width):
        seed(x, 0)
        seed(x, height - 1)
    for y in range(height):
        seed(0, y)
        seed(width - 1, y)
    while stack:
        index = stack.pop()
        x, y = index % width, index // width
        if x > 0:
            seed(x - 1, y)
        if x + 1 < width:
            seed(x + 1, y)
        if y > 0:
            seed(x, y - 1)
        if y + 1 < height:
            seed(x, y + 1)

    removed = sum(background)
    if removed < max(1, width * height // 100):
        return None
    if removed > width * height * 99 // 100:
        return None

    rgba = bytearray(width * height * 4)
    for index in range(width * height):
        source = index * 3
        target = index * 4
        rgb = (pixels[source], pixels[source + 1], pixels[source + 2])
        distance = _distance(rgb, reference)
        if background[index] or distance <= ALPHA_SOFT_EDGE:
            alpha = 0
        elif distance >= ALPHA_HARD_EDGE:
            alpha = 255
        else:
            alpha = int(
                255
                * (distance - ALPHA_SOFT_EDGE)
                / (ALPHA_HARD_EDGE - ALPHA_SOFT_EDGE)
            )
        rgba[target : target + 4] = bytes((*rgb, alpha))
    return Image.frombytes("RGBA", (width, height), bytes(rgba))


def _alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A").point(
        lambda value: 255 if value >= CONTENT_ALPHA_THRESHOLD else 0
    )
    return alpha.getbbox()


def normalize_avatar_image(
    image: Image.Image,
    *,
    output_size: int = OUTPUT_SIZE,
    safe_margin: int = SAFE_MARGIN,
) -> NormalizedAvatar:
    """把角色图规范为标准透明画布，主体底部居中并保留安全边距。"""
    source = ImageOps.exif_transpose(image)
    original_size = source.size
    if min(original_size) < MIN_SOURCE_DIM:
        raise ValueError(f"图片尺寸不能小于 {MIN_SOURCE_DIM}×{MIN_SOURCE_DIM}")
    if max(original_size) > MAX_SOURCE_DIM:
        raise ValueError(f"图片长边不能超过 {MAX_SOURCE_DIM}px")
    if output_size <= safe_margin * 2:
        raise ValueError("输出画布尺寸小于安全边距")

    working = source.convert("RGBA")
    # 输出画布上限决定最终可见细节；先缩到该尺寸，避免在 2048/4096 图上做 Python 像素遍历。
    working.thumbnail((output_size, output_size), Image.Resampling.LANCZOS)
    alpha_extrema = working.getchannel("A").getextrema()
    if alpha_extrema[0] < 255:
        processed = working
        background_removed = False
        processing = "trim-align-canvas"
    else:
        processed = _remove_uniform_background(working)
        if processed is None:
            raise ValueError("无法识别均匀背景，请使用透明 PNG 或背景单一、主体清晰的图片")
        background_removed = True
        processing = "background-remove-trim-align-canvas"

    bbox = _alpha_bbox(processed)
    if bbox is None:
        raise ValueError("图片中没有可识别的主体")
    content = processed.crop(bbox)
    max_width = output_size - safe_margin * 2
    max_height = output_size - safe_margin * 2
    scale = min(max_width / content.width, max_height / content.height)
    content_width = max(1, round(content.width * scale))
    content_height = max(1, round(content.height * scale))
    content = content.resize((content_width, content_height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (output_size, output_size), (0, 0, 0, 0))
    left = (output_size - content_width) // 2
    top = output_size - safe_margin - content_height
    canvas.alpha_composite(content, (left, top))
    return NormalizedAvatar(
        image=canvas,
        original_size=original_size,
        content_size=(content_width, content_height),
        content_bbox=(left, top, left + content_width - 1, top + content_height - 1),
        background_removed=background_removed,
        processing=processing,
    )


def normalize_avatar_file(path: Path) -> NormalizedAvatar:
    with Image.open(path) as image:
        image.load()
        return normalize_avatar_image(image)


def png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
