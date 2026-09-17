import { useEffect, useState, type ReactNode } from "react";
import {
  createPersona,
  fetchModelProfiles,
  fetchPersonas,
  fetchPersonaAssetTasks,
  fetchSettings,
  fetchVoiceOptions,
  previewVoice,
  updatePersona,
  updateSettings,
  uploadPersonaAvatar,
  type AppSettings,
  type AgentRun,
  type ModelProfile,
  type PersonaCard,
  type VoiceOption,
} from "./api";
import ModelProfileSelect from "./ModelProfileSelect";
import VoiceSelect from "./VoiceSelect";

const inputCls =
  "w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20";
const cardCls = "rounded-lg border border-line bg-white shadow-card p-4 flex flex-col gap-3 min-w-0";

const personaPresetOptions = [
  { value: "", label: "自定义" },
  { value: "work", label: "工作" },
  { value: "companion", label: "陪伴" },
  { value: "service", label: "服务" },
] as const;

const assetRunStatusZh: Record<string, string> = {
  pending: "等待",
  running: "处理中",
  completed: "完成",
  failed: "失败",
};

const splitList = (value: string): string[] =>
  value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean);

function voiceBadgeText(persona: PersonaCard, voiceOptions: VoiceOption[] = []): string {
  const voice = persona.voice?.voice;
  if (voice?.trim()) {
    // 供应商音色表里有中文名就优先用中文名，跟下拉框保持一致
    const matched = voiceOptions.find((item) => item.id === voice);
    if (matched?.name && matched.name !== matched.id) return matched.name;
    const parts = voice.split(/[_/]/).filter(Boolean);
    if (parts.length >= 2) return parts.slice(-2).join("_");
    return parts[parts.length - 1] ?? voice;
  }
  if (persona.voice?.provider) return persona.voice.provider;
  return "未设置音色";
}

function PersonaAvatar({ persona, className }: { persona: PersonaCard; className: string }) {
  if (persona.avatar?.trim()) {
    return (
      <img
        src={persona.avatar}
        alt={`${persona.name} 头像`}
        className={`${className} object-cover bg-surface-secondary`}
      />
    );
  }
  return (
    <div className={`${className} bg-brand text-white grid place-items-center font-bold shrink-0`}>
      {(persona.name || "?").slice(0, 1)}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  hint,
  type = "text",
  min,
  max,
  step,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  type?: string;
  min?: number | string;
  max?: number | string;
  step?: number | string;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-xs text-muted min-w-0">
      {label}
      <input
        className={inputCls}
        type={type}
        min={min}
        max={max}
        step={step}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint ? <small className="text-[11px] text-muted break-words">{hint}</small> : null}
    </label>
  );
}

function TextArea({
  label,
  value,
  onChange,
  placeholder,
  hint,
  rows = 3,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  rows?: number;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-xs text-muted min-w-0">
      {label}
      <textarea
        className={`${inputCls} min-h-[68px] resize-y`}
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint ? <small className="text-[11px] text-muted break-words">{hint}</small> : null}
    </label>
  );
}

function CardSection({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: string;
  children: ReactNode;
}) {
  return (
    <section className={cardCls}>
      <div className="flex items-center justify-between gap-2.5">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {badge ? <span className="rounded-full px-2 py-0.5 bg-line-subtle text-[11px] text-muted whitespace-nowrap">{badge}</span> : null}
      </div>
      {children}
    </section>
  );
}

