# DeskMate 角色资产生成提示词模板

> 日期：2026-09-10 ｜ 状态：待用户跑通第一个角色后定稿
> 目标：生成一套分层 2D 角色部件，直接可被 `layers.json` 解析器消费

## 画布与通用约束

- **画布尺寸**：512×512 像素
- **背景**：纯透明（PNG 透明通道）
- **角色主体**：居中站立，约占画布高度 60-70%（角色高度约 280-340px，头部在画布上方 1/3 处）
- **风格**：平涂/赛璐璐风格，线条清晰，色彩块面分明
- **边缘**：干净硬边，无羽化、无半透明像素
- **光照**：正面柔光，无明显阴影方向
- **不要文字、不要水印、不要背景元素**

## 6 张必选图层

每张图层是**同一角色的同一姿态**，仅部件不同。所有图层叠在一起（身体在底，眼嘴在上）能完美对齐成完整角色。

---

### 第 1 张：`body.png` — 身体主体

```
A full-body standing 2D character in anime/game cel-shaded style.
Canvas 512x512, transparent background, NO background elements.

Character: [在这里描述你的角色]
- Standing upright, facing slightly toward viewer
- Arms relaxed at sides
- NO eyes, NO mouth on face — face area is blank/smooth skin
- Clean outlines, flat colors
- Full body from head to feet visible within frame
```

---

### 第 2 张：`eyes_open.png` — 睁眼

```
Same character as body.png, same pose, same position.
Canvas 512x512, transparent background.

Show ONLY the eyes:
- Both eyes open, looking forward
- Neutral/default expression
- Eye shape, iris, pupil, highlights visible
- Everything else transparent
- Must align exactly with body.png face when overlaid
```

---

### 第 3 张：`eyes_closed.png` — 闭眼

```
Same character as body.png, same pose, same position.
Canvas 512x512, transparent background.

Show ONLY the eyes:
- Both eyes closed (simple curved lines or thin arcs)
- Relaxed/gentle closed-eye expression
- Everything else transparent
- Must align exactly with body.png face when overlaid
```

---

### 第 4 张：`mouth_closed.png` — 闭嘴

```
Same character as body.png, same pose, same position.
Canvas 512x512, transparent background.

Show ONLY the mouth:
- Mouth closed, a simple thin line
- Neutral expression
- Everything else transparent
- Must align exactly with body.png face when overlaid
```

---

### 第 5 张：`mouth_open.png` — 张嘴

```
Same character as body.png, same pose, same position.
Canvas 512x512, transparent background.

Show ONLY the mouth:
- Mouth slightly open (speaking shape), small oval/diamond opening
- Inside of mouth darker than lips
- Everything else transparent
- Must align exactly with body.png face when overlaid
```

---

### 第 6 张：`mouth_smile.png` — 微笑

```
Same character as body.png, same pose, same position.
Canvas 512x512, transparent background.

Show ONLY the mouth:
- Gentle smile, slightly curved upward
- Friendly/slight smile, not a wide grin
- Everything else transparent
- Must align exactly with body.png face when overlaid
```

---

## 可选追加图层（V1 不强求）

| 图层 | 说明 |
|---|---|
| `brows_raised.png` | 抬眉 |
| `brows_furrowed.png` | 皱眉 |
| `blush.png` | 腮红（半透明叠加） |
| `accessory.png` | 帽子/眼镜/发饰等配饰 |
| `effect_sparkle.png` | 完成闪光粒子 |

## 推荐工具

| 工具 | 免费额度 | 网址 | 推荐理由 |
|---|---|---|---|
| **通义万相** | 每日免费额度 | [tongyi.aliyun.com/wanxiang](https://tongyi.aliyun.com/wanxiang) | 阿里系，中文提示词友好，人物稳定 |
| **即梦** | 每日免费额度 | [jimeng.jianying.com](https://jimeng.jianying.com) | 字节系，画风多样 |
| **可灵** | 每日免费额度 | [klingai.com](https://klingai.com) | 快手系，角色一致性较好 |
| **Leonardo.ai** | 每日 150 token | [leonardo.ai](https://leonardo.ai) | 国外工具，风格控制精细 |
| **ChatGPT (DALL·E)** | Plus 用户无限 | [chatgpt.com](https://chatgpt.com) | 直接对话生成，最省事 |

> **建议**：先用 ChatGPT/DALL·E 把 6 张图层一次性对话跑完（上传 body 图作为参考，让它生成变体）。如果画风不满意，换通义万相或即梦重跑。

## 使用方式

1. 把上面 6 段英文提示词里的 `[在这里描述你的角色]` 替换为你的角色描述，例如：
   > A young professional woman, short dark hair, wearing a neat white blouse and dark pants, warm and approachable look.
2. 逐张生成（必须同一角色、同一姿态，只是部件不同）
3. 确保每张图去背后保存为透明 PNG，按文件名放入 `assets/personas/<角色id>/`
4. 告诉我角色 ID，我来写 `layers.json` 生成器和挂件接入
