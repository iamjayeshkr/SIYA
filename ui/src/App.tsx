/* ui/src/App.tsx — Vani OS complete UI */
import { useState, useRef, useEffect, useCallback } from "react";

/* ── Types ──────────────────────────────────────────────────────────────── */
type View = "chat" | "memory" | "tools" | "models";
type VoiceMode = "primary" | "fallback";
interface Msg { id: string; role: "user"|"assistant"; text: string; model?: string; ts: number; tool_calls?: TC[]; }
interface TC  { name: string; duration_ms: number; success: boolean; }
interface MemEntry { id: number; ts: string; text: string; source: string; tags: string[]; importance: number; score?: number; }
interface ModelInfo { healthy: boolean; provider: string; tier: string; }
interface ToolRow { id: number; ts: string; tool_name: string; duration_ms: number; success: boolean; error_msg?: string; }

/* ── Tauri IPC (mocked in browser) ─────────────────────────────────────── */
const IS_TAURI = "__TAURI_INTERNALS__" in window;
async function tauriInvoke<T>(cmd: string, args?: unknown, mock?: T): Promise<T> {
  if (!IS_TAURI) { await new Promise(r => setTimeout(r, 400 + Math.random()*300)); return mock as T; }
  const { invoke } = await import("@tauri-apps/api/core");
  const raw = await invoke<string>(cmd, args as Record<string,unknown>);
  return JSON.parse(raw);
}

