import { useState } from "react";
import type { VoiceOption } from "./api";

const KIND_ORDER: VoiceOption["kind"][] = ["system", "cloned", "preset"];
const KIND_LABELS: Record<VoiceOption["kind"], string> = {
  system: "系统音色",
  cloned: "克隆音色",
  preset: "预置音色",
};

const inputCls =
  "w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20";

/** 音色下拉：按种类分组，音色多时带关键词过滤（MiniMax 单账号就有 300+ 项）。 */
export default function VoiceSelect({
  options,
  value,
  onChange,
  className = inputCls,
  previousOptionLabels,
  emptyLabel = "跟随全局默认",
}: {
  options: VoiceOption[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
  /** 值不在列表里时显示的补充选项，键为值、值为文案后缀，例如「当前值，不在列表」。 */
  previousOptionLabels?: Record<string, string>;
  emptyLabel?: string;
}) {
  const [query, setQuery] = useState("");
  const keyword = query.trim().toLowerCase();
  const visible = keyword
    ? options.filter((item) => `${item.name} ${item.id}`.toLowerCase().includes(keyword))
    : options;
  const extras = Object.entries(previousOptionLabels ?? {}).filter(([id]) => id && !visible.some((item) => item.id === id));

  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      {options.length >= 20 ? (
        <input
          className={className}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`筛选音色（共 ${options.length} 个，可按中文名或 ID 搜索）`}
        />
      ) : null}
      <select className={className} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{emptyLabel}</option>
        {extras.map(([id, label]) => (
          <option key={id} value={id}>
            {id}
            {label ? `（${label}）` : ""}
          </option>
        ))}
        {KIND_ORDER.map((kind) => {
          const items = visible.filter((item) => item.kind === kind);
          if (items.length === 0) return null;
          return (
            <optgroup key={kind} label={`${KIND_LABELS[kind]}（${items.length}）`}>
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </optgroup>
          );
        })}
      </select>
      {keyword && visible.length === 0 ? (
        <small className="text-[11px] text-muted break-words">没有匹配「{query}」的音色，清空筛选可看全部。</small>
      ) : null}
    </div>
  );
}
