import { useEffect, useState } from "react";
import { DEFAULT_ACTIONS, type ActionSpec, type ActionTrigger } from "@deskmate/contracts";
import { fetchMotions, fetchPersonas, motionLibraryUrl, personaAssetUrl, saveMotions, type MotionOverrides, type PersonaCard, type VrmMotionConfig, type VrmClipRef } from "./api";
import VrmPreview from "./VrmPreview";

const FAMILIES = ["human", "animal", "anime"] as const;
type Family = (typeof FAMILIES)[number];

const TRIGGERS: ActionTrigger[] = [
  "idle", "listening", "thinking", "speaking", "executing", "awaiting_approval",
  "success", "error", "click", "project", "hover",
];

const DEFAULT_LOOP_TRIGGERS: string[] = [
  "idle", "listening", "thinking", "speaking", "executing", "awaiting_approval",
];

/** 调度节奏默认值，与后端 PresentationBridge._DEFAULT_ANIMATIONS 保持一致。 */
const DEFAULT_ANIMATIONS: Record<string, number> = {
  idle_action_interval_ms: 8000,
  transition_ms: 300,
  breath_rate: 1.0,
  blink_interval_ms: 4000,
};

const ANIMATION_FIELDS: { key: string; label: string; step: number }[] = [
  { key: "idle_action_interval_ms", label: "空闲轮询间隔 ms", step: 500 },
  { key: "transition_ms", label: "动作过渡 ms", step: 20 },
  { key: "blink_interval_ms", label: "眨眼间隔 ms", step: 100 },
  { key: "breath_rate", label: "呼吸速率", step: 0.05 },
];

/** 动作实验室的 VRMA 探测地址，与 VrmPreview 一致。 */
const assetUrl = (personaId: string, file: string): string => personaAssetUrl(personaId, file);

/** 配了共享动作库就从库里取，否则取角色自己的 vrma/。入参是动作基名（不带 .vrma）。 */
function clipUrl(personaId: string, library: string | undefined, clipName: string): string {
  return library
    ? motionLibraryUrl(library, `${clipName}.vrma`)
    : assetUrl(personaId, `vrma/${clipName}.vrma`);
}

/** 归一化 trigger -> 素材配置，缺省即同名文件；多候选取第一条用于预览。 */
function resolveClip(
  ref: VrmClipRef | VrmClipRef[] | undefined,
  fallback: string,
): { clip: string; repeat: number; timeScale: number } {
  const one = Array.isArray(ref) ? ref[0] : ref;
  if (one == null) return { clip: fallback, repeat: 1, timeScale: 1 };
  if (typeof one === "string") return { clip: one, repeat: 1, timeScale: 1 };
  return {
    clip: one.clip || fallback,
    repeat: Math.max(1, Math.floor(one.repeat ?? 1)),
    timeScale: one.timeScale && one.timeScale > 0 ? one.timeScale : 1,
  };
}

/** 列出共享库里的片段名：新导出的 vrma 丢进库里就能预览，不用先写进角色卡。 */
async function fetchLibraryClips(variant: string | undefined): Promise<string[]> {
  if (!variant) return [];
  try {
    const resp = await fetch(`/api/motion-library/${encodeURIComponent(variant)}`);
    if (!resp.ok) return [];
    return ((await resp.json()) as { clips?: string[] }).clips ?? [];
  } catch {
    return [];
  }
}

/** 列出 trigger 的全部候选（含权重），供总览展示；缺省即同名文件。 */
function listCandidates(
  ref: VrmClipRef | VrmClipRef[] | undefined,
  fallback: string,
): { clip: string; weight: number }[] {
  const list = ref == null ? [] : Array.isArray(ref) ? ref : [ref];
  if (list.length === 0) return [{ clip: fallback, weight: 1 }];
  return list.map((one) =>
    typeof one === "string"
      ? { clip: one || fallback, weight: 1 }
      : { clip: one.clip || fallback, weight: one.weight ?? 1 },
  );
}

/**
 * 动作实验室总览：一行一个状态，列出该状态下会播的动作。

 * 只做展示与定位，编辑仍在下方按 trigger 展开的面板里做。
 */
