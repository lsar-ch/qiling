/**
 * 开箱备选模型（codex++ 式：base_url / model / provider 已预填，用户只填 API Key）。
 * 模型名可能随供应商更新，档案里仍可手动修改。
 */
import type { ModelProfileCategory } from "./api";

export interface ModelPreset {
  id: string;
  category: ModelProfileCategory;
  label: string;
  vendor: string;
  provider: string;
  baseUrl: string;
  model: string;
  keyPlaceholder: string;
  note: string;
}

export const MODEL_PRESETS: ModelPreset[] = [
  // ── 通用文字模型 ──
  {
    id: "deepseek-chat",
    category: "text",
    label: "DeepSeek",
    vendor: "DeepSeek",
    provider: "openai_compatible",
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-chat",
    keyPlaceholder: "sk-...",
    note: "DeepSeek 官方 OpenAI 兼容接口；base_url 不要加 /v1",
  },
  {
    id: "qwen-plus",
    category: "text",
    label: "通义千问 Qwen Plus",
    vendor: "阿里云百炼",
    provider: "openai_compatible",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-plus",
    keyPlaceholder: "sk-...",
    note: "阿里百炼 OpenAI 兼容接口；也可换 qwen-flash / qwen3-coder-plus",
  },
  {
    id: "doubao-seed",
    category: "text",
    label: "豆包 Seed 2.1 Pro",
    vendor: "火山方舟",
    provider: "openai_compatible",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    model: "doubao-seed-2-1-pro-260915",
    keyPlaceholder: "方舟 API Key",
    note: "需先在方舟控制台开通该模型；模型名可按控制台改",
  },
  {
    id: "ark-code-plan",
    category: "text",
    label: "火山方舟 Coding Plan",
    vendor: "火山方舟套餐",
    provider: "openai_compatible",
    baseUrl: "https://ark.cn-beijing.volces.com/api/plan/v3",
    model: "ark-code-latest",
    keyPlaceholder: "方舟套餐 API Key",
    note: "Coding Plan / Token 套餐入口，自动调度最新代码模型",
  },
  {
    id: "glm-plus",
    category: "text",
    label: "智谱 GLM-4 Plus",
    vendor: "智谱 AI",
    provider: "openai_compatible",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-4-plus",
    keyPlaceholder: "xxxxx.xxxxx",
    note: "智谱开放平台 API Key",
  },
  {
    id: "kimi-moonshot",
    category: "text",
    label: "Kimi（Moonshot）",
    vendor: "月之暗面",
    provider: "openai_compatible",
    baseUrl: "https://api.moonshot.cn/v1",
    model: "moonshot-v1-8k",
    keyPlaceholder: "sk-...",
    note: "长文本对话；也可换 moonshot-v1-32k / 128k",
  },
  {
    id: "siliconflow-deepseek",
    category: "text",
    label: "硅基流动 DeepSeek V3",
    vendor: "SiliconFlow",
    provider: "openai_compatible",
    baseUrl: "https://api.siliconflow.cn/v1",
    model: "deepseek-ai/DeepSeek-V3",
    keyPlaceholder: "sk-...",
    note: "聚合平台，一个 Key 可切换多家开源模型",
  },
  {
    id: "openai-mini",
    category: "text",
    label: "OpenAI GPT-4o mini",
    vendor: "OpenAI",
    provider: "openai_compatible",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    keyPlaceholder: "sk-...",
    note: "需要海外网络环境",
  },
  // ── 多模态模型 ──
  {
    id: "qwen-vl-max",
    category: "multimodal",
    label: "通义千问 VL Max",
    vendor: "阿里云百炼",
    provider: "openai_compatible",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-vl-max",
    keyPlaceholder: "sk-...",
    note: "图片 / 截图理解，百炼 OpenAI 兼容接口",
  },
  {
    id: "glm-4v-plus",
    category: "multimodal",
    label: "智谱 GLM-4V Plus",
    vendor: "智谱 AI",
    provider: "openai_compatible",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-4v-plus",
    keyPlaceholder: "xxxxx.xxxxx",
    note: "图片理解，智谱开放平台 API Key",
  },
  // ── STT 语音识别 ──
  {
    id: "dashscope-stt",
    category: "stt",
    label: "阿里云百炼 Paraformer",
    vendor: "阿里云百炼",
    provider: "dashscope",
    baseUrl: "",
    model: "paraformer-realtime-v2",
    keyPlaceholder: "sk-...",
    note: "实时语音识别，DashScope API Key",
  },
  {
    id: "groq-whisper",
    category: "stt",
    label: "Groq Whisper",
    vendor: "Groq",
    provider: "openai_compatible",
    baseUrl: "https://api.groq.com/openai/v1",
    model: "whisper-large-v3-turbo",
    keyPlaceholder: "gsk_...",
    note: "Groq 极速 Whisper，OpenAI 兼容接口",
  },
  // ── TTS 语音合成 ──
  {
    id: "minimax-tts",
    category: "tts",
    label: "MiniMax 语音合成",
    vendor: "MiniMax",
    provider: "minimax",
    baseUrl: "",
    model: "speech-2.8-hd",
    keyPlaceholder: "sk-api-...",
    note: "MiniMax 高清语音合成",
  },
  {
    id: "dashscope-cosyvoice",
    category: "tts",
    label: "阿里云百炼 CosyVoice",
    vendor: "阿里云百炼",
    provider: "dashscope",
    baseUrl: "",
    model: "cosyvoice-v3.5-plus",
    keyPlaceholder: "sk-...",
    note: "CosyVoice 声音复刻与合成",
  },
  {
    id: "openai-tts",
    category: "tts",
    label: "OpenAI TTS",
    vendor: "OpenAI",
    provider: "openai_compatible",
    baseUrl: "https://api.openai.com/v1",
    model: "tts-1",
    keyPlaceholder: "sk-...",
    note: "OpenAI 官方语音合成，需要海外网络",
  },
];
