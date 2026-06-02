// ui/src/store/index.ts
// Zustand global store for Vani OS UI

import { create } from "zustand";

export type VoiceMode = "primary" | "fallback";
export type AppView = "chat" | "memory" | "tools" | "models" | "settings";

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  model?: string;
  ts: number;
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  name: string;
  duration_ms: number;
  success: boolean;
  result_preview?: string;
}

export interface MemoryEntry {
  id: number;
  ts: string;
  text: string;
  source: string;
  tags: string[];
  importance: number;
  score?: number;
}

export interface ModelStatus {
  id: string;
  healthy: boolean;
  provider: string;
  tier: string;
}

export interface ToolAuditRow {
  id: number;
  ts: string;
  tool_name: string;
  duration_ms: number;
  success: boolean;
  error_msg?: string;
  result_summary?: string;
}

interface VaniStore {
  // View
  view: AppView;
  setView: (v: AppView) => void;

  // Voice
  isListening: boolean;
  voiceMode: VoiceMode;
  setListening: (v: boolean) => void;
  setVoiceMode: (v: VoiceMode) => void;

  // Conversation
  messages: Message[];
  isThinking: boolean;
  addMessage: (m: Message) => void;
  setThinking: (v: boolean) => void;
  clearMessages: () => void;

  // Memory
  memoryResults: MemoryEntry[];
  memoryStats: { semantic_memories: number; working_entries: number } | null;
  setMemoryResults: (r: MemoryEntry[]) => void;
  setMemoryStats: (s: VaniStore["memoryStats"]) => void;

  // Models
  modelStatus: Record<string, ModelStatus>;
  setModelStatus: (s: Record<string, ModelStatus>) => void;

  // Tools
  toolHistory: ToolAuditRow[];
  setToolHistory: (h: ToolAuditRow[]) => void;
}

export const useVaniStore = create<VaniStore>((set) => ({
  view: "chat",
  setView: (view) => set({ view }),

  isListening: false,
  voiceMode: "primary",
  setListening: (isListening) => set({ isListening }),
  setVoiceMode: (voiceMode) => set({ voiceMode }),

  messages: [],
  isThinking: false,
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setThinking: (isThinking) => set({ isThinking }),
  clearMessages: () => set({ messages: [] }),

  memoryResults: [],
  memoryStats: null,
  setMemoryResults: (memoryResults) => set({ memoryResults }),
  setMemoryStats: (memoryStats) => set({ memoryStats }),

  modelStatus: {},
  setModelStatus: (modelStatus) => set({ modelStatus }),

  toolHistory: [],
  setToolHistory: (toolHistory) => set({ toolHistory }),
}));
