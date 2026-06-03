"""
vani/plugins/builtin/whiteboard_plugin.py

Whiteboard Plugin — Vani opens an interactive whiteboard in the browser.

What it does:
  • Opens a full-featured HTML5 canvas whiteboard
  • Vani can pre-draw concept sketches based on conversation
  • Supports: freehand draw, shapes, text, erase, save as PNG
  • Works like a collaborative Paint / Excalidraw

Triggers: "whiteboard", "paint karo", "draw", "sketch"
"""

from __future__ import annotations
import os
import subprocess
import sys
import logging
from datetime import datetime
from pathlib import Path

from vani.plugins.registry import VaniPlugin, PluginResult, PluginContext

logger = logging.getLogger("vani.plugins.whiteboard")


class WhiteboardPlugin(VaniPlugin):
    name = "whiteboard"
    icon = "🎨"
    description = "Opens an interactive whiteboard in your browser for visual explanations."
    category = "visual"
    enabled = False
    triggers = [
        "whiteboard", "paint karo", "draw karo", "sketch karo",
        "drawing board", "canvas kholo", "sketchpad", "paint",
        "draw something", "let me draw", "whiteboard kholo",
        "excalidraw", "drawing", "board pe likhte hain",
    ]

    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        html = self._build_whiteboard()

        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)
        now = datetime.now().strftime("%d%b%Y_%H%M")
        filename = f"Vani_Whiteboard_{now}.html"
        filepath = desktop / filename
        filepath.write_text(html, encoding="utf-8")

        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(filepath)])
            elif sys.platform == "win32":
                os.startfile(str(filepath))
            else:
                subprocess.Popen(["xdg-open", str(filepath)])
        except Exception:
            pass

        return PluginResult(
            success=True,
            message="🎨 Whiteboard ready! Browser mein khul gaya — ab draw karo!",
            artifact_path=str(filepath),
            artifact_type="html",
            ui_payload={"filename": filename}
        )

    def _build_whiteboard(self) -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vani Whiteboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&display=swap');
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0a1e; font-family: 'Space Grotesk', sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
  
  .toolbar {
    background: rgba(255,255,255,0.04);
    border-bottom: 1px solid rgba(196,126,255,0.15);
    padding: 0.5rem 1rem;
    display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;
  }
  .brand {
    font-weight: 700; font-size: 1rem;
    background: linear-gradient(135deg, #c47eff, #818cf8);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-right: 0.5rem;
  }
  .sep { width: 1px; height: 28px; background: rgba(196,126,255,0.2); }
  
  .tool-btn {
    background: transparent;
    border: 1px solid rgba(196,126,255,0.2);
    color: #94a3b8; border-radius: 0.5rem;
    padding: 0.35rem 0.75rem; cursor: pointer;
    font-size: 0.85rem; font-family: inherit;
    transition: all 0.15s; display: flex; align-items: center; gap: 0.3rem;
  }
  .tool-btn:hover, .tool-btn.active {
    background: rgba(124,58,237,0.3);
    border-color: #c47eff; color: #c47eff;
  }
  
  .color-swatch {
    width: 24px; height: 24px; border-radius: 50%;
    border: 2px solid transparent; cursor: pointer;
    transition: transform 0.15s, border-color 0.15s;
  }
  .color-swatch:hover, .color-swatch.active { transform: scale(1.25); border-color: white; }
  
  input[type=range] { accent-color: #7c3aed; width: 80px; cursor: pointer; }
  input[type=color] { width: 32px; height: 32px; border: none; border-radius: 50%; cursor: pointer; background: none; padding: 0; }
  
  #canvas-wrap {
    flex: 1; display: flex; justify-content: center; align-items: center;
    padding: 1rem; overflow: hidden;
  }
  #canvas {
    background: #ffffff;
    border-radius: 1rem;
    box-shadow: 0 0 60px rgba(124,58,237,0.3), 0 0 120px rgba(124,58,237,0.1);
    cursor: crosshair;
    max-width: 100%; max-height: 100%;
  }
  
  label { color: #64748b; font-size: 0.8rem; }
</style>
</head>
<body>
<div class="toolbar">
  <span class="brand">🎨 Vani Whiteboard</span>
  <div class="sep"></div>
  
  <!-- Tools -->
  <button class="tool-btn active" id="btn-pen" onclick="setTool('pen')">✏️ Pen</button>
  <button class="tool-btn" id="btn-line" onclick="setTool('line')">📏 Line</button>
  <button class="tool-btn" id="btn-rect" onclick="setTool('rect')">▭ Rect</button>
  <button class="tool-btn" id="btn-circle" onclick="setTool('circle')">⬤ Circle</button>
  <button class="tool-btn" id="btn-text" onclick="setTool('text')">T Text</button>
  <button class="tool-btn" id="btn-eraser" onclick="setTool('eraser')">🧹 Erase</button>
  
  <div class="sep"></div>
  
  <!-- Colors -->
  <div class="color-swatch active" style="background:#1e293b" onclick="setColor('#1e293b')" title="Dark"></div>
  <div class="color-swatch" style="background:#ef4444" onclick="setColor('#ef4444')" title="Red"></div>
  <div class="color-swatch" style="background:#3b82f6" onclick="setColor('#3b82f6')" title="Blue"></div>
  <div class="color-swatch" style="background:#22c55e" onclick="setColor('#22c55e')" title="Green"></div>
  <div class="color-swatch" style="background:#f59e0b" onclick="setColor('#f59e0b')" title="Yellow"></div>
  <div class="color-swatch" style="background:#8b5cf6" onclick="setColor('#8b5cf6')" title="Purple"></div>
  <div class="color-swatch" style="background:#ec4899" onclick="setColor('#ec4899')" title="Pink"></div>
  <input type="color" id="custom-color" value="#1e293b" onchange="setColor(this.value)" title="Custom color">
  
  <div class="sep"></div>
  
  <label>Size</label>
  <input type="range" id="size-slider" min="1" max="40" value="3" oninput="setSize(this.value)">
  <span id="size-label" style="color:#64748b;font-size:0.8rem;min-width:20px">3</span>
  
  <div class="sep"></div>
  
  <button class="tool-btn" onclick="undo()">↩️ Undo</button>
  <button class="tool-btn" onclick="clearCanvas()">🗑️ Clear</button>
  <button class="tool-btn" onclick="saveCanvas()">💾 Save PNG</button>
</div>

<div id="canvas-wrap">
  <canvas id="canvas"></canvas>
</div>

<script>
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const wrap = document.getElementById('canvas-wrap');

let tool = 'pen';
let color = '#1e293b';
let size = 3;
let drawing = false;
let startX, startY;
let history = [];
let snapshot;

function resize() {
  const s = Math.min(wrap.clientWidth - 32, wrap.clientHeight - 32, 1200);
  const h = Math.min(wrap.clientHeight - 32, 800);
  canvas.width = s;
  canvas.height = h;
  redraw();
}

function saveSnapshot() {
  history.push(ctx.getImageData(0, 0, canvas.width, canvas.height));
  if (history.length > 50) history.shift();
}

function redraw() {
  if (history.length) {
    try { ctx.putImageData(history[history.length - 1], 0, 0); } catch(e) {}
  }
}

function undo() {
  if (history.length > 1) {
    history.pop();
    ctx.putImageData(history[history.length - 1], 0, 0);
  } else if (history.length === 1) {
    history.pop();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

function setTool(t) {
  tool = t;
  document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + t)?.classList.add('active');
  canvas.style.cursor = t === 'eraser' ? 'cell' : t === 'text' ? 'text' : 'crosshair';
}

function setColor(c) {
  color = c;
  document.getElementById('custom-color').value = c;
  document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
}

function setSize(v) {
  size = parseInt(v);
  document.getElementById('size-label').textContent = v;
}

function getPos(e) {
  const r = canvas.getBoundingClientRect();
  const t = e.touches ? e.touches[0] : e;
  return [t.clientX - r.left, t.clientY - r.top];
}

canvas.addEventListener('mousedown', start);
canvas.addEventListener('mousemove', move);
canvas.addEventListener('mouseup', end);
canvas.addEventListener('touchstart', e => { e.preventDefault(); start(e); }, {passive:false});
canvas.addEventListener('touchmove',  e => { e.preventDefault(); move(e); },  {passive:false});
canvas.addEventListener('touchend',   e => { e.preventDefault(); end(e); },   {passive:false});

function start(e) {
  [startX, startY] = getPos(e);
  drawing = true;
  saveSnapshot();
  if (tool === 'pen' || tool === 'eraser') {
    ctx.beginPath();
    ctx.moveTo(startX, startY);
  }
  if (tool === 'text') {
    const txt = prompt('Enter text:');
    if (txt) {
      ctx.fillStyle = color;
      ctx.font = `${Math.max(size * 5, 14)}px Space Grotesk, sans-serif`;
      ctx.fillText(txt, startX, startY);
    }
    drawing = false;
  }
}

function move(e) {
  if (!drawing) return;
  const [x, y] = getPos(e);
  if (tool === 'pen') {
    ctx.strokeStyle = color; ctx.lineWidth = size;
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.lineTo(x, y); ctx.stroke();
  } else if (tool === 'eraser') {
    ctx.strokeStyle = '#ffffff'; ctx.lineWidth = size * 4;
    ctx.lineCap = 'round';
    ctx.lineTo(x, y); ctx.stroke();
  } else {
    // Preview shapes
    ctx.putImageData(history[history.length - 1], 0, 0);
    ctx.strokeStyle = color; ctx.lineWidth = size;
    ctx.fillStyle = 'transparent';
    if (tool === 'line') {
      ctx.beginPath(); ctx.moveTo(startX, startY); ctx.lineTo(x, y); ctx.stroke();
    } else if (tool === 'rect') {
      ctx.strokeRect(startX, startY, x - startX, y - startY);
    } else if (tool === 'circle') {
      const r = Math.hypot(x - startX, y - startY);
      ctx.beginPath(); ctx.arc(startX, startY, r, 0, Math.PI * 2); ctx.stroke();
    }
  }
}

function end() { drawing = false; }

function clearCanvas() {
  if (confirm('Clear the whiteboard?')) {
    saveSnapshot();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

function saveCanvas() {
  const a = document.createElement('a');
  a.download = `Vani_Whiteboard_${new Date().toLocaleDateString('en-GB').replace(/\//g,'-')}.png`;
  a.href = canvas.toDataURL('image/png');
  a.click();
}

window.addEventListener('resize', resize);
resize();
saveSnapshot(); // initial blank state
</script>
</body>
</html>"""