function OverviewMatrix({
  actions,
  family,
  isVrm,
  assetPresence,
  vrmActions,
  loopTriggers,
  onJump,
}: {
  actions: MotionOverrides;
  family: Family;
  isVrm: boolean;
  assetPresence: Record<string, boolean>;
  vrmActions: VrmMotionConfig["actions"];
  loopTriggers: string[];
  onJump: (t: ActionTrigger) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-black/5 text-xs text-muted">
          <tr>
            <th className="px-3 py-1.5 font-medium">状态</th>
            <th className="px-3 py-1.5 font-medium">动作（时长/冷却/权重）</th>
            <th className="px-3 py-1.5 font-medium">VRMA</th>
            <th className="px-3 py-1.5 font-medium">{isVrm ? "循环" : "循环（仅 3D）"}</th>
          </tr>
        </thead>
        <tbody>
          {TRIGGERS.map((trigger) => {
            const specs = actions[family]?.[trigger] ?? [];
            const present = assetPresence[trigger];
            const candidates = isVrm ? listCandidates(vrmActions?.[trigger], trigger) : [];
            return (
              <tr
                key={trigger}
                className="border-t border-line align-top hover:bg-black/[0.02]"
                onClick={() => onJump(trigger)}
              >
                <td className="whitespace-nowrap px-3 py-1.5 font-medium">{trigger}</td>
                <td className="px-3 py-1.5">
                  {specs.length === 0 && <span className="text-muted">—</span>}
                  {specs.map((s) => (
                    <div key={s.id} className="flex flex-wrap items-baseline gap-x-2">
                      <span className="truncate" title={s.id}>{s.id}</span>
                      <span className="truncate text-xs text-brand" title={`2D 动作类：${s.className}`}>
                        {s.className}
                      </span>
                      <span className="text-xs text-muted">
                        {s.durationMs ?? 0}ms / 冷却 {s.cooldownMs ?? 0}ms / 权重 {s.weight ?? 0}
                      </span>
                    </div>
                  ))}
                </td>
                <td className="px-3 py-1.5 text-xs">
                  {!isVrm ? <span className="text-muted">—</span> : (
                    <span className="flex items-start gap-1.5">
                      {present === undefined ? <span className="text-muted">…</span>
                        : present ? <span className="text-emerald-600">有</span>
                        : <span className="text-red-500">缺失</span>}
                      <span className="flex flex-wrap gap-x-1.5">
                        {candidates.map((c) => (
                          <span key={c.clip} className="whitespace-nowrap" title={`权重 ${c.weight}`}>
                            {c.clip}
                            {candidates.length > 1 && <span className="text-muted"> x{c.weight}</span>}
                          </span>
                        ))}
                      </span>
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-xs">
                  {!isVrm ? <span className="text-muted">—</span>
                    : loopTriggers.includes(trigger) ? "循环" : "单次"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function cloneDefaults(): MotionOverrides {
  const out: MotionOverrides = {};
  for (const family of FAMILIES) {
    out[family] = {};
    for (const trigger of TRIGGERS) {
      out[family][trigger] = (DEFAULT_ACTIONS[family][trigger] ?? []).map((a) => ({ ...a }));
    }
  }
  return out;
}

function mergeOverrides(base: MotionOverrides, overrides: MotionOverrides | null): MotionOverrides {
  if (!overrides) return base;
  for (const [family, triggers] of Object.entries(overrides)) {
    if (!base[family]) continue;
    for (const [trigger, specs] of Object.entries(triggers)) {
      if (!base[family][trigger]) continue;
      base[family][trigger] = specs.map((s) => {
        const existing = base[family][trigger].find((b) => b.id === s.id);
        return { ...(existing ?? s), ...s };
      });
    }
  }
  return base;
}

export default function MotionLabPage() {
  const [personas, setPersonas] = useState<PersonaCard[]>([]);
  const [personaId, setPersonaId] = useState("");
  const [family, setFamily] = useState<Family>("human");
  const [actions, setActions] = useState<MotionOverrides>({});
  const [vrm, setVrm] = useState<VrmMotionConfig>({ loop_triggers: DEFAULT_LOOP_TRIGGERS, crossfade_ms: 200 });
  const [animations, setAnimations] = useState<Record<string, number>>(DEFAULT_ANIMATIONS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [previewTrigger, setPreviewTrigger] = useState<ActionTrigger>("idle");
  const [dirty, setDirty] = useState(false);
  /** trigger -> VRMA 文件是否存在；仅 VRM persona 填充。 */
  const [assetPresence, setAssetPresence] = useState<Record<string, boolean>>({});
  /** persona 资产目录里实际存在的 VRMA 文件基名，供状态动作换素材。 */
  const [availableClips, setAvailableClips] = useState<string[]>([]);

  useEffect(() => {
    void fetchPersonas().then((items) => {
      setPersonas(items);
      if (items.length) setPersonaId(items[0].id);
    });
  }, []);

  useEffect(() => {
    if (!personaId) return;
    setLoading(true);
    void fetchMotions(personaId)
      .then((m) => {
        setActions(mergeOverrides(cloneDefaults(), m.actions));
        setVrm(m.vrm ?? { loop_triggers: DEFAULT_LOOP_TRIGGERS, crossfade_ms: 200 });
        setAnimations({ ...DEFAULT_ANIMATIONS, ...(m.animations ?? {}) });
        setDirty(false);
      })
      .finally(() => setLoading(false));
  }, [personaId]);

  const activePersona = personas.find((p) => p.id === personaId);
  const isVrm = !!(activePersona as (PersonaCard & { vrm?: string }) | undefined)?.vrm;

  // VRM persona：一次探测 11 个 trigger 基名是否存在，同时得到「可选素材」与「当前映射是否命中」。
  // ponytail: 基名集合按导入契约固定为 trigger 名，够用；素材改名就落后端校验了。
  useEffect(() => {
    if (!personaId || !isVrm) {
      setAssetPresence({});
      setAvailableClips([]);
      return;
    }
    let disposed = false;
    void (async () => {
      // 探测集合 = 11 个 trigger 基名 + 角色卡引用的候选名 + 库里全部片段。
      const listed = await fetchLibraryClips(vrm.library);
      if (disposed) return;
      const probeNames = Array.from(
        new Set([
          ...TRIGGERS,
          ...TRIGGERS.flatMap((t) => listCandidates(vrm.actions?.[t], t).map((c) => c.clip)),
          ...listed,
        ]),
      );
      const entries = await Promise.all(
        probeNames.map(async (name) => {
          try {
            const r = await fetch(clipUrl(personaId, vrm.library, name), { method: "HEAD" });
            return [name, r.ok] as const;
          } catch {
            return [name, false] as const;
          }
        }),
      );
      if (disposed) return;
      const has: Record<string, boolean> = Object.fromEntries(entries);
      // 候选里只要缺一条就算缺失，避免总览给出假「有」。
      const presence: Record<string, boolean> = {};
      TRIGGERS.forEach((t) => {
        presence[t] = listCandidates(vrm.actions?.[t], t).every((c) => has[c.clip]);
      });
      setAssetPresence(presence);
      setAvailableClips(probeNames.filter((name) => has[name]));
    })();
    return () => { disposed = true; };
  }, [personaId, isVrm, vrm.actions, vrm.library]);

  const setAction = (trigger: ActionTrigger, index: number, patch: Partial<ActionSpec>): void => {
    setActions((prev) => {
      const next: MotionOverrides = { ...prev };
      const list = [...(next[family]?.[trigger] ?? [])];
      list[index] = { ...list[index], ...patch };
      next[family] = { ...next[family], [trigger]: list };
      return next;
    });
    setDirty(true);
  };

  const toggleLoopTrigger = (t: string): void => {
    setVrm((prev) => {
      const cur = prev.loop_triggers ?? [];
      const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t];
      return { ...prev, loop_triggers: next };
    });
    setDirty(true);
  };

  /**
   * 换 trigger 的 VRMA 素材；落回同名时删掉键，配置保持干净。
   * 对象形式（带 repeat/timeScale）只改 clip，保留另一个字段，否则会悄悄丢配置。
   * 多候选数组只换第一条，其余候选原样留着 —— 否则下拉一改就把候选表清空了。
   */
  const setClipRef = (t: ActionTrigger, clip: string): void => {
    setVrm((prev) => {
      const actions = { ...(prev.actions ?? {}) };
      const cur = actions[t];
      if (Array.isArray(cur)) {
        const [head, ...rest] = cur;
        const first =
          typeof head === "object" && head !== null ? { ...head, clip } : clip;
        actions[t] = [first, ...rest];
      } else {
        const keep = typeof cur === "object" && cur !== null ? cur : null;
        if (clip === t && !keep) delete actions[t];
        else if (keep) actions[t] = { ...keep, clip };
        else actions[t] = clip;
      }
      return { ...prev, actions };
    });
    setDirty(true);
  };

  const save = async (): Promise<void> => {
    if (!personaId) return;
    setSaving(true);
    setNotice("");
    try {
      await saveMotions(personaId, { actions, vrm, animations });
      setDirty(false);
      setNotice("已保存，桌面挂件将实时生效。");
    } catch (e) {
      setNotice(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const previewSpecs = actions[family]?.[previewTrigger] ?? [];
  const previewLoop = vrm.loop_triggers?.includes(previewTrigger) ?? false;
  // 2D 动作可选类名：该 family 全部 trigger 用到的 class 去重，够用且不用新接口。
  const classOptions = Array.from(
    new Set(TRIGGERS.flatMap((t) => (actions[family]?.[t] ?? []).map((s) => s.className))),
  ).filter(Boolean).sort();

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="mb-4 flex items-center justify-end gap-4">
        <button
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          disabled={saving || !dirty || !personaId}
          onClick={() => void save()}
        >
          {saving ? "保存中…" : "保存"}
        </button>
      </div>

      {notice && <div className="mb-4 rounded-lg bg-black/5 px-3 py-2 text-sm">{notice}</div>}

      <div className="mb-4 flex items-center gap-3">
        <label className="text-sm text-muted">角色</label>
        <select
          className="rounded-lg border border-line bg-white px-3 py-2 text-sm"
          value={personaId}
          onChange={(e) => setPersonaId(e.target.value)}
        >
          {personas.map((p) => (
            <option key={p.id} value={p.id}>{p.name}（{p.id}）</option>
          ))}
        </select>
        <div className="ml-4 flex rounded-lg border border-line p-0.5">
          {FAMILIES.map((f) => (
            <button
              key={f}
              className={`rounded-md px-3 py-1 text-sm ${family === f ? "bg-brand text-white" : "text-muted"}`}
              onClick={() => setFamily(f)}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {!loading && (
        <div className="mb-4">
          <div className="mb-2 text-sm font-semibold">{family} 全状态总览</div>
          <OverviewMatrix
            actions={actions}
            family={family}
            isVrm={isVrm}
            assetPresence={assetPresence}
            vrmActions={vrm.actions}
            loopTriggers={vrm.loop_triggers ?? []}
            onJump={(t) => setPreviewTrigger(t)}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-2">
          {loading ? (
            <div className="text-sm text-muted">加载中…</div>
          ) : (
            TRIGGERS.map((trigger) => {
              const specs = actions[family]?.[trigger] ?? [];
              return (
                <details key={trigger} className="rounded-lg border border-line bg-white">
                  <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm font-medium">
                    <button
                      className="rounded bg-black/5 px-2 py-0.5 text-xs"
                      onClick={(e) => { e.preventDefault(); setPreviewTrigger(trigger); }}
                    >
                      预览
                    </button>
                    <span>{trigger}</span>
                    <span className="text-xs text-muted">{specs.length} 个动作</span>
                  </summary>
                  {specs.map((spec, i) => (
                    <div key={spec.id} className="grid grid-cols-[1fr_90px_90px_70px] items-center gap-2 border-t border-line px-3 py-1.5 text-sm">
                      <span className="flex items-center gap-2 overflow-hidden">
                        <span className="truncate" title={spec.id}>{spec.id}</span>
                        <select
                          className="rounded border border-line bg-white px-1 py-0.5 text-xs text-black"
                          value={spec.className ?? ""}
                          onChange={(e) => setAction(trigger, i, { className: e.target.value })}
                        >
                          {!classOptions.includes(spec.className ?? "") && (
                            <option value={spec.className ?? ""}>{spec.className ?? "（无）"}</option>
                          )}
                          {classOptions.map((c) => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                        </select>
                      </span>
                      <NumberInput label="时长ms" value={spec.durationMs ?? 0} onChange={(v) => setAction(trigger, i, { durationMs: v })} />
                      <NumberInput label="冷却ms" value={spec.cooldownMs ?? 0} onChange={(v) => setAction(trigger, i, { cooldownMs: v })} />
                      <NumberInput label="权重" value={spec.weight ?? 0} onChange={(v) => setAction(trigger, i, { weight: v })} />
                    </div>
                  ))}
                </details>
              );
            })
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border border-line bg-white p-3">
            <h2 className="mb-2 text-sm font-semibold">预览 {previewTrigger}</h2>
            {isVrm && (
              <VrmPreview
                personaId={personaId}
                library={vrm.library}
                trigger={previewTrigger}
                clipBase={resolveClip(vrm.actions?.[previewTrigger], previewTrigger).clip}
                loop={previewLoop}
                crossfadeMs={vrm.crossfade_ms}
              />
            )}
            {!isVrm && (
              <div className="flex h-64 items-center justify-center rounded-lg bg-black/5 text-sm text-muted">
                <span className="mascot-preview">{previewSpecs[0]?.className ?? "—"}</span>
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {previewSpecs.map((s) => (
                <button key={s.id} className="rounded bg-black/5 px-2 py-0.5 text-xs">{s.className}</button>
              ))}
            </div>
            {isVrm && (
              <label className="mt-3 block text-xs text-muted">
                动作库（3D）
                <select
                  className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1 text-sm text-black"
                  value={vrm.library ?? ""}
                  onChange={(e) => {
                    const next = e.target.value || undefined;
                    setVrm((prev) => ({ ...prev, library: next }));
                    setDirty(true);
                  }}
                >
                  <option value="">（不用库，读角色自己的 vrma/）</option>
                  {["female", "male"].map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </label>
            )}
            {isVrm && (
              <label className="mt-3 block text-xs text-muted">
                VRMA 素材（3D）
                <select
                  className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1 text-sm text-black"
                  value={resolveClip(vrm.actions?.[previewTrigger], previewTrigger).clip}
                  onChange={(e) => setClipRef(previewTrigger, e.target.value)}
                >
                  {!availableClips.includes(previewTrigger) && (
                    <option value={previewTrigger}>{previewTrigger}（缺失）</option>
                  )}
                  {availableClips.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <div className="rounded-lg border border-line bg-white p-3">
            <h2 className="mb-2 text-sm font-semibold">调度节奏</h2>
            <div className="space-y-2">
              {ANIMATION_FIELDS.map((f) => (
                <label key={f.key} className="flex items-center justify-between gap-2 text-xs text-muted">
                  <span>{f.label}</span>
                  <input
                    type="number"
                    step={f.step}
                    className="w-28 rounded border border-line px-1.5 py-0.5 text-sm text-black"
                    value={animations[f.key] ?? DEFAULT_ANIMATIONS[f.key]}
                    onChange={(e) => {
                      setAnimations((p) => ({ ...p, [f.key]: Number(e.target.value) }));
                      setDirty(true);
                    }}
                  />
                </label>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">
              idle 状态下每 {animations.idle_action_interval_ms ?? 8000}ms 轮询一次；挂件再按交互模式乘系数（work 1.2 / casual 0.8）。
            </p>
          </div>

          <div className="rounded-lg border border-line bg-white p-3">
            <h2 className="mb-2 text-sm font-semibold">VRM 播放参数</h2>
            <label className="mb-2 block text-xs text-muted">循环 trigger</label>
            <div className="mb-3 flex flex-wrap gap-1.5">
              {TRIGGERS.map((t) => (
                <button
                  key={t}
                  className={`rounded px-2 py-0.5 text-xs ${(vrm.loop_triggers ?? []).includes(t) ? "bg-brand text-white" : "bg-black/5"}`}
                  onClick={() => toggleLoopTrigger(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            <label className="block text-xs text-muted">交叉淡化 ms</label>
            <input
              type="number"
              className="mt-1 w-32 rounded-lg border border-line px-2 py-1 text-sm"
              value={vrm.crossfade_ms ?? 200}
              onChange={(e) => { setVrm((p) => ({ ...p, crossfade_ms: Number(e.target.value) })); setDirty(true); }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function NumberInput({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col text-xs text-muted">
      <span>{label}</span>
      <input
        type="number"
        className="mt-0.5 rounded border border-line px-1.5 py-0.5 text-sm"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}
