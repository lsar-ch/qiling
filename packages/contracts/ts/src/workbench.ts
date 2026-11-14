export interface WorkbenchItem {
  id: string;
  kind: "link" | "iframe" | "builtin";
  title: string;
  group: string | null;
  url: string | null;
  feature_id: string | null;
  visible: boolean;
  order: number;
}

export interface WorkbenchSettings {
  items: WorkbenchItem[];
}

export interface WorkbenchNote {
  note_id: string;
  title: string;
  content: string;
  project_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkbenchTodo {
  todo_id: string;
  title: string;
  description: string;
  project_path?: string | null;
  status: "pending" | "completed";
  created_at: string;
  updated_at: string;
}
