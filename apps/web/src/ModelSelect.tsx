import { useEffect, useRef, useState } from "react";

const inputCls =
  "w-full border border-line rounded-lg px-2.5 py-2 text-sm text-ink focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/20";

/** 模型名称输入框：仍可手填，点击可展开供应商模型列表并点选。

    列表由父组件在点「获取」时拉取，这里只管展开/筛选/选中收起。 */
export default function ModelSelect({
  value,
  onChange,
  models,
  loading,
  reason,
  openRequest,
  placeholder,
  className = inputCls,
}: {
  value: string;
  onChange: (value: string) => void;
  models: string[];
  loading: boolean;
  reason: string | null;
  openRequest?: number;
  placeholder?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (event: MouseEvent): void => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const keyword = query.trim().toLowerCase();
  const visible = keyword ? models.filter((id) => id.toLowerCase().includes(keyword)) : models;

  useEffect(() => {
    if (!openRequest) return;
    setOpen(true);
    setQuery("");
  }, [openRequest]);

  const expand = (): void => {
    setOpen(true);
    setQuery("");
  };

  const pick = (id: string): void => {
    onChange(id);
    setOpen(false);
  };

  return (
    <div className="relative min-w-0" ref={boxRef}>
      <input
        className={className}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onFocus={expand}
        onClick={expand}
        placeholder={placeholder}
      />
      {open ? (
        <div className="absolute z-20 mt-1 w-full max-h-64 overflow-auto border border-line rounded-lg bg-surface shadow-lg">
          {models.length >= 12 ? (
            <input
              className="w-full border-b border-line px-2.5 py-2 text-sm text-ink focus:outline-none"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`筛选模型（共 ${models.length} 个）`}
              autoFocus
            />
          ) : null}
          {loading ? (
            <div className="px-2.5 py-2 text-xs text-muted">正在拉取模型列表…</div>
          ) : visible.length > 0 ? (
            visible.map((id) => (
              <button
                key={id}
                type="button"
                className={`block w-full px-2.5 py-2 text-left text-sm hover:bg-brand/10 ${id === value ? "text-brand" : "text-ink"}`}
                onClick={() => pick(id)}
              >
                {id}
              </button>
            ))
          ) : (
            <div className="px-2.5 py-2 text-xs text-muted break-words">
              {models.length === 0 ? (reason ?? "点击「获取」从供应商拉取可用模型列表，也可直接手填。") : `没有匹配「${query}」的模型`}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
