"""DeskMate 角色生成器 POC：结构化参数 → 可动画 SVG 角色。

用法：
    python scripts/persona_svg_generator.py [params.json] [--out preview.html]

params.json 为 VL 抽取结果（色板/发型/眼型/服装/配件）；缺省则用内置示例。
输出：内联 SVG 角色的预览 HTML（含数据状态切换按钮）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_persona_svg(p: dict) -> str:
    """按参数实例化 SVG 角色（viewBox 240x380，Q 版全身，部件可动画）。"""
    skin = p.get("skin_tone", "#FFF5EE")
    hair = p.get("hair_color", "#2B2B2B")
    hair_style = p.get("hair_style", "短发+刘海")
    eye = p.get("eye_color", "#6B4B3A")
    eye_shape = p.get("eye_shape", "杏眼")
    outfit = p.get("outfit", {}) or {}
    dress = outfit.get("primary_color", "#3B3B46")
    dress2 = outfit.get("secondary_color", "#C0392B")
    accessories = p.get("accessories", []) or []
    scarf = dress2 if "围巾" in accessories else "#666"
    clip = dress2 if "发夹" in accessories else None

    # 发型：短发+刘海 与 双马尾/长发 走不同剪影
    if "长发" in hair_style or "双马尾" in hair_style or "单马尾" in hair_style:
        hair_side = (
            '<path d="M78 92 Q52 78 50 132 Q50 158 84 168 Q86 130 92 104 Z" fill="{h}"/>'
            '<path d="M162 92 Q188 78 190 132 Q190 158 156 168 Q154 130 148 104 Z" fill="{h}"/>'
        ).format(h=hair)
        hair_top = (
            '<path d="M74 86 Q120 40 166 86 Q180 70 172 66 Q192 56 186 78 Q200 84 186 92 Q178 88 166 90 '
            'Q120 62 74 90 Q62 88 54 92 Q40 84 54 78 Q48 70 68 66 Q60 56 74 86 Z" fill="{h}"/>'
        ).format(h=hair)
    else:  # 短发
        hair_side = (
            '<path d="M76 92 Q50 74 52 116 Q52 138 80 150 Q82 122 88 100 Z" fill="{h}"/>'
            '<path d="M164 92 Q190 74 188 116 Q188 138 160 150 Q158 122 152 100 Z" fill="{h}"/>'
        ).format(h=hair)
        hair_top = (
            '<path d="M70 92 Q78 52 120 50 Q162 52 170 92 Q160 84 120 82 Q80 84 70 92 Z" fill="{h}"/>'
        ).format(h=hair)
    fringe = (
        '<path d="M78 94 Q82 76 100 72 Q118 70 128 74 Q146 70 162 94 Q152 108 130 106 '
        'Q110 104 96 106 Q84 106 78 94 Z" fill="{h}"/>'
    ).format(h=hair)

    # 眼型：杏眼=圆润，细长眼=压扁，其余默认
    if "细长" in eye_shape:
        eye_w, eye_h = 7, 4.5
    elif "下垂" in eye_shape:
        eye_w, eye_h = 6.5, 5.5
    else:
        eye_w, eye_h = 6.5, 8
    clip_path = (
        '<clipPath id="clip"><path d="M88 104 Q96 96 106 104 Q100 112 92 110 Z M134 104 '
        'Q142 96 152 104 Q146 112 138 110 Z"/></clipPath>'
    ) if clip else ""

    return f'''<svg class="persona-svg" viewBox="0 0 240 380" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>{persona_css(hair, dress, dress2, scarf)}</style>
    {clip_path}
  </defs>

  <!-- 身体（呼吸） -->
  <g class="persona-body">
    <!-- 颈 + 肩 -->
    <path d="M104 168 Q120 158 136 168 L138 186 L102 186 Z" fill="{skin}" stroke="#00000022" strokeWidth="1"/>
    <path d="M92 172 Q88 184 96 196 Q120 208 144 196 Q152 184 148 172 Q136 182 120 184 Q104 182 92 172 Z"
          fill="{skin}" stroke="#00000022" strokeWidth="1"/>
    <!-- 露肩连衣裙 -->
    <path d="M84 176 Q78 200 82 224 Q88 262 98 296 Q110 330 120 352 Q130 330 142 296 Q152 262 158 224 "
          fill="{dress}" stroke="#00000033"/>
    <path d="M98 296 Q112 330 120 352 Q128 330 142 296 Q132 316 120 320 Q108 316 98 296 Z" fill="{dress2}"/>
    <path d="M82 224 Q100 238 120 240 Q140 238 158 224 Q156 252 146 280 Q132 262 120 264 Q108 262 94 280 Z"
          fill="{dress2}" opacity="0.9"/>
    <!-- 围巾 -->
    <path d="M96 170 Q120 160 144 170 L146 196 Q120 206 94 196 Z" fill="{scarf}" stroke="#00000033"/>
    <path d="M96 170 Q102 188 98 204 Q110 198 120 200 Q130 198 142 204 Q138 188 144 170 Z" fill="{scarf}" opacity="0.85"/>
  </g>

  <!-- 头部 -->
  <g class="persona-head">
    <circle cx="120" cy="104" r="46" fill="{skin}" stroke="#00000022" strokeWidth="1"/>
    <!-- 耳 -->
    <circle cx="76" cy="106" r="7" fill="{skin}"/>
    <circle cx="164" cy="106" r="7" fill="{skin}"/>
    <!-- 发型 -->
    {hair_side}
    {hair_top}
    {fringe}
    {f'<rect x="150" y="74" width="14" height="10" rx="3" fill="{clip}" transform="rotate(18 157 79)"/>' if clip else ""}
    <!-- 眉 -->
    <path d="M96 88 Q104 84 112 87" stroke="{hair}" strokeWidth="2.6" fill="none" strokeLinecap="round"/>
    <path d="M128 87 Q136 84 144 88" stroke="{hair}" strokeWidth="2.6" fill="none" strokeLinecap="round"/>
    <!-- 眼（眨眼动画） -->
    <g class="persona-eyes" clip-path="{ ("url(#clip)") if clip else None }">
      <ellipse class="eye-l" cx="104" cy="100" rx="{eye_w}" ry="{eye_h}" fill="{eye}"/>
      <ellipse class="eye-r" cx="136" cy="100" rx="{eye_w}" ry="{eye_h}" fill="{eye}"/>
      <circle class="glint-l" cx="106" cy="97.5" r="1.8" fill="#fff"/>
      <circle class="glint-r" cx="138" cy="97.5" r="1.8" fill="#fff"/>
    </g>
    <!-- 鼻 -->
    <path d="M120 106 Q118 112 121 114" stroke="#00000033" strokeWidth="1.6" fill="none" strokeLinecap="round"/>
    <!-- 嘴（可切换） -->
    <g class="persona-mouths">
      <path class="mouth-smile" d="M110 124 Q120 132 130 124" stroke="#B5544D" strokeWidth="3" fill="none" strokeLinecap="round"/>
      <path class="mouth-ah" d="M109 122 Q120 138 131 122 Z" fill="#8C4F3D"/>
      <ellipse class="mouth-o" cx="120" cy="126" rx="6.5" ry="8.5" fill="#8C4F3D"/>
    </g>
  </g>
</svg>'''


def persona_css(hair: str, dress: str, dress2: str, scarf: str) -> str:
    return f"""
    /* 呼吸：整身微动 */
    .persona-body {{ animation: pBreath 3.6s ease-in-out infinite; transform-origin: 120px 300px; }}
    @keyframes pBreath {{ 0%,100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-2.5px); }} }}
    /* 眨眼 */
    .persona-eyes {{ transform-origin: 120px 100px; animation: pBlink 4.6s infinite; }}
    @keyframes pBlink {{ 0%,92%,100% {{ transform: scaleY(1); }} 95%,97% {{ transform: scaleY(0.08); }} }}
    /* 嘴型切换 */
    .persona-mouths .mouth-ah, .persona-mouths .mouth-o {{ display: none; }}
    .w-root[data-state="speaking"] .mouth-ah,
    .w-root[data-speaking="1"] .mouth-ah {{ display: block; }}
    .w-root[data-state="speaking"] .mouth-smile {{ display: none; }}
    .w-root[data-state="awaiting_approval"] .mouth-o,
    .w-root[data-state="thinking"] .mouth-o {{ display: block; }}
    .w-root[data-state="awaiting_approval"] .mouth-smile,
    .w-root[data-state="thinking"] .mouth-smile {{ display: none; }}
    /* 情绪动效 */
    .w-root[data-emotion="thinking"] .persona-body {{ animation-duration: 1.6s; }}
    .w-root[data-emotion="confused"] .persona-head {{ animation: pShake .5s ease-in-out infinite; transform-origin: 120px 104px; }}
    @keyframes pShake {{ 0%,100% {{ transform: translateX(0); }} 25% {{ transform: translateX(-3px); }} 75% {{ transform: translateX(3px); }} }}
    .w-root[data-emotion="error"] .persona-head {{ animation: pShiver .35s ease-in-out infinite; transform-origin: 120px 104px; }}
    @keyframes pShiver {{ 0%,100% {{ transform: translateX(0); }} 20% {{ transform: translateX(-4px) rotate(-.6deg); }} 40% {{ transform: translateX(4px) rotate(.6deg); }} 60% {{ transform: translateX(-3px); }} 80% {{ transform: translateX(3px); }} }}
    """


def build_preview_html(svg: str, params: dict) -> str:
    states = [
        ("idle", "neutral", "idle 空闲"),
        ("listening", "attentive", "listening 聆听中"),
        ("thinking", "thinking", "thinking 思考中"),
        ("speaking", "neutral", "speaking 说话中"),
        ("awaiting_approval", "confused", "awaiting_approval 需要授权"),
        ("completed", "success", "completed 完成"),
        ("error", "error", "error 失败"),
    ]
    buttons = "".join(
        f'<button class="state-btn" data-state="{s}" data-emotion="{e}">{l}</button>'
        for s, e, l in states
    )
    meta = json.dumps(params, ensure_ascii=False, indent=2)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>DeskMate 参考图生成角色 POC</title>
<style>
  body {{ margin:0; background:#1e2230; color:#cdd3e0; font-family:-apple-system,"PingFang SC",sans-serif; }}
  .page {{ padding:24px; }}
  h1 {{ font-size:15px; margin:0 0 4px; }}
  .hint {{ font-size:12px; color:#8b93a7; margin-bottom:16px; }}
  .row {{ display:flex; gap:24px; flex-wrap:wrap; align-items:flex-start; }}
  .stage {{ width:240px; height:380px; border-radius:16px;
    background:radial-gradient(circle at 50% 20%, rgba(255,255,255,.06), transparent 70%);
    display:flex; align-items:center; justify-content:center; }}
  .persona-svg {{ width:220px; height:348px; }}
  .col {{ display:flex; flex-direction:column; gap:8px; }}
  .state-btn {{ width:230px; text-align:left; padding:7px 12px; border:1px solid #3a4154; border-radius:8px;
    background:#262c3d; color:#cdd3e0; cursor:pointer; font-size:12px; }}
  .state-btn.active {{ border-color:#6366F1; background:#313a5c; color:#fff; }}
  pre {{ background:#14171f; padding:12px; border-radius:10px; font-size:11px; color:#9fb0c7;
    white-space:pre-wrap; max-width:420px; }}
</style>
</head>
<body>
<div class="page">
  <h1>参考图 → VL 抽取 → 参数化 SVG 角色（POC）</h1>
  <div class="hint">点按钮切换状态/情绪，观察眨眼、呼吸、嘴型与情绪动效。</div>
  <div class="row">
    <div class="stage w-root" id="stage" data-state="idle" data-emotion="neutral">{svg}</div>
    <div class="col" id="btns">{buttons}<pre>{meta}</pre></div>
  </div>
</div>
<script>
  const stage = document.getElementById("stage");
  document.querySelectorAll(".state-btn").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(".state-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      stage.dataset.state = btn.dataset.state;
      stage.dataset.emotion = btn.dataset.emotion;
    }});
  }});
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("params", nargs="?", type=Path, default=None, help="VL 抽取的 JSON 参数文件")
    parser.add_argument("--out", type=Path, default=None, help="输出 HTML 路径")
    args = parser.parse_args()

    if args.params and args.params.is_file():
        params = json.loads(args.params.read_text(encoding="utf-8"))
    else:
        params = {
            "hair_color": "#1A0D0E",
            "hair_style": "短发+刘海",
            "eye_color": "#8B4513",
            "eye_shape": "杏眼",
            "skin_tone": "#FFF5EE",
            "outfit": {
                "type": "露肩连衣裙",
                "primary_color": "#000000",
                "secondary_color": "#8B0000",
            },
            "accessories": ["围巾", "发夹"],
            "face_shape": "瓜子脸",
            "vibe": "优雅知性，略带神秘感",
            "coverage": "full_body",
        }
    svg = build_persona_svg(params)
    out = args.out or Path("/tmp/deskmate_svg_poc.html")
    out.write_text(build_preview_html(svg, params), encoding="utf-8")
    print(f"已生成 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
