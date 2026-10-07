import { useEffect, useRef, useState } from "react";
import { confirmText } from "./dialog";
import {
  createModelProfile,
  deleteModelProfile,
  fetchModelProfiles,
  fetchProviderModels,
  fetchVoiceOptions,
  previewVoice,
  testModelProfile,
  updateModelProfile,
  type ModelProfile,
  type ModelProfileCategory,
  type ModelProfilePayload,
  type VoiceOption,
} from "./api";
import ModelSelect from "./ModelSelect";
import VoiceSelect from "./VoiceSelect";

const CATEGORY_META: Record<
  ModelProfileCategory,
  { title: string; hint: string; providers: { value: string; label: string }[] }
> = {
  text: {
    title: "通用文字模型",
    hint: "用于日常对话、文本总结和任务理解。聊天页只会选择这一类与多模态模型。",
    providers: [
      { value: "openai_compatible", label: "OpenAI 兼容接口" },
      { value: "echo", label: "本地演示模式" },
    ],
  },
  multimodal: {
    title: "多模态模型",
    hint: "用于图片、截图和视觉内容理解。当前版本先保存档案，视觉执行入口接入前也可用于文字对话。",
    providers: [{ value: "openai_compatible", label: "OpenAI 兼容接口" }],
  },
  stt: {
    title: "语音识别模型",
    hint: "用于麦克风录音转文字。当前支持阿里云百炼 DashScope / Paraformer 系列。",
    providers: [{ value: "dashscope", label: "阿里云百炼 DashScope" }],
  },
  tts: {
    title: "语音合成模型",
    hint: "用于把助手回复转换成语音。支持 MiniMax、DashScope CosyVoice，以及任何 OpenAI 兼容 / 自建的语音服务。配置保存后即可拉取该供应商的音色列表。",
    providers: [
      { value: "minimax", label: "MiniMax" },
      { value: "dashscope", label: "阿里云百炼 DashScope" },
      { value: "openai_compatible", label: "OpenAI 兼容 / 自建服务" },
    ],
  },
};

type Draft = {
  id: string;
  name: string;
  category: ModelProfileCategory;
  provider: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  voice: string;
  enabled: boolean;
  isDefault: boolean;
};

const inputCls =
  "w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20";

function newDraft(category: ModelProfileCategory): Draft {
  const suffix = globalThis.crypto?.randomUUID?.().replace(/-/g, "").slice(0, 10) ?? String(Date.now());
  return {
    id: `${category}_${suffix}`,
    name: "",
    category,
    provider: CATEGORY_META[category].providers[0].value,
    baseUrl: "",
    model: "",
    apiKey: "",
    voice: "",
    enabled: true,
    isDefault: false,
  };
}

function profileDraft(profile: ModelProfile): Draft {
  return {
    id: profile.id,
    name: profile.name,
    category: profile.category,
    provider: profile.provider,
    baseUrl: profile.base_url,
    model: profile.model,
    apiKey: "",
    voice: profile.voice,
    enabled: profile.enabled,
    isDefault: profile.is_default,
  };
}

function payloadFromDraft(draft: Draft): ModelProfilePayload {
  const payload: ModelProfilePayload = {
    id: draft.id,
    name: draft.name.trim(),
    category: draft.category,
    provider: draft.provider,
    base_url: draft.baseUrl.trim(),
    model: draft.model.trim(),
    voice: draft.voice.trim(),
    enabled: draft.enabled,
    is_default: draft.isDefault,
  };
  if (draft.apiKey.trim()) payload.api_key = draft.apiKey.trim();
  return payload;
}

