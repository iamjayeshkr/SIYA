// ui/src/hooks/useTauri.ts
// Wraps all Tauri invoke() calls with typed APIs.
// Falls back to mock data when running in browser (development).

import { invoke } from "@tauri-apps/api/core";

const IS_TAURI = "__TAURI_INTERNALS__" in window;

// ── Mock data for browser dev ─────────────────────────────────────────────────

const MOCK_RESPONSE = JSON.stringify({
  text: "Haan Rudra, main sun raha hoon. Tauri UI successfully connected!",
  model_used: "qwen2.5-7b",
  duration_ms: 312,
  tool_calls: [],
});

const MOCK_STATS = JSON.stringify({
  semantic_memories: 247,
  working_entries: 3,
  has_permanent: true,
});

const MOCK_MODELS = JSON.stringify({
  "qwen2.5-7b":  { healthy: true,  provider: "ollama", tier: "lightweight" },
  "qwen2.5-14b": { healthy: false, provider: "ollama", tier: "medium" },
  "gemini-flash": { healthy: true, provider: "gemini", tier: "medium" },
  "gemini-pro":  { healthy: true,  provider: "gemini", tier: "heavy" },
});

const MOCK_TOOLS = JSON.stringify([
  { id: 1, ts: new Date(Date.now() - 60000).toISOString(), tool_name: "web_search", duration_ms: 820, success: true, result_summary: "Found 10 results for 'Rust async runtime'" },
  { id: 2, ts: new Date(Date.now() - 120000).toISOString(), tool_name: "whatsapp_send", duration_ms: 1200, success: true, result_summary: "Message sent to +91..." },
  { id: 3, ts: new Date(Date.now() - 240000).toISOString(), tool_name: "memory_search", duration_ms: 45, success: true, result_summary: "3 results found" },
  { id: 4, ts: new Date(Date.now() - 400000).toISOString(), tool_name: "screen_read", duration_ms: 28000, success: false, error_msg: "timeout after 25s" },
]);

// ── API ───────────────────────────────────────────────────────────────────────

async function call<T>(cmd: string, args?: Record<string, unknown>, mock?: string): Promise<T> {
  if (!IS_TAURI) {
    await new Promise((r) => setTimeout(r, 300));
    return JSON.parse(mock ?? "null") as T;
  }
  const raw = await invoke<string>(cmd, args);
  return JSON.parse(raw) as T;
}

export function useTauri() {
  async function sendQuery(query: string) {
    return call<{
      text: string;
      model_used: string;
      duration_ms: number;
      tool_calls: Array<{ name: string; duration_ms: number; success: boolean }>;
    }>("send_query", { query }, MOCK_RESPONSE);
  }

  async function toggleListening(): Promise<boolean> {
    if (!IS_TAURI) return true;
    return invoke<boolean>("toggle_listening");
  }

  async function getMemoryStats() {
    return call<{ semantic_memories: number; working_entries: number }>(
      "get_memory_stats", {}, MOCK_STATS
    );
  }

  async function searchMemory(query: string) {
    return call<Array<{
      id: number; ts: string; text: string;
      source: string; tags: string[]; importance: number; score: number;
    }>>("search_memory", { query }, JSON.stringify([]));
  }

  async function getToolHistory(toolName?: string) {
    return call<Array<{
      id: number; ts: string; tool_name: string;
      duration_ms: number; success: boolean;
      error_msg?: string; result_summary?: string;
    }>>("get_tool_history", { toolName: toolName ?? null }, MOCK_TOOLS);
  }

  async function getModelStatus() {
    return call<Record<string, {
      healthy: boolean; provider: string; tier: string;
    }>>("get_model_status", {}, MOCK_MODELS);
  }

  async function hideToTray() {
    if (IS_TAURI) await invoke("hide_to_tray");
  }

  async function quitApp() {
    if (IS_TAURI) await invoke("quit_app");
  }

  return {
    sendQuery,
    toggleListening,
    getMemoryStats,
    searchMemory,
    getToolHistory,
    getModelStatus,
    hideToTray,
    quitApp,
    isTauri: IS_TAURI,
  };
}
