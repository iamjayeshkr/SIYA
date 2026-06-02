import os
from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 14)
        self.cell(0, 10, 'Vani Application Audit Report', ln=1, align='C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 10)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

def generate_audit(pdf_path: str):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Helvetica', '', 12)
    # Sections
    sections = [
        ('Identified Bugs', [
            "1. Syntax/Indentation error in `whatsapp_call` causing import failure.",
            "2. Model name mismatch – using non‑existent Gemini model causing runtime crashes.",
            "3. Deprecated `preemptive_generation` argument in AgentSession causing TypeError.",
            "4. Infinite blocking loop in `memory_loop.run()` leading to shutdown hangs.",
            "5. App launching fallback using `open -a` fails for web apps like YouTube.",
            "6. Media intent classifier over‑captures simple play commands, blocking proper search/play behavior.",
            "7. Heavy top‑level imports (pyautogui, sounddevice, Telethon, Playwright) inflating startup latency.",
            "8. Missing graceful handling when `vani_messaging` module is unavailable.",
        ]),
        ('Implemented Latency Optimizations', [
            "- Moved heavy imports into lazy dynamic imports inside each `@tool` wrapper.",
            "- Added warm‑import timing tests confirming import time ~0.13 s after LiveKit pre‑load.",
            "- Refactored `whatsapp_call` to restore missing logic and fix indentation.",
            "- Modularized prompt files into `modes/` directory for on‑demand loading.",
            "- Delegated `open_application` to `open_app_smart` for robust web‑app handling.",
            "- Implemented async task queue with non‑blocking `asyncio.Queue` for Qwen background worker.",
            "- Added graceful fallback for optional modules (learning_memory, vani_name_pronunciation, etc.).",
        ]),
        ('Further Optimization Recommendations', [
            "1. Cache heavy imports after first lazy load using `functools.lru_cache` to avoid repeat import overhead.",
            "2. Profile `vani_reasoning.py` with `cProfile` to locate any remaining hot paths.",
            "3. Reduce memory footprint by limiting stored conversation history size in `ContextCache`.",
            "4. Use compiled binary wheels for `pynput` and `PyAutoGUI` to speed up import time.",
            "5. Pre‑warm the LiveKit connection asynchronously before user interaction to hide latency.",
            "6. Enable HTTP/2 for OpenWeather API calls and add response caching (TTL 10 min).",
            "7. Consolidate repeated OS‑level subprocess calls (e.g., Chrome launch) into a reusable helper.",
            "8. Consider using a background thread pool for CPU‑heavy tasks like image processing.",
            "9. Evaluate moving static assets to a CDN and serve them via HTTP range requests for faster streaming.",
            "10. Implement a watchdog to auto‑restart the LiveKit worker on unexpected crashes.",
        ])
    ]
    for title, bullets in sections:
        pdf.set_font('Helvetica', 'B', 13)
        pdf.cell(0, 10, title, ln=1)
        pdf.set_font('Helvetica', '', 12)
        for bullet in bullets:
            pdf.multi_cell(0, 8, f'- {bullet}')
        pdf.ln(4)
    pdf.output(pdf_path)

if __name__ == '__main__':
    output_path = os.path.join(os.path.dirname(__file__), 'audit.pdf')
    generate_audit(output_path)
    print(f'Audit PDF generated at {output_path}')
