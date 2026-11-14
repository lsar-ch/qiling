import type { AnimalMotionAction, AnimalMotionConfig } from "../api";

export interface AnimalMotionMetrics {
  missing: string[];
  resolved: boolean;
}

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function asClipName(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  const record = asRecord(value);
  return record && typeof record.clip === "string" && record.clip.trim()
    ? record.clip.trim()
    : null;
}

function normalizeActionList(value: unknown): AnimalMotionAction[] {
  const items = Array.isArray(value) ? value : [value];
  return items.flatMap((item) => {
    const clip = asClipName(item);
    if (!clip) return [];
    const record = asRecord(item);
    const action: AnimalMotionAction = { clip };
    for (const key of ["repeat", "timeScale", "weight", "cooldownMs"] as const) {
      if (record && typeof record[key] === "number") action[key] = record[key];
    }
    return [action];
  });
}

function normalizeAnimalMotionConfig(
  config: AnimalMotionConfig | undefined,
): AnimalMotionConfig | undefined {
  const record = asRecord(config);
  if (!record) return undefined;
  const rawActions = asRecord(record.actions) ?? {};
  const actions = Object.fromEntries(
    Object.entries(rawActions)
      .map(([trigger, value]) => [trigger, normalizeActionList(value)] as const)
      .filter(([, candidates]) => candidates.length > 0),
  );
  const rawFallbacks = asRecord(record.fallbacks) ?? {};
  const fallbacks = Object.fromEntries(
    Object.entries(rawFallbacks)
      .map(([trigger, value]) => [
        trigger,
        (Array.isArray(value) ? value : [value])
          .map(asClipName)
          .filter((name): name is string => Boolean(name)),
      ] as const)
      .filter(([, names]) => names.length > 0),
  );
  return {
    ...(record as unknown as AnimalMotionConfig),
    actions,
    ...(Object.keys(fallbacks).length > 0 ? { fallbacks } : {}),
  };
}

/**
 * 动作候选 → 实际 clip。固定动作只允许静态动作兜底，不能退回 walk/run；
 * executing/project 才允许使用移动动作。
 */
export function resolveAnimalClip(
  config: AnimalMotionConfig | undefined,
  trigger: string,
  available: string[],
): string | null {
  if (available.length === 0) return null;
  const normalized = normalizeAnimalMotionConfig(config);
  const isLocomotionTrigger = trigger === "executing" || trigger === "project";
  const isLocomotionClip = (name: string): boolean => name === "walk" || name === "run";
  const candidates = (normalized?.actions[trigger] ?? []).filter(
    (item) => isLocomotionTrigger || !isLocomotionClip(item.clip),
  );
  const fromTrigger = candidates.find((item) => available.includes(item.clip));
  if (fromTrigger) return fromTrigger.clip;

  const fallbacks = (normalized?.fallbacks?.[trigger] ?? []).filter(
    (name) => isLocomotionTrigger || !isLocomotionClip(name),
  );
  const fromFallback = fallbacks.find((name) => available.includes(name));
  if (fromFallback) return fromFallback;

  const stationaryFallbacks = (normalized?.fallbacks?.idle ?? [
    "sit_idle",
    "sleep",
    "crouch",
    "idle",
  ]).filter((name) => !isLocomotionClip(name));
  return stationaryFallbacks.find((name) => available.includes(name)) ?? null;
}

export function animalMotionMetrics(config: AnimalMotionConfig | undefined, triggers: string[]): AnimalMotionMetrics {
  const normalized = normalizeAnimalMotionConfig(config);
  const names = new Set(Object.values(normalized?.actions ?? {}).flat().map((item) => item.clip));
  const missing = triggers.filter((trigger) => !normalized?.actions[trigger]?.length);
  return { missing, resolved: missing.length === 0 && names.size > 0 };
}