/* ── Helpers ────────────────────────────────────────────────────────────── */
function uid() { return Math.random().toString(36).slice(2); }
function relTime(ts: string) {
  const d = Date.now() - new Date(ts).getTime(), s = d/1000;
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s/60)}m ago`;
  if (s < 86400) return `${Math.round(s/3600)}h ago`;
  return `${Math.round(s/86400)}d ago`;
}

/* ── Mock data ──────────────────────────────────────────────────────────── */
const MOCK_REPLY = { text: "Haan Rudra! Tauri UI is live. Main sab kuch samajh raha hoon — voice, memory, tools sab ready hain. Kya karna hai?", model_used: "qwen2.5-7b", duration_ms: 314, tool_calls: [{ name: "memory_search", duration_ms: 42, success: true }] };
const MOCK_MEMORIES: MemEntry[] = [
  { id:1, ts: new Date(Date.now()-3600000).toISOString(), text:"Rudra prefers dark mode for all interfaces", source:"manual", tags:["preference","ui"], importance:1.5, score:0.94 },
  { id:2, ts: new Date(Date.now()-86400000).toISOString(), text:"Vani Core rewrite decided: Rust for performance, async-first", source:"conversation", tags:["decision","architecture"], importance:2.0, score:0.89 },
  { id:3, ts: new Date(Date.now()-172800000).toISOString(), text:"P4 Rust deadline end of August", source:"conversation", tags:["deadline","project"], importance:1.8, score:0.81 },
  { id:4, ts: new Date(Date.now()-259200000).toISOString(), text:"WhatsApp tool times out ~30% of the time on Monday mornings", source:"tool", tags:["bug","whatsapp"], importance:1.2, score:0.76 },
  { id:5, ts: new Date(Date.now()-604800000).toISOString(), text:"Rudra's MacBook has 32GB RAM — can run qwen2.5:14b locally", source:"conversation", tags:["hardware","models"], importance:1.0, score:0.71 },
];
const MOCK_MODELS: Record<string, ModelInfo> = {
  "qwen2.5-7b":  { healthy:true,  provider:"ollama", tier:"lightweight" },
  "qwen2.5-3b":  { healthy:true,  provider:"ollama", tier:"lightweight" },
  "llama3.2-3b": { healthy:false, provider:"ollama", tier:"lightweight" },
  "qwen2.5-14b": { healthy:true,  provider:"ollama", tier:"medium"      },
  "gemini-flash":{ healthy:true,  provider:"gemini", tier:"medium"      },
  "gemini-pro":  { healthy:true,  provider:"gemini", tier:"heavy"       },
};
const MOCK_TOOLS: ToolRow[] = [
  { id:1, ts:new Date(Date.now()-40000).toISOString(),   tool_name:"memory_search",  duration_ms:42,    success:true  },
  { id:2, ts:new Date(Date.now()-90000).toISOString(),   tool_name:"web_search",     duration_ms:820,   success:true  },
  { id:3, ts:new Date(Date.now()-180000).toISOString(),  tool_name:"whatsapp_send",  duration_ms:1240,  success:true  },
  { id:4, ts:new Date(Date.now()-300000).toISOString(),  tool_name:"screen_read",    duration_ms:25000, success:false, error_msg:"timeout after 25s" },
  { id:5, ts:new Date(Date.now()-500000).toISOString(),  tool_name:"youtube_play",   duration_ms:340,   success:true  },
  { id:6, ts:new Date(Date.now()-700000).toISOString(),  tool_name:"memory_write",   duration_ms:28,    success:true  },
  { id:7, ts:new Date(Date.now()-900000).toISOString(),  tool_name:"browser_navigate",duration_ms:680,  success:true  },
  { id:8, ts:new Date(Date.now()-1200000).toISOString(), tool_name:"whatsapp_read",  duration_ms:30001, success:false, error_msg:"timeout after 30s" },
];

/* ════════════════════════════════════════════════════════════════════════════
   ROOT APP
════════════════════════════════════════════════════════════════════════════ */
export default function App() {
  const [view, setView]           = useState<View>("chat");
  const [listening, setListening] = useState(false);
  const [voiceMode]               = useState<VoiceMode>("primary");
  const [msgs, setMsgs]           = useState<Msg[]>([
    { id:uid(), role:"assistant", text:"Namaste Rudra 🙏 Vani P3 Tauri UI ready hai. Bolo kya karna hai?", ts:Date.now() }
  ]);
  const [thinking, setThinking]   = useState(false);
  const [input, setInput]         = useState("");
  const [memSearch, setMemSearch] = useState("");
  const [memories, setMemories]   = useState<MemEntry[]>(MOCK_MEMORIES);
  const [models, setModels]       = useState<Record<string,ModelInfo>>(MOCK_MODELS);
  const [tools, setTools]         = useState<ToolRow[]>(MOCK_TOOLS);
  const [memStats]                = useState({ semantic_memories: 247, working_entries: 3 });
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior:"smooth" }); }, [msgs, thinking]);

  const sendMsg = useCallback(async (text: string) => {
    if (!text.trim()) return;
    setInput("");
    const userMsg: Msg = { id:uid(), role:"user", text, ts:Date.now() };
    setMsgs(p => [...p, userMsg]);
    setThinking(true);
    try {
      const res = await tauriInvoke("send_query", { query: text }, MOCK_REPLY);
      const aMsg: Msg = { id:uid(), role:"assistant", text:(res as typeof MOCK_REPLY).text, model:(res as typeof MOCK_REPLY).model_used, ts:Date.now(), tool_calls:(res as typeof MOCK_REPLY).tool_calls };
      setMsgs(p => [...p, aMsg]);
    } finally { setThinking(false); }
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(input); }
  };

  const searchMemory = useCallback(async (q: string) => {
    const res = await tauriInvoke<MemEntry[]>("search_memory", { query: q }, MOCK_MEMORIES.filter(m => m.text.toLowerCase().includes(q.toLowerCase())));
    setMemories(res);
  }, []);

  useEffect(() => { tauriInvoke<Record<string,ModelInfo>>("get_model_status",{},MOCK_MODELS).then(setModels); }, []);
  useEffect(() => { tauriInvoke<ToolRow[]>("get_tool_history",{},MOCK_TOOLS).then(setTools); }, []);

  const tierColor = (t: string) => t==="lightweight"?"#22c55e":t==="medium"?"#f59e0b":"#a78bfa";
  const providerIcon = (p: string) => p==="ollama"?"⬡":"✦";

  return (
    <div style={S.root}>
      {/* Sidebar */}
      <nav style={S.sidebar}>
        <div style={S.logo}>
          <div style={S.logoOrb} />
          <span style={S.logoText}>Vani</span>
        </div>

        {(["chat","memory","tools","models"] as View[]).map(v => (
          <button key={v} onClick={() => setView(v)} style={{ ...S.navBtn, ...(view===v ? S.navBtnActive : {}) }}>
            <span style={S.navIcon}>{v==="chat"?"◎":v==="memory"?"⬡":v==="tools"?"⚙":v==="models"?"⬟":""}</span>
            <span style={S.navLabel}>{v}</span>
          </button>
        ))}

        <div style={S.sidebarBottom}>
          <div style={{ ...S.voicePill, background: voiceMode==="primary" ? "rgba(34,197,94,0.15)" : "rgba(245,158,11,0.15)" }}>
            <div style={{ ...S.voiceDot, background: voiceMode==="primary" ? "#22c55e" : "#f59e0b" }} />
            <span style={{ color: voiceMode==="primary" ? "#22c55e" : "#f59e0b", fontSize:11 }}>
              {voiceMode==="primary" ? "LiveKit" : "Whisper"}
            </span>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main style={S.main}>

        {/* ── CHAT VIEW ── */}
        {view === "chat" && (
          <div style={S.chatWrap}>
            <div style={S.msgList}>
              {msgs.map(m => (
                <div key={m.id} style={{ ...S.msgRow, justifyContent: m.role==="user" ? "flex-end" : "flex-start" }}>
                  {m.role === "assistant" && <div style={S.avatar}>V</div>}
                  <div style={{ maxWidth:"72%" }}>
                    <div style={{ ...S.bubble, ...(m.role==="user" ? S.bubbleUser : S.bubbleBot) }}>
                      {m.text}
                    </div>
                    {m.tool_calls && m.tool_calls.length > 0 && (
                      <div style={S.toolCallRow}>
                        {m.tool_calls.map((tc,i) => (
                          <span key={i} style={{ ...S.toolTag, color: tc.success ? "#22c55e" : "#f87171" }}>
                            {tc.success ? "✓" : "✗"} {tc.name} {tc.duration_ms}ms
                          </span>
                        ))}
                      </div>
                    )}
                    {m.model && <div style={S.msgMeta}>via {m.model}</div>}
                  </div>
                </div>
              ))}
              {thinking && (
                <div style={{ ...S.msgRow, justifyContent:"flex-start" }}>
                  <div style={S.avatar}>V</div>
                  <div style={{ ...S.bubble, ...S.bubbleBot }}>
                    <span style={S.dots}><span>.</span><span>.</span><span>.</span></span>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            {/* Input bar */}
            <div style={S.inputBar}>
              <button
                style={{ ...S.micBtn, ...(listening ? S.micActive : {}) }}
                onClick={() => setListening(l => !l)}
                title="Push to talk"
              >
                {listening ? "■" : "●"}
              </button>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type or speak to Vani…"
                rows={1}
                style={S.textarea}
              />
              <button style={S.sendBtn} onClick={() => sendMsg(input)} disabled={!input.trim()}>
                ↑
              </button>
            </div>
          </div>
        )}

        {/* ── MEMORY VIEW ── */}
        {view === "memory" && (
          <div style={S.panelWrap}>
            <div style={S.panelHeader}>
              <h1 style={S.panelTitle}>Semantic Memory</h1>
              <div style={S.statRow}>
                <div style={S.statCard}><div style={S.statNum}>{memStats.semantic_memories}</div><div style={S.statLabel}>memories</div></div>
                <div style={S.statCard}><div style={S.statNum}>{memStats.working_entries}</div><div style={S.statLabel}>in session</div></div>
              </div>
            </div>
            <div style={S.searchRow}>
              <input
                value={memSearch}
                onChange={e => setMemSearch(e.target.value)}
                onKeyDown={e => e.key==="Enter" && searchMemory(memSearch)}
                placeholder="Search memories semantically…"
                style={S.searchInput}
              />
              <button style={S.searchBtn} onClick={() => searchMemory(memSearch)}>Search</button>
            </div>
            <div style={S.memList}>
              {memories.map(m => (
                <div key={m.id} style={S.memCard}>
                  <div style={S.memCardTop}>
                    <span style={S.memSource}>{m.source}</span>
                    {m.score && <span style={S.memScore}>{(m.score*100).toFixed(0)}% match</span>}
                    <span style={S.memTime}>{relTime(m.ts)}</span>
                  </div>
                  <p style={S.memText}>{m.text}</p>
                  <div style={S.tagRow}>
                    {m.tags.map(t => <span key={t} style={S.tag}>{t}</span>)}
                    {m.importance > 1.5 && <span style={{ ...S.tag, background:"rgba(167,139,250,0.15)", color:"#a78bfa" }}>★ important</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── TOOLS VIEW ── */}
        {view === "tools" && (
          <div style={S.panelWrap}>
            <div style={S.panelHeader}>
              <h1 style={S.panelTitle}>Tool Audit</h1>
              <div style={S.statRow}>
                <div style={S.statCard}><div style={S.statNum}>{tools.filter(t=>t.success).length}</div><div style={S.statLabel}>succeeded</div></div>
                <div style={S.statCard}><div style={S.statNum}>{tools.filter(t=>!t.success).length}</div><div style={S.statLabel}>failed</div></div>
                <div style={S.statCard}><div style={{ ...S.statNum, color:"#22c55e" }}>{Math.round(tools.filter(t=>t.success).length/tools.length*100)}%</div><div style={S.statLabel}>success rate</div></div>
              </div>
            </div>
            <table style={S.table}>
              <thead>
                <tr style={S.thead}>
                  <th style={S.th}>Tool</th>
                  <th style={S.th}>Status</th>
                  <th style={S.th}>Duration</th>
                  <th style={S.th}>When</th>
                </tr>
              </thead>
              <tbody>
                {tools.map(r => (
                  <tr key={r.id} style={S.tr}>
                    <td style={S.td}><span style={S.toolName}>{r.tool_name}</span></td>
                    <td style={S.td}>
                      <span style={{ ...S.statusBadge, background: r.success ? "rgba(34,197,94,0.12)" : "rgba(248,113,113,0.12)", color: r.success ? "#22c55e" : "#f87171" }}>
                        {r.success ? "✓ ok" : `✗ ${r.error_msg?.split(" ")[0] ?? "err"}`}
                      </span>
                    </td>
                    <td style={{ ...S.td, color: r.duration_ms > 5000 ? "#f59e0b" : "var(--fg-muted)", fontVariantNumeric:"tabular-nums" }}>
                      {r.duration_ms >= 1000 ? `${(r.duration_ms/1000).toFixed(1)}s` : `${r.duration_ms}ms`}
                    </td>
                    <td style={{ ...S.td, color:"var(--fg-muted)", fontSize:12 }}>{relTime(r.ts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ── MODELS VIEW ── */}
        {view === "models" && (
          <div style={S.panelWrap}>
            <div style={S.panelHeader}>
              <h1 style={S.panelTitle}>Model Router</h1>
              <div style={S.statRow}>
                {(["lightweight","medium","heavy"] as const).map(tier => {
                  const ms = Object.values(models).filter(m => m.tier===tier);
                  const healthy = ms.filter(m => m.healthy).length;
                  return (
                    <div key={tier} style={S.statCard}>
                      <div style={{ ...S.statNum, color: tierColor(tier) }}>{healthy}/{ms.length}</div>
                      <div style={S.statLabel}>{tier}</div>
                    </div>
                  );
                })}
              </div>
            </div>
            <div style={S.modelGrid}>
              {Object.entries(models).map(([id, m]) => (
                <div key={id} style={{ ...S.modelCard, opacity: m.healthy ? 1 : 0.5 }}>
                  <div style={S.modelCardTop}>
                    <span style={{ fontSize:18 }}>{providerIcon(m.provider)}</span>
                    <div style={{ ...S.healthDot, background: m.healthy ? "#22c55e" : "#f87171" }} />
                  </div>
                  <div style={S.modelId}>{id}</div>
                  <div style={S.modelMeta}>
                    <span style={{ ...S.tierBadge, color: tierColor(m.tier), background: tierColor(m.tier)+"22" }}>{m.tier}</span>
                    <span style={S.providerLabel}>{m.provider}</span>
                  </div>
                  <div style={{ ...S.healthLabel, color: m.healthy ? "#22c55e" : "#f87171" }}>
                    {m.healthy ? "healthy" : "offline"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Sora:wght@300;400;500;600&display=swap');
        * { box-sizing:border-box; margin:0; padding:0; }
        body { background:#0a0a0f; font-family:'Sora',sans-serif; color:#e8e8f0; }
        ::-webkit-scrollbar { width:4px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:#2a2a3a; border-radius:4px; }
        @keyframes blink { 0%,100%{opacity:0.2} 50%{opacity:1} }
        @keyframes pulse { 0%,100%{box-shadow:0 0 0 0 rgba(167,139,250,0.4)} 50%{box-shadow:0 0 0 8px rgba(167,139,250,0)} }
        @keyframes orb { 0%,100%{transform:scale(1)} 50%{transform:scale(1.08)} }
        .dots span:nth-child(1){animation:blink 1.2s .0s infinite}
        .dots span:nth-child(2){animation:blink 1.2s .2s infinite}
        .dots span:nth-child(3){animation:blink 1.2s .4s infinite}
      `}</style>
    </div>
  );
}

