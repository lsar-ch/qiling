// 记忆契约 —— 镜像自 deskmate_contracts/memory.py。
export type MemoryLayer = "L2" | "L3" | "persona";

export interface MemoryEntrySummary {
  entry_id: string;
  section: string;
  text: string;
  refs: string[];
}

export interface MemorySection {
  title: string;
  entries: MemoryEntrySummary[];
}

export interface MemoryDoc {
  layer: MemoryLayer;
  key: string;
  title: string;
  raw_markdown: string;
  sections: MemorySection[];
}

export interface DocOverview {
  layer: MemoryLayer;
  key: string;
  title: string;
  entry_count: number;
  updated_at: string | null;
}

export interface SearchHit {
  entry_id: string;
  layer: MemoryLayer;
  key: string;
  section: string;
  text: string;
  refs: string[];
  score: number;
}

export interface MemoryBlock {
  source: string;
  text: string;
  chars: number;
}

export interface CompiledMemory {
  built_at: string;
  budget: number;
  blocks: MemoryBlock[];
  text: string;
}
