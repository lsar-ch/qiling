// 轻量 Markdown 渲染：只覆盖执行器/模型常用的几种语法，不引第三方依赖。
// 目标只有一个——把后台回来的长文本排得能读，且绝不注入 HTML。
import { useState, type ReactNode } from "react";

type Block =
  | { kind: "code"; lang: string; text: string }
  | { kind: "heading"; level: number; text: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "p"; text: string };

const COLLAPSE_AT = 1400;
const FENCE = /^\s*```(.*)$/;
const HEADING = /^\s{0,3}#{1,4}\s+(.*)$/;
const BULLET = /^\s*[-*•]\s+(.*)$/;
const ORDERED = /^\s*(\d+)[.)]\s+(.*)$/;

function splitBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  let ordered: string[] = [];

  const flushParagraph = (): void => {
    if (paragraph.length) blocks.push({ kind: "p", text: paragraph.join("\n") });
    paragraph = [];
  };
  const flushLists = (): void => {
    if (list.length) blocks.push({ kind: "ul", items: list });
    if (ordered.length) blocks.push({ kind: "ol", items: ordered });
    list = [];
    ordered = [];
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const fence = line.match(FENCE);
    if (fence) {
      const lang = (fence[1] || "").trim();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      flushParagraph();
      flushLists();
      blocks.push({ kind: "code", lang, text: body.join("\n") });
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      flushParagraph();
      flushLists();
      blocks.push({ kind: "heading", level: (line.match(/#/g) ?? []).length, text: heading[1] });
      continue;
    }
    const bullet = line.match(BULLET);
    if (bullet) {
      flushParagraph();
      ordered = flushIfNeed(ordered, "ol", blocks);
      list.push(bullet[1]);
      continue;
    }
    const orderedItem = line.match(ORDERED);
    if (orderedItem) {
      flushParagraph();
      list = flushIfNeed(list, "ul", blocks);
      ordered.push(orderedItem[2]);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushLists();
      continue;
    }
    flushLists();
    paragraph.push(line.trim());
  }
  flushParagraph();
  flushLists();
  return blocks;
}

function flushIfNeed(items: string[], kind: "ul" | "ol", blocks: Block[]): string[] {
  if (items.length) blocks.push(kind === "ul" ? { kind: "ul", items } : { kind: "ol", items });
  return [];
}

// 行内语法：行内代码、粗体、链接。其余按纯文本输出（不注入 HTML）。
function inline(text: string): ReactNode[] {
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
  const out: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const key = `in-${(index += 1)}`;
    if (match[1] !== undefined) {
      out.push(
        <code key={key} className="px-1 py-0.5 rounded bg-surface-secondary font-mono text-[12px] break-anywhere">
          {match[1]}
        </code>,
      );
    } else if (match[2] !== undefined) {
      out.push(<strong key={key}>{match[2]}</strong>);
    } else {
      out.push(
        <a key={key} href={match[4]} target="_blank" rel="noreferrer noopener" className="text-brand hover:underline break-anywhere">
          {match[3]}
        </a>,
      );
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function MarkdownLite({
  text,
  collapsible = true,
}: {
  text: string;
  collapsible?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const trimmed = text.replace(/\n{3,}/g, "\n\n").trim();
  if (!trimmed) return null;
  const long = trimmed.length > COLLAPSE_AT;
  const body = long && !expanded ? `${trimmed.slice(0, COLLAPSE_AT)}\n\n…` : trimmed;

  return (
    <div className="min-w-0">
      {splitBlocks(body).map((block, i) => {
        const key = `b-${i}`;
        if (block.kind === "code") {
          return (
            <pre key={key} className="my-2 rounded-lg bg-surface-secondary border border-line p-2.5 overflow-x-auto scroll-thin">
              <code className="font-mono text-[12px] leading-relaxed whitespace-pre">{block.text}</code>
              {block.lang && <span className="block mt-1 text-[10px] text-muted">{block.lang}</span>}
            </pre>
          );
        }
        if (block.kind === "heading") {
          const size = block.level <= 1 ? "text-[15px]" : "text-sm";
          return (
            <p key={key} className={`mt-2.5 mb-1 font-semibold text-ink ${size}`}>
              {inline(block.text)}
            </p>
          );
        }
        if (block.kind === "ul" || block.kind === "ol") {
          const items = block.items;
          return block.kind === "ul" ? (
            <ul key={key} className="my-1 pl-4 list-disc space-y-1">
              {items.map((item, j) => <li key={j}>{inline(item)}</li>)}
            </ul>
          ) : (
            <ol key={key} className="my-1 pl-4 list-decimal space-y-1">
              {items.map((item, j) => <li key={j}>{inline(item)}</li>)}
            </ol>
          );
        }
        return (
          <p key={key} className="my-1 first:mt-0 last:mb-0">
            {inline(block.text)}
          </p>
        );
      })}
      {long && (
        <button
          type="button"
          className="mt-1.5 text-[11px] text-brand hover:underline"
          onClick={() => setExpanded((prev) => !prev)}
        >
          {expanded ? "收起" : `展开全文（共 ${trimmed.length} 字）`}
        </button>
      )}
    </div>
  );
}