export default function ModelProfilesSection({ onChanged }: { onChanged?: () => void | Promise<void> }) {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [editorRequest, setEditorRequest] = useState(0);
  const [voiceOptions, setVoiceOptions] = useState<VoiceOption[]>([]);
  const [voiceProvider, setVoiceProvider] = useState("");
  const [voiceReason, setVoiceReason] = useState<string | null>(null);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelReason, setModelReason] = useState<string | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [modelOpenRequest, setModelOpenRequest] = useState(0);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const editorRef = useRef<HTMLDivElement | null>(null);

  const load = async (): Promise<void> => {
    setError("");
    try {
      setProfiles(await fetchModelProfiles());
    } catch (e) {
      setError(e instanceof Error ? e.message : "模型档案加载失败");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!editorRequest) return;
    requestAnimationFrame(() => editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [editorRequest]);

  const savedProfileIds = new Set(profiles.map((profile) => profile.id));

  const loadVoiceOptions = async (profileId?: string): Promise<void> => {
    setVoiceBusy(true);
    try {
      const list = await fetchVoiceOptions(profileId);
      setVoiceOptions(list.voices);
      setVoiceProvider(list.provider);
      setVoiceReason(list.reason);
    } catch {
      setVoiceOptions([]);
      setVoiceReason("音色列表获取失败，可直接填写音色 ID");
    } finally {
      setVoiceBusy(false);
    }
  };

  const loadModelOptions = async (target: Draft | null = draft): Promise<void> => {
    if (!target) return;
    if (target.provider === "echo") {
      setModelOptions([]);
      setModelReason("本地演示模式没有模型列表，直接填任意名称即可。");
      return;
    }
    setModelBusy(true);
    try {
      const list = await fetchProviderModels({
        baseUrl: target.baseUrl,
        apiKey: target.apiKey,
        profileId: savedProfileIds.has(target.id) ? target.id : undefined,
      });
      setModelOptions(list.models);
      setModelReason(list.reason);
    } catch (e) {
      setModelOptions([]);
      setModelReason(e instanceof Error ? e.message : "模型列表获取失败，可直接手填");
    } finally {
      setModelBusy(false);
    }
  };

  const preview = async (): Promise<void> => {
    if (!draft) return;
    setPreviewing(true);
    setError("");
    try {
      const blob = await previewVoice({
        profile_id: savedProfileIds.has(draft.id) ? draft.id : undefined,
        provider: draft.provider,
        base_url: draft.baseUrl.trim(),
        model: draft.model.trim(),
        voice: draft.voice.trim(),
        api_key: draft.apiKey.trim() || undefined,
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      audio.onerror = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch (e) {
      setError(e instanceof Error ? e.message : "试听失败");
    } finally {
      setPreviewing(false);
    }
  };

  const openEditor = (nextDraft: Draft): void => {
    setDraft(nextDraft);
    setModelOptions([]);
    setModelReason(null);
    setEditorRequest((current) => current + 1);
    if (nextDraft.category === "tts") {
      void loadVoiceOptions(savedProfileIds.has(nextDraft.id) ? nextDraft.id : undefined);
    }
  };

  const save = async (): Promise<void> => {
    if (!draft) return;
    if (!draft.name.trim()) {
      setError("请填写档案名称");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const existing = profiles.some((profile) => profile.id === draft.id);
      if (existing) await updateModelProfile(draft.id, payloadFromDraft(draft));
      else await createModelProfile(payloadFromDraft(draft));
      await load();
      await onChanged?.();
      setDraft(null);
      setNotice(existing ? "模型档案已更新。" : "模型档案已创建。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "模型档案保存失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (profile: ModelProfile): Promise<void> => {
    if (!(await confirmText(`删除模型档案「${profile.name}」？`, "删除模型档案"))) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await deleteModelProfile(profile.id);
      await load();
      await onChanged?.();
      setNotice("模型档案已删除。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "模型档案删除失败");
    } finally {
      setBusy(false);
    }
  };

  const test = async (profile: ModelProfile): Promise<void> => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await testModelProfile(profile.id);
      setTestResult((current) => ({ ...current, [profile.id]: result.message }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接测试失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-line bg-surface shadow-card p-4 flex flex-col gap-4 min-w-0">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">多模型档案</h3>
          <p className="mt-1 text-xs text-muted leading-relaxed">
            按用途分别保存模型。API Key 只保存在本机，不写入角色卡，也不会从 API 返回明文。
          </p>
        </div>
        {notice ? <span className="text-xs text-ok shrink-0">{notice}</span> : null}
      </div>

      {error ? <div className="rounded-lg bg-bad-50 text-bad px-3 py-2.5 text-xs">{error}</div> : null}

      {draft ? (
        <div ref={editorRef} className="rounded-lg border border-brand/30 bg-brand-50/40 p-3.5 flex flex-col gap-3 scroll-mt-4">
          <div className="flex items-center justify-between gap-3">
            <b className="text-sm text-ink">
              {profiles.some((profile) => profile.id === draft.id) ? "编辑" : "新增"} · {CATEGORY_META[draft.category].title}
            </b>
            <button className="text-xs text-muted hover:text-ink" onClick={() => setDraft(null)} disabled={busy}>
              取消
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5 text-xs text-muted">
              档案名称
              <input className={inputCls} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="例如：千问 Plus" />
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted">
              接口类型
              <select className={inputCls} value={draft.provider} onChange={(event) => setDraft({ ...draft, provider: event.target.value })}>
                {CATEGORY_META[draft.category].providers.map((provider) => (
                  <option key={provider.value} value={provider.value}>{provider.label}</option>
                ))}
              </select>
            </label>
            {draft.category === "text" || draft.category === "multimodal" || draft.provider === "openai_compatible" ? (
              <label className="flex flex-col gap-1.5 text-xs text-muted sm:col-span-2">
                API 地址
                <input className={inputCls} value={draft.baseUrl} onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })} placeholder="https://.../v1" />
              </label>
            ) : null}
            <label className="flex flex-col gap-1.5 text-xs text-muted">
              <span className="flex items-center justify-between gap-2">
                <span>模型名称</span>
                {draft.category === "text" || draft.category === "multimodal" ? (
                  <button
                    type="button"
                    className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11px] text-ink hover:border-brand hover:text-brand disabled:opacity-50"
                    onClick={() => {
                      void loadModelOptions();
                      setModelOpenRequest((current) => current + 1);
                    }}
                    disabled={modelBusy}
                    title="从供应商拉取可用模型"
                  >
                    {modelBusy ? "获取中…" : "获取"}
                  </button>
                ) : null}
              </span>
              {draft.category === "text" || draft.category === "multimodal" ? (
                <>
                  <small className="text-[11px] text-muted break-words">
                    {draft.category === "text"
                      ? "推荐使用纯文本对话类模型（如 qwen-flash、qwen-plus），不建议选图像、视频或向量嵌入类模型。"
                      : "推荐使用支持图像理解的多模态模型（如 qwen-vl 系列）；需要处理视频时，请确认模型本身支持视频输入。"}
                  </small>
                  <ModelSelect
                    value={draft.model}
                    onChange={(next) => setDraft({ ...draft, model: next })}
                    models={modelOptions}
                    loading={modelBusy}
                    reason={modelReason}
                    openRequest={modelOpenRequest}
                    placeholder="qwen-flash"
                  />
                  <small className="text-[11px] text-muted break-words">
                    {modelOptions.length > 0
                      ? `共 ${modelOptions.length} 个可用模型，点选即填入；也可直接手填。`
                      : "点击「获取」可从供应商拉取可用模型列表，也可直接手填。"}
                  </small>
                </>
              ) : (
                <input
                  className={inputCls}
                  value={draft.model}
                  onChange={(event) => setDraft({ ...draft, model: event.target.value })}
                  placeholder={draft.category === "stt" ? "paraformer-realtime-v2" : "speech-2.8-hd"}
                />
              )}
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted">
              API Key
              <input
                className={inputCls}
                type="password"
                value={draft.apiKey}
                onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })}
                placeholder={profiles.find((profile) => profile.id === draft.id)?.api_key_configured ? "已配置；留空保持不变" : "输入 API Key"}
              />
            </label>
            {draft.category === "tts" ? (
              <div className="flex flex-col gap-1.5 text-xs text-muted sm:col-span-2">
                <div className="flex items-center justify-between gap-2">
                  <span>音色</span>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className="text-[11px] text-brand hover:underline disabled:opacity-50"
                      onClick={() => void preview()}
                      disabled={previewing || busy}
                      title="用当前音色合成一句样音（会消耗供应商额度）"
                    >
                      {previewing ? "合成中…" : "试听"}
                    </button>
                    <button
                      type="button"
                      className="text-[11px] text-brand hover:underline disabled:opacity-50"
                      onClick={() => void loadVoiceOptions(draft && savedProfileIds.has(draft.id) ? draft.id : undefined)}
                      disabled={voiceBusy}
                    >
                      {voiceBusy ? "获取中…" : "重新获取音色列表"}
                    </button>
                  </div>
                </div>
                {voiceOptions.length > 0 ? (
                  <>
                    <VoiceSelect
                      options={voiceOptions}
                      value={draft.voice}
                      onChange={(next) => setDraft({ ...draft, voice: next })}
                      emptyLabel="未指定（使用供应商默认音色）"
                      className={inputCls}
                      previousOptionLabels={draft.voice ? { [draft.voice]: "当前值，不在列表" } : undefined}
                    />
                    <small className="text-[11px] text-muted break-words">
                      共 {voiceOptions.length} 个音色，来自 {voiceProvider}
                      {draft && savedProfileIds.has(draft.id) ? " 该档案" : " 当前生效配置"}。
                      新档案请先保存，再回来拉取该供应商的音色列表。
                    </small>
                  </>
                ) : (
                  <>
                    <input className={inputCls} value={draft.voice} onChange={(event) => setDraft({ ...draft, voice: event.target.value })} placeholder="Chinese (Mandarin)_Soft_Girl" />
                    <small className="text-[11px] text-muted break-words">
                      {voiceReason ?? "音色列表来自当前生效的语音合成配置；也可直接填写音色 ID。"}
                    </small>
                  </>
                )}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" className="w-4 h-4 accent-brand" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />
              启用档案
            </label>
            <label className="inline-flex items-center gap-2">
              <input type="checkbox" className="w-4 h-4 accent-brand" checked={draft.isDefault} onChange={(event) => setDraft({ ...draft, isDefault: event.target.checked })} />
              设为该分类默认
            </label>
          </div>
          <div className="flex justify-end">
            <button className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-onbrand hover:bg-brand-600 disabled:opacity-50" onClick={() => void save()} disabled={busy}>
              {busy ? "保存中…" : "保存档案"}
            </button>
          </div>
        </div>
      ) : null}

      {(Object.keys(CATEGORY_META) as ModelProfileCategory[]).map((category) => {
        const meta = CATEGORY_META[category];
        const items = profiles.filter((profile) => profile.category === category);
        return (
          <div key={category} className="flex flex-col gap-2.5">
            <div className="flex items-start justify-between gap-3 border-b border-line pb-2">
              <div>
                <h4 className="text-sm font-semibold text-ink">{meta.title}</h4>
                <p className="mt-0.5 text-[11px] text-muted leading-relaxed">{meta.hint}</p>
              </div>
              <button className="shrink-0 rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink hover:border-brand hover:text-brand" onClick={() => openEditor(newDraft(category))}>
                新增档案
              </button>
            </div>
            {items.length === 0 ? (
              <p className="rounded-lg bg-surface-tertiary px-3 py-2.5 text-xs text-muted">尚未配置{meta.title}。</p>
            ) : (
              <div className="flex flex-col gap-2">
                {items.map((profile) => (
                  <div key={profile.id} className="rounded-lg border border-line px-3 py-2.5 flex flex-wrap items-center justify-between gap-2 min-w-0">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <b className="text-sm text-ink break-words">{profile.name}</b>
                        {profile.is_default ? <span className="rounded-full bg-ok-50 px-2 py-0.5 text-[11px] text-ok">当前生效</span> : null}
                        {!profile.enabled ? <span className="rounded-full bg-line-subtle px-2 py-0.5 text-[11px] text-muted">已停用</span> : null}
                      </div>
                      <p className="mt-1 text-[11px] text-muted break-words">
                        {profile.provider} · {profile.model || "未填写模型"} · API Key {profile.api_key_configured ? "已配置" : "未配置"}
                      </p>
                      {testResult[profile.id] ? <p className="mt-1 text-[11px] text-muted">{testResult[profile.id]}</p> : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {category === "text" || category === "multimodal" ? (
                        <button className="rounded-md border border-line px-2.5 py-1 text-xs text-ink hover:border-brand hover:text-brand disabled:opacity-50" onClick={() => void test(profile)} disabled={busy}>
                          测试连接
                        </button>
                      ) : null}
                      <button className="rounded-md border border-line px-2.5 py-1 text-xs text-ink hover:border-brand hover:text-brand disabled:opacity-50" onClick={() => openEditor(profileDraft(profile))} disabled={busy}>
                        编辑
                      </button>
                      <button className="rounded-md px-2.5 py-1 text-xs text-bad hover:bg-bad-50 disabled:opacity-50" onClick={() => void remove(profile)} disabled={busy}>
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