/* ── Styles ─────────────────────────────────────────────────────────────── */
const S: Record<string, React.CSSProperties> = {
  root: { display:"flex", height:"100vh", overflow:"hidden", background:"#0a0a0f", fontFamily:"'Sora',sans-serif" },

  /* Sidebar */
  sidebar: { width:200, minWidth:200, background:"#0d0d16", borderRight:"1px solid rgba(255,255,255,0.06)", display:"flex", flexDirection:"column", padding:"20px 12px", gap:4 },
  logo: { display:"flex", alignItems:"center", gap:10, marginBottom:24, paddingLeft:8 },
  logoOrb: { width:28, height:28, borderRadius:"50%", background:"linear-gradient(135deg,#a78bfa,#6d28d9)", animation:"orb 3s ease-in-out infinite" },
  logoText: { fontSize:18, fontWeight:600, letterSpacing:-0.5, color:"#e8e8f0" },
  navBtn: { display:"flex", alignItems:"center", gap:10, padding:"9px 12px", borderRadius:8, border:"none", background:"transparent", color:"rgba(232,232,240,0.45)", cursor:"pointer", fontSize:13, fontWeight:400, fontFamily:"'Sora',sans-serif", transition:"all 0.15s", textTransform:"capitalize" },
  navBtnActive: { background:"rgba(167,139,250,0.12)", color:"#c4b5fd" },
  navIcon: { fontSize:16, width:20, textAlign:"center" as const },
  navLabel: { flex:1, textAlign:"left" as const },
  sidebarBottom: { marginTop:"auto", paddingTop:16 },
  voicePill: { display:"flex", alignItems:"center", gap:6, padding:"6px 10px", borderRadius:20 },
  voiceDot: { width:6, height:6, borderRadius:"50%" },

  /* Main */
  main: { flex:1, display:"flex", flexDirection:"column", overflow:"hidden" },

  /* Chat */
  chatWrap: { flex:1, display:"flex", flexDirection:"column", overflow:"hidden" },
  msgList: { flex:1, overflowY:"auto" as const, padding:"24px 28px", display:"flex", flexDirection:"column", gap:16 },
  msgRow: { display:"flex", alignItems:"flex-end", gap:10 },
  avatar: { width:32, height:32, minWidth:32, borderRadius:"50%", background:"linear-gradient(135deg,#a78bfa,#6d28d9)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, fontWeight:600, color:"#fff" },
  bubble: { padding:"12px 16px", borderRadius:16, fontSize:14, lineHeight:1.65, fontFamily:"'Sora',sans-serif" },
  bubbleUser: { background:"#a78bfa", color:"#fff", borderBottomRightRadius:4 },
  bubbleBot: { background:"#16161f", border:"1px solid rgba(255,255,255,0.07)", color:"#e8e8f0", borderBottomLeftRadius:4 },
  toolCallRow: { display:"flex", flexWrap:"wrap" as const, gap:4, marginTop:6 },
  toolTag: { fontSize:11, fontFamily:"'JetBrains Mono',monospace", padding:"2px 7px", background:"rgba(255,255,255,0.05)", borderRadius:4 },
  msgMeta: { fontSize:11, color:"rgba(232,232,240,0.3)", marginTop:4, paddingLeft:4 },
  dots: { display:"inline-flex", gap:2, fontSize:20 },

  /* Input */
  inputBar: { display:"flex", alignItems:"flex-end", gap:8, padding:"16px 20px", borderTop:"1px solid rgba(255,255,255,0.06)", background:"#0d0d16" },
  micBtn: { width:40, height:40, minWidth:40, borderRadius:"50%", border:"1px solid rgba(255,255,255,0.1)", background:"rgba(255,255,255,0.04)", color:"rgba(232,232,240,0.6)", cursor:"pointer", fontSize:14, display:"flex", alignItems:"center", justifyContent:"center", transition:"all 0.15s" },
  micActive: { background:"rgba(167,139,250,0.25)", borderColor:"#a78bfa", color:"#a78bfa", animation:"pulse 1.5s infinite" },
  textarea: { flex:1, background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:12, padding:"10px 14px", color:"#e8e8f0", fontSize:14, fontFamily:"'Sora',sans-serif", resize:"none" as const, outline:"none", lineHeight:1.5 },
  sendBtn: { width:40, height:40, minWidth:40, borderRadius:"50%", border:"none", background:"#7c3aed", color:"#fff", cursor:"pointer", fontSize:18, display:"flex", alignItems:"center", justifyContent:"center", transition:"opacity 0.15s" },

  /* Panel shared */
  panelWrap: { flex:1, overflow:"auto", padding:"28px 32px", display:"flex", flexDirection:"column", gap:20 },
  panelHeader: { display:"flex", flexDirection:"column", gap:16 },
  panelTitle: { fontSize:22, fontWeight:600, letterSpacing:-0.5, color:"#e8e8f0" },
  statRow: { display:"flex", gap:12 },
  statCard: { background:"#16161f", border:"1px solid rgba(255,255,255,0.07)", borderRadius:10, padding:"12px 20px", textAlign:"center" as const },
  statNum: { fontSize:24, fontWeight:600, color:"#c4b5fd", lineHeight:1 },
  statLabel: { fontSize:11, color:"rgba(232,232,240,0.4)", marginTop:4, textTransform:"uppercase" as const, letterSpacing:0.5 },

  /* Memory */
  searchRow: { display:"flex", gap:8 },
  searchInput: { flex:1, background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:8, padding:"9px 14px", color:"#e8e8f0", fontSize:14, fontFamily:"'Sora',sans-serif", outline:"none" },
  searchBtn: { padding:"0 20px", background:"#7c3aed", border:"none", borderRadius:8, color:"#fff", fontSize:13, fontWeight:500, cursor:"pointer", fontFamily:"'Sora',sans-serif" },
  memList: { display:"flex", flexDirection:"column", gap:10 },
  memCard: { background:"#16161f", border:"1px solid rgba(255,255,255,0.07)", borderRadius:12, padding:"14px 16px", display:"flex", flexDirection:"column", gap:8 },
  memCardTop: { display:"flex", alignItems:"center", gap:8 },
  memSource: { fontSize:11, padding:"2px 8px", background:"rgba(167,139,250,0.12)", color:"#a78bfa", borderRadius:4, textTransform:"uppercase" as const, letterSpacing:0.5 },
  memScore: { fontSize:11, color:"#22c55e", marginLeft:"auto" },
  memTime: { fontSize:11, color:"rgba(232,232,240,0.35)" },
  memText: { fontSize:14, color:"#d4d4e0", lineHeight:1.6 },
  tagRow: { display:"flex", flexWrap:"wrap" as const, gap:5 },
  tag: { fontSize:11, padding:"2px 8px", background:"rgba(255,255,255,0.06)", color:"rgba(232,232,240,0.5)", borderRadius:4 },

  /* Tools table */
  table: { width:"100%", borderCollapse:"collapse" as const, fontSize:13 },
  thead: { borderBottom:"1px solid rgba(255,255,255,0.08)" },
  th: { padding:"8px 12px", textAlign:"left" as const, fontSize:11, textTransform:"uppercase" as const, letterSpacing:0.5, color:"rgba(232,232,240,0.35)", fontWeight:500 },
  tr: { borderBottom:"1px solid rgba(255,255,255,0.04)" },
  td: { padding:"10px 12px", color:"#d4d4e0" },
  toolName: { fontFamily:"'JetBrains Mono',monospace", fontSize:12, color:"#c4b5fd" },
  statusBadge: { fontSize:11, padding:"3px 8px", borderRadius:4, fontFamily:"'JetBrains Mono',monospace" },

  /* Models */
  modelGrid: { display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(160px,1fr))", gap:12 },
  modelCard: { background:"#16161f", border:"1px solid rgba(255,255,255,0.07)", borderRadius:12, padding:"16px", display:"flex", flexDirection:"column", gap:8, transition:"opacity 0.2s" },
  modelCardTop: { display:"flex", alignItems:"center", justifyContent:"space-between" },
  healthDot: { width:8, height:8, borderRadius:"50%" },
  modelId: { fontSize:13, fontWeight:500, fontFamily:"'JetBrains Mono',monospace", color:"#e8e8f0", lineHeight:1.3 },
  modelMeta: { display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" as const },
  tierBadge: { fontSize:10, padding:"2px 7px", borderRadius:4, fontWeight:500 },
  providerLabel: { fontSize:11, color:"rgba(232,232,240,0.35)" },
  healthLabel: { fontSize:11, fontWeight:500 },
};