export default function CharacterPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [personas, setPersonas] = useState<PersonaCard[]>([]);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [draft, setDraft] = useState<PersonaCard | null>(null);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [voiceOptions, setVoiceOptions] = useState<VoiceOption[]>([]);
  const [voiceProvider, setVoiceProvider] = useState("");
  const [voiceOptionsReason, setVoiceOptionsReason] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [assetRuns, setAssetRuns] = useState<AgentRun[]>([]);

  const previewVoiceSample = async (): Promise<void> => {
    setPreviewing(true);
    setError("");
    try {
      const blob = await previewVoice({
        provider: draft?.voice?.provider || undefined,
        model: draft?.voice?.model || undefined,
        voice: draft?.voice?.voice || undefined,
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

  const load = async (): Promise<void> => {
    setLoading(true);
    setError("");
    try {
      const [nextSettings, nextPersonas, nextProfiles] = await Promise.all([
        fetchSettings(),
        fetchPersonas(),
        fetchModelProfiles(),
      ]);
      setSettings(nextSettings);
      setPersonas(nextPersonas);
      setModelProfiles(
        nextProfiles.filter(
          (profile) => profile.enabled && (profile.category === "text" || profile.category === "multimodal"),
        ),
      );
      setDraft(nextPersonas.find((item) => item.id === nextSettings.active_persona_id) ?? nextPersonas[0] ?? null);
      setDirty(false);
      void fetchVoiceOptions()
        .then((list) => {
          setVoiceOptions(list.voices);
          setVoiceProvider(list.provider);
          setVoiceOptionsReason(list.reason);
        })
        .catch(() => {
          setVoiceOptions([]);
          setVoiceOptionsReason("音色列表获取失败，可直接填写音色 ID");
        });
      void fetchPersonaAssetTasks()
        .then(setAssetRuns)
        .catch(() => setAssetRuns([]));
    } catch (e) {
      setError(e instanceof Error ? e.message : "角色卡加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // 仅挂载时加载一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = (update: (current: PersonaCard) => PersonaCard): void => {
    setDraft((current) => (current ? update(current) : current));
    setDirty(true);
  };

  const setVoiceField = (
    key: "voice" | "speed" | "pitch" | "emotion" | "instruction",
    value: string | number | undefined,
  ): void => {
    patch((current) => ({ ...current, voice: { ...current.voice, [key]: value } }));
  };

  const setActivationField = (key: "persona_name" | "wake_prefixes" | "sleep_phrases", value: string): void => {
    if (key === "persona_name") {
      patch((current) => ({ ...current, activation: { ...current.activation, persona_name: value } }));
      return;
    }
    patch((current) => ({ ...current, activation: { ...current.activation, [key]: splitList(value) } }));
  };

  const setPreset = (value: string): void => {
    patch((current) => ({
      ...current,
      preset: value === "" ? null : (value as PersonaCard["preset"]),
    }));
  };

  const refreshAssetRuns = async (): Promise<void> => {
    try {
      setAssetRuns(await fetchPersonaAssetTasks());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "资产任务刷新失败");
    }
  };

  const setModelProfile = (profileId: string): void => {
    patch((current) => ({
      ...current,
      llm: profileId ? { ...current.llm, profile_id: profileId } : {},
    }));
  };

  const voicePayload = (persona: PersonaCard): Record<string, unknown> => ({
    active_persona_id: persona.id,
    ...(persona.voice?.speed != null ? { voice_speed: persona.voice.speed } : {}),
    ...(persona.voice?.pitch != null ? { voice_pitch: persona.voice.pitch } : {}),
    ...(persona.voice?.emotion ? { voice_emotion: persona.voice.emotion } : {}),
    ...(persona.voice?.instruction ? { voice_instruction: persona.voice.instruction } : {}),
  });

  const activate = async (persona: PersonaCard): Promise<void> => {
    if (dirty && !window.confirm("当前角色有未保存修改，启用其它角色将丢弃编辑，继续吗？")) return;
    setBusyId(persona.id);
    setError("");
    setNotice("");
    try {
      const nextSettings = await updateSettings(voicePayload(persona));
      setSettings(nextSettings);
      setDraft(persona);
      setDirty(false);
      setNotice(`已启用「${persona.name}」：身份与语音配置已生效。`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "启用失败");
    } finally {
      setBusyId(null);
    }
  };

  const save = async (): Promise<void> => {
    if (!draft) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await updatePersona(draft);
      const isActive = saved.id === settings?.active_persona_id;
      let nextSettings = settings;
      if (isActive) {
        nextSettings = await updateSettings(voicePayload(saved));
      }
      setSettings(nextSettings);
      setPersonas((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      setDraft(saved);
      setDirty(false);
      setNotice(
        isActive
          ? `已保存「${saved.name}」：语音配置已生效。`
          : `已保存「${saved.name}」。点击左侧卡片「启用」即可切换角色。`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const createNewPersona = async (): Promise<void> => {
    const id = window.prompt("请输入角色卡 ID（只允许英文、数字、_、-）", `persona_${personas.length + 1}`);
    if (!id) return;
    const name = window.prompt("请输入角色名称", "新角色");
    if (!name) return;
    setError("");
    setNotice("");
    try {
      const created = await createPersona({
        id,
        name,
        kind: "assistant",
        description: "新的桌面 AI 工作伙伴",
        personality: ["自然", "亲切"],
        backstory: "",
        language: "zh-CN",
        reply_style: "默认用中文、简洁、适合朗读。",
        avatar: "",
        voice: { provider: "minimax", model: "speech-2.8-hd", voice: "Chinese (Mandarin)_Soft_Girl", speed: 1.05, pitch: 1 },
        activation: { persona_name: name, wake_prefixes: ["你好", "嗨"], sleep_phrases: ["暂时静默", "先别说话", "安静一下"] },
      });
      setPersonas((current) => [...current, created]);
      setDraft(created);
      setDirty(false);
      setNotice(`已创建「${created.name}」。完善配置后点击「保存」。`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "角色卡创建失败");
    }
  };

  const selectPersona = (persona: PersonaCard): void => {
    setDraft(persona);
    setDirty(false);
  };

  const uploadAvatar = async (file: File): Promise<void> => {
    if (!draft) return;
    setUploadingAvatar(true);
    setError("");
    setNotice("");
    try {
      const result = await uploadPersonaAvatar(draft.id, file);
      const avatar = `${result.avatar}?v=${Date.now()}`;
      patch((current) => ({ ...current, avatar }));
      setNotice("形象已上传。点击底部「保存」后写入角色卡。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "形象上传失败");
    } finally {
      setUploadingAvatar(false);
    }
  };

  const heading = (
    <div className="flex flex-col gap-1">
      <h2 className="text-xl font-bold text-ink">角色卡</h2>
      <p className="text-sm text-muted">角色与语音绑定：启用一个角色，会整套切换其身份、音色与唤醒配置。</p>
    </div>
  );

  const noticeBlock = (
    <>
      {notice ? <div className="rounded-lg border border-ok/30 bg-ok-50 px-3 py-2.5 text-xs text-ok break-words">{notice}</div> : null}
      {error ? <div className="rounded-lg bg-bad-50 text-bad px-3.5 py-2.5 text-sm break-words">{error}</div> : null}
    </>
  );

  if (loading) {
    return (
      <section className="flex flex-col gap-3.5 min-w-0">
        {heading}
        <div className={cardCls}>
          <p className="text-sm text-muted">角色卡加载中…</p>
        </div>
      </section>
    );
  }

  if (error && !personas.length) {
    return (
      <section className="flex flex-col gap-3.5 min-w-0">
        {heading}
        {noticeBlock}
        <div className={cardCls}>
          <p className="text-sm text-muted break-words">{error}</p>
          <button className="rounded-lg px-4 py-2 bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors self-start" type="button" onClick={() => void load()}>
            重试加载
          </button>
        </div>
      </section>
    );
  }

  if (!personas.length) {
    return (
      <section className="flex flex-col gap-3.5 min-w-0">
        {heading}
        {noticeBlock}
        <div className={`${cardCls} items-center justify-center text-center py-10 gap-3`}>
          <p className="text-sm text-ink font-medium">还没有角色卡</p>
          <p className="text-xs text-muted">新建第一个角色卡，为 DeskMate 配置身份、音色与唤醒方式。</p>
          <button className="rounded-lg px-4 py-2.5 bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors" type="button" onClick={() => void createNewPersona()}>
            新建第一个角色卡
          </button>
        </div>
      </section>
    );
  }

  const activePersonaId = settings?.active_persona_id ?? "";

  return (
    <section className="flex flex-col gap-3.5 min-w-0">
      {heading}
      {noticeBlock}
      <div className="grid grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)] gap-3.5 min-w-0">
        {/* 左栏：角色库列表 */}
        <div className="flex flex-col gap-2.5 min-w-0">
          <div className="flex items-center justify-between gap-2.5 min-w-0">
            <h3 className="text-sm font-semibold text-ink">角色库</h3>
            <button className="text-brand text-xs hover:underline whitespace-nowrap" type="button" onClick={() => void createNewPersona()}>
              新建角色卡
            </button>
          </div>
          <div className="flex flex-col gap-2 min-w-0">
            {personas.map((persona) => {
              const isActive = persona.id === activePersonaId;
              const isSelected = draft?.id === persona.id;
              const isBusy = busyId === persona.id;
              return (
                <div
                  key={persona.id}
                  role="button"
                  tabIndex={0}
                  className={`rounded-lg border bg-white shadow-card p-3.5 flex flex-col gap-2.5 min-w-0 cursor-pointer transition-colors ${
                    isSelected ? "border-brand ring-1 ring-brand/20" : "border-line hover:border-brand"
                  }`}
                  onClick={() => selectPersona(persona)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectPersona(persona);
                    }
                  }}
                >
                  <div className="flex items-start gap-2.5 min-w-0">
                    <PersonaAvatar persona={persona} className="w-10 h-10 rounded-full text-lg" />
                    <div className="flex flex-col gap-1 min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="text-sm font-semibold text-ink truncate">{persona.name || "未命名角色"}</span>
                        {persona.kind ? <span className="text-[11px] text-muted whitespace-nowrap">· {persona.kind}</span> : null}
                      </div>
                      <div className="flex flex-wrap gap-1 min-w-0">
                        {persona.personality.slice(0, 3).map((tag) => (
                          <span key={tag} className="rounded-full bg-brand-50 text-brand px-2 py-0.5 text-[11px] break-words max-w-full">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="inline-flex items-center gap-1 rounded-full bg-line-subtle px-2 py-0.5 text-[11px] text-muted min-w-0" title={persona.voice?.voice ?? persona.voice?.provider}>
                      <span className="w-1.5 h-1.5 rounded-full bg-muted shrink-0" />
                      <span className="truncate">{voiceBadgeText(persona, voiceOptions)}</span>
                    </span>
                    <button
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors shrink-0 ${
                        isActive ? "bg-line-subtle text-muted cursor-default" : "bg-brand text-white hover:bg-brand-600"
                      }`}
                      type="button"
                      disabled={isActive || isBusy}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (!isActive) void activate(persona);
                      }}
                    >
                      {isActive ? "使用中" : isBusy ? "启用中…" : "启用"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 右栏：当前选中角色的编辑器 */}
        <div className="flex flex-col gap-3.5 min-w-0">
          {dirty ? (
            <div className="rounded-lg bg-warn-50 text-warn px-3 py-2.5 text-xs leading-relaxed">有未保存修改：改动仅在本页草稿中，点击下方「保存」才会写入角色卡。</div>
          ) : null}
          {draft ? (
            <>
              <div className="flex items-start justify-between gap-2.5 min-w-0">
                <div className="flex items-center gap-3 min-w-0">
                  <PersonaAvatar persona={draft} className="w-11 h-11 rounded-full text-lg" />
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <h3 className="text-base font-semibold text-ink break-words">{draft.name || "未命名角色"}</h3>
                    {draft.description ? <p className="text-xs text-muted break-words">{draft.description}</p> : null}
                  </div>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap shrink-0 ${draft.id === activePersonaId ? "bg-ok-50 text-ok" : "bg-line-subtle text-muted"}`}>
                  {draft.id === activePersonaId ? "使用中" : "未启用"}
                </span>
              </div>

              <CardSection title="身份人设" badge="身份">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 min-w-0">
                  <Field label="角色名称" value={draft.name} onChange={(value) => patch((current) => ({ ...current, name: value }))} hint="唤醒词默认使用这个名称。" />
                  <Field label="角色类型（kind）" value={draft.kind} onChange={(value) => patch((current) => ({ ...current, kind: value }))} hint="例如 assistant、cat、secretary。" />
                </div>
                <Field label="一句话介绍" value={draft.description} onChange={(value) => patch((current) => ({ ...current, description: value }))} hint="用于角色在主界面的简介。" />
                <Field
                  label="性格标签"
                  value={draft.personality.join("、")}
                  onChange={(value) => patch((current) => ({ ...current, personality: splitList(value) }))}
                  hint="用顿号分隔，例如：自然、可靠、略带幽默。"
                />
                <TextArea label="背景故事" value={draft.backstory} onChange={(value) => patch((current) => ({ ...current, backstory: value }))} hint="作为稳定人设背景，不等同于用户记忆。" />
                <TextArea label="回复风格" value={draft.reply_style} onChange={(value) => patch((current) => ({ ...current, reply_style: value }))} hint="会影响后续对话提示词和语音表达。" />
              </CardSection>

              <CardSection title="预设底座" badge="可选">
                <div className="flex flex-wrap gap-2">
                  {personaPresetOptions.map((option) => {
                    const selected = (draft.preset ?? "") === option.value;
                    return (
                      <button
                        key={option.value || "custom"}
                        type="button"
                        className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                          selected ? "border-brand bg-brand-50 text-brand" : "border-line text-muted hover:border-brand"
                        }`}
                        aria-pressed={selected}
                        onClick={() => setPreset(option.value)}
                      >
                        {option.label}
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] text-muted leading-relaxed break-words">
                  预设只作为稳定底座，角色卡中的身份、背景、回复风格等非空字段会覆盖预设；选择「自定义」则完全使用当前角色卡内容。
                </p>
              </CardSection>

              <CardSection title="模型绑定" badge="可跟随全局">
                <p className="text-xs text-muted leading-relaxed break-words">
                  只绑定模型档案，不在角色卡中保存 API Key。未指定时使用设置页对应分类的默认模型。
                </p>
                <div className="flex flex-col gap-1.5 text-xs text-muted">
                  通用文字 / 多模态模型
                  <ModelProfileSelect
                    value={draft.llm?.profile_id ?? ""}
                    options={[
                      { id: "", label: "跟随全局默认" },
                      ...modelProfiles.map((profile) => ({
                        id: profile.id,
                        label: `${profile.name} · ${profile.category === "multimodal" ? "多模态" : "文字"} · ${profile.model || profile.provider}`,
                      })),
                    ]}
                    onChange={setModelProfile}
                    ariaLabel="选择角色模型"
                    className="w-full"
                    buttonClassName="h-9 w-full text-sm"
                    menuClassName="left-0 w-full"
                  />
                </div>
                {modelProfiles.length === 0 ? (
                  <p className="rounded-lg bg-warn-50 px-3 py-2.5 text-xs text-warn leading-relaxed">
                    尚未配置文字或多模态模型，请先到设置页创建模型档案。
                  </p>
                ) : null}
              </CardSection>

              <CardSection title="形象" badge="V1">
                <div className="flex items-start gap-3 min-w-0">
                  <PersonaAvatar persona={draft} className="w-20 h-20 rounded-lg text-2xl" />
                  <div className="flex flex-col gap-2 min-w-0">
                    <label className="inline-flex items-center justify-center rounded-lg px-3 py-2 bg-brand text-white text-xs font-medium hover:bg-brand-600 transition-colors cursor-pointer w-fit">
                      {uploadingAvatar ? "上传中…" : "上传本地图片"}
                      <input
                        className="sr-only"
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        disabled={uploadingAvatar}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          event.currentTarget.value = "";
                          if (file) void uploadAvatar(file);
                        }}
                      />
                    </label>
                    <p className="text-[11px] text-muted leading-relaxed break-words">
                      支持 PNG、JPG、WebP，短边至少 512px、长边不超过 4096px，最大 15 MB。透明图会直接裁切；普通图需要背景颜色单一，系统会自动去背景并对齐到固定画布。
                    </p>
                  </div>
                </div>
                <Field
                  label="外部图片地址（可选）"
                  value={draft.avatar.startsWith("/api/personas/") ? "" : draft.avatar}
                  onChange={(value) => patch((current) => ({ ...current, avatar: value }))}
                  placeholder="https://…/avatar.png"
                  hint="上传本地图片后无需填写；远程图片仍可直接使用。"
                />
                <div className="rounded-lg bg-line-subtle px-3 py-2.5 text-xs text-muted leading-relaxed break-words">
                  V1 先使用一张完整基础形象，DeskMate 后续负责规范化和程序化动态；不要求你制作组件图或状态图。
                </div>
              </CardSection>

              <CardSection title="语音" badge="绑定本角色">
                <p className="text-xs text-muted leading-relaxed break-words">语音引擎与音色随角色启用生效；语音总开关、激活与默认状态见设置页「语音能力」。</p>
                <div className="flex items-center justify-between gap-2 min-w-0">
                  <p className="text-[11px] text-muted leading-relaxed break-words">
                    {draft.voice?.provider || draft.voice?.model
                      ? `语音引擎：${draft.voice?.provider ? `${draft.voice.provider} · ` : ""}${draft.voice?.model ?? "默认模型"}`
                      : "语音引擎跟随全局默认"}
                  </p>
                  <button
                    type="button"
                    className="shrink-0 text-[11px] text-brand hover:underline disabled:opacity-50"
                    onClick={() => void previewVoiceSample()}
                    disabled={previewing}
                    title="用当前音色合成一句样音（会消耗供应商额度，未保存的选择也会生效）"
                  >
                    {previewing ? "合成中…" : "试听"}
                  </button>
                </div>
                {voiceOptions.length > 0 ? (
                  <div className="flex flex-col gap-1.5 text-xs text-muted min-w-0">
                    <span>音色</span>
                    <VoiceSelect
                      options={voiceOptions}
                      value={draft.voice?.voice ?? ""}
                      onChange={(next) => setVoiceField("voice", next)}
                      previousOptionLabels={draft.voice?.voice ? { [draft.voice.voice]: "当前值，不在列表" } : undefined}
                    />
                    <small className="text-[11px] text-muted break-words">
                      共 {voiceOptions.length} 个音色，来自 {voiceProvider}。不同角色可绑定不同音色；音色多时可用上方输入框按名称或 ID 筛选。
                    </small>
                  </div>
                ) : (
                  <Field
                    label="音色"
                    value={draft.voice?.voice ?? ""}
                    onChange={(value) => setVoiceField("voice", value)}
                    placeholder="MiniMax Soft_Girl 类"
                    hint={voiceOptionsReason ?? "填写供应商音色 ID，例如 Chinese (Mandarin)_Soft_Girl。"}
                  />
                )}
                <div className="grid grid-cols-2 gap-2.5 min-w-0">
                  <Field
                    label="语速"
                    type="number"
                    min="0.5"
                    max="2"
                    step="0.05"
                    value={draft.voice?.speed ?? ""}
                    onChange={(value) => setVoiceField("speed", value === "" ? undefined : Number(value))}
                    hint="范围 0.5–2，步进 0.05。"
                  />
                  <Field
                    label="音高"
                    type="number"
                    min="0.5"
                    max="2"
                    step="0.05"
                    value={draft.voice?.pitch ?? ""}
                    onChange={(value) => setVoiceField("pitch", value === "" ? undefined : Number(value))}
                    hint="范围 0.5–2，步进 0.05。"
                  />
                </div>
                <Field
                  label="情绪"
                  value={draft.voice?.emotion ?? ""}
                  onChange={(value) => setVoiceField("emotion", value)}
                  placeholder="例如 gentle"
                  hint="可选；不同供应商支持的情绪标签不同。"
                />
                <TextArea
                  label="风格指令"
                  value={draft.voice?.instruction ?? ""}
                  onChange={(value) => setVoiceField("instruction", value)}
                  placeholder="例如：温柔、自然、语速适中"
                  hint="用于 TTS 的表现提示，不改变角色身份。"
                />
              </CardSection>

              <CardSection title="唤醒与监听" badge="绑定本角色">
                <Field
                  label="唤醒词角色名"
                  value={draft.activation?.persona_name ?? draft.name}
                  onChange={(value) => setActivationField("persona_name", value)}
                  hint={`例如"你好，${draft.activation?.persona_name ?? draft.name}"。`}
                />
                <Field
                  label="唤醒前缀"
                  value={(draft.activation?.wake_prefixes ?? []).join("、")}
                  onChange={(value) => setActivationField("wake_prefixes", value)}
                  hint="用顿号分隔多个前缀。"
                />
                <Field
                  label="静默指令"
                  value={(draft.activation?.sleep_phrases ?? []).join("、")}
                  onChange={(value) => setActivationField("sleep_phrases", value)}
                  hint="说出其中任意一句后，普通语音不会触发对话。"
                />
                <p className="text-xs text-muted leading-relaxed break-words">默认状态（常开/静默）是全局设置，见设置页「语音能力」。</p>
              </CardSection>

              <CardSection title="资产任务" badge="进度">
                <div className="flex items-center justify-between gap-2.5">
                  <p className="text-xs text-muted leading-relaxed break-words">音色克隆与形象导入的后台任务状态，数据由角色资产导入脚本维护。</p>
                  <button className="text-brand text-xs hover:underline whitespace-nowrap" type="button" onClick={() => void refreshAssetRuns()}>
                    刷新
                  </button>
                </div>
                {assetRuns.length ? (
                  <div className="flex flex-col gap-2">
                    {assetRuns.slice(0, 8).map((run) => {
                      const status = assetRunStatusZh[run.status] ?? run.status;
                      return (
                        <div key={run.run_id} className="rounded-lg border border-line bg-surface-secondary px-3 py-2.5 flex items-center justify-between gap-2.5 min-w-0">
                          <div className="flex flex-col gap-0.5 min-w-0">
                            <span className="text-xs font-medium text-ink break-words">{run.progress || run.run_id}</span>
                            <span className="text-[11px] text-muted break-words">{run.error || run.result || run.updated_at}</span>
                          </div>
                          <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ${
                            run.status === "completed" ? "bg-ok-50 text-ok" : run.status === "failed" ? "bg-bad-50 text-bad" : "bg-line-subtle text-muted"
                          }`}>
                            {status}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-muted">暂无资产任务。</p>
                )}
              </CardSection>

              <div className="flex items-center justify-between gap-2.5 min-w-0">
                <p className="text-[11px] text-muted break-words">
                  {draft.id === activePersonaId ? "当前角色正在使用中：保存后身份与语音配置立即生效。" : "保存仅写入角色卡；启用请点击左侧卡片「启用」。"}
                </p>
                <button
                  className="rounded-lg px-4 py-2.5 bg-brand text-white text-sm font-medium hover:bg-brand-600 transition-colors disabled:opacity-55 shrink-0"
                  type="button"
                  disabled={saving}
                  onClick={() => void save()}
                >
                  {saving ? "保存中…" : "保存"}
                </button>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}
