from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

OUTPUT = "/mnt/user-data/outputs/Vanni_Interview_Questions.pdf"

doc = SimpleDocTemplate(
    OUTPUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm, bottomMargin=2*cm,
    title="Vanni Codebase – Interview Questions",
    author="Claude AI Analysis"
)
W = A4[0] - 4*cm

DARK   = colors.HexColor("#1a1a2e")
ACCENT = colors.HexColor("#e94560")
LIGHT  = colors.HexColor("#f5f5f5")
MUTED  = colors.HexColor("#555577")

styles = getSampleStyleSheet()

section_style = ParagraphStyle("Section", fontName="Helvetica-Bold",
    fontSize=15, textColor=colors.white, spaceAfter=0, spaceBefore=18, leading=22)
section_sub = ParagraphStyle("SecSub", fontName="Helvetica",
    fontSize=9, textColor=colors.HexColor("#aabbcc"), spaceAfter=0)

q_style = ParagraphStyle("Q", fontName="Helvetica-Bold",
    fontSize=11, textColor=DARK, spaceBefore=10, spaceAfter=2, leading=16, leftIndent=12)
hint_style = ParagraphStyle("Hint", fontName="Helvetica",
    fontSize=9.5, textColor=colors.HexColor("#222244"),
    spaceAfter=8, leading=15, leftIndent=20,
    backColor=colors.HexColor("#f0f4ff"),
    borderPadding=(6, 8, 6, 8))
toc_cat = ParagraphStyle("TocCat", fontName="Helvetica-Bold",
    fontSize=10, textColor=DARK, spaceBefore=4, leftIndent=12)

def section_block(title, subtitle=""):
    data = [[Paragraph(title, section_style)],
            [Paragraph(subtitle, section_sub) if subtitle else Paragraph("", section_sub)]]
    t = Table(data, colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), DARK),
        ("TOPPADDING",  (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING", (0,0), (-1,-1), 14),
        ("RIGHTPADDING", (0,0), (-1,-1), 14),
    ]))
    return t

def q_block(num, text, hint=None, diff=None):
    items = []
    if diff:
        colour = '2ecc71' if diff=='Easy' else ('f39c12' if diff=='Medium' else 'e74c3c')
        full_text = f"Q{num}.  <font color='#{colour}'>[{diff}]</font>  {text}"
    else:
        full_text = f"Q{num}.  {text}"
    items.append(Paragraph(full_text, q_style))
    if hint:
        items.append(Paragraph(hint, hint_style))
    return KeepTogether(items)

story = []

# ── COVER ──
story.append(Spacer(1, 2.5*cm))
cover_hero = Table([
    [Paragraph("VANNI", ParagraphStyle("CoverTitle", fontName="Helvetica-Bold",
        fontSize=56, textColor=ACCENT, alignment=TA_CENTER, leading=64))],
    [Spacer(1, 0.15*cm)],
    [Paragraph("Personal AI Assistant", ParagraphStyle("CoverSub",
        fontName="Helvetica", fontSize=16, textColor=DARK, alignment=TA_CENTER, leading=22))],
    [Spacer(1, 0.25*cm)],
    [HRFlowable(width=W*0.7, thickness=2, color=ACCENT)],
    [Spacer(1, 0.25*cm)],
    [Paragraph("Complete Interview Question Bank", ParagraphStyle("CoverSub2",
        fontName="Helvetica-Bold", fontSize=18, textColor=DARK, alignment=TA_CENTER, leading=24))],
    [Spacer(1, 0.3*cm)],
    [Paragraph("Codebase ka full analysis · 100+ questions · 12 technical domains · Deep Hinglish answers",
        ParagraphStyle("CoverMeta", fontName="Helvetica", fontSize=10, textColor=MUTED,
            alignment=TA_CENTER, leading=15))],
], colWidths=[W])
cover_hero.setStyle(TableStyle([
    ("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
    ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
]))
story.append(cover_hero)
story.append(Spacer(1, 1.5*cm))

stats = Table([[
    Table([[Paragraph("100+", ParagraphStyle("Stat", fontName="Helvetica-Bold", fontSize=24, textColor=ACCENT, alignment=TA_CENTER))],
           [Paragraph("Questions", ParagraphStyle("StatL", fontName="Helvetica", fontSize=9, textColor=MUTED, alignment=TA_CENTER))]], colWidths=[4*cm]),
    Table([[Paragraph("12", ParagraphStyle("Stat", fontName="Helvetica-Bold", fontSize=24, textColor=ACCENT, alignment=TA_CENTER))],
           [Paragraph("Topic Areas", ParagraphStyle("StatL", fontName="Helvetica", fontSize=9, textColor=MUTED, alignment=TA_CENTER))]], colWidths=[4*cm]),
    Table([[Paragraph("3", ParagraphStyle("Stat", fontName="Helvetica-Bold", fontSize=24, textColor=ACCENT, alignment=TA_CENTER))],
           [Paragraph("Difficulty Levels", ParagraphStyle("StatL", fontName="Helvetica", fontSize=9, textColor=MUTED, alignment=TA_CENTER))]], colWidths=[4*cm]),
]], colWidths=[W/3]*3)
stats.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,-1),LIGHT),
    ("TOPPADDING",(0,0),(-1,-1),14),("BOTTOMPADDING",(0,0),(-1,-1),14),
]))
story.append(stats)
story.append(Spacer(1,1.5*cm))

domains = [
    ("1","Python & Async"),("2","Architecture & Design"),("3","Voice & Wake Detection"),
    ("4","Speaker Verification"),("5","Intent Routing"),("6","Memory & Storage"),
    ("7","Messaging & Social"),("8","LLM & Ollama"),("9","Security"),
    ("10","Performance"),("11","Testing"),("12","System Design"),
]
drows = [[Paragraph(f"{d[0]}. {d[1]}", toc_cat) for d in domains[i:i+3]] for i in range(0,12,3)]
dtable = Table(drows, colWidths=[W/3]*3)
dtable.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
story.append(dtable)
story.append(PageBreak())

# All questions data
ALL_SECTIONS = []

# SECTION 1
ALL_SECTIONS.append(("1. Python & Asyncio Fundamentals", "Core language patterns used throughout the codebase", [
(1,"What is the difference between asyncio.Queue and the custom LatestWinsQueue in worker.py? Why was it introduced?",
"Samjho aise: asyncio.Queue ek LINE hai — pehle aaya, pehle execute hoga (FIFO). Agar user ne 5 commands diye aur Vani busy thi, toh woh SAARE 5 execute honge queue se — ek ke baad ek. Yeh bahut bura UX hai.\n\nLatestWinsQueue ne yeh problem solve ki LAST-WRITE-WINS se: jab naya command aata hai, purana wala CANCEL ho jaata hai aur sirf NAYI instruction execute hoti hai. Jaise elevator mein — agar tune 3rd floor press kiya aur phir 7th floor press kiya, elevator seedha 7 jaayega, 3 pe rukne ka koi matlab nahi.\n\nCode mein: put_nowait() purane future ko STALE sentinel se resolve karta hai, active task cancel karta hai, aur nayi instruction store karta hai.","Medium"),

(2,"Explain put_nowait() in LatestWinsQueue. What 3 things does it do?",
"put_nowait() ek hi call mein teen kaam karta hai:\n\n1. STALE SENTINEL: Agar koi purana pending future hai, usko future.set_result(STALE) se resolve karta hai. Matlab woh future ke caller ko pata chal jaata hai ki 'tera kaam cancel ho gaya, naya aaya hai'.\n\n2. ACTIVE TASK CANCEL: Agar currently koi tool chal raha hai (Ollama query, browser open), usse asyncio Task.cancel() se rokta hai. Warna purana kaam khatam hone ka wait karna padta.\n\n3. NEW ITEM SWAP + WAKE: _pending_item mein nayi instruction store karta hai aur _event.set() call karta hai — jisse background worker loop jaag jaata hai aur naya kaam shuru karta hai.","Medium"),

(3,"What is double-checked locking and where is it used in speaker_encoder.py?",
"Double-checked locking ek thread-safety pattern hai jo performance optimize karta hai.\n\nPROBLEM: Agar sirf ek lock lagao, toh HAMESHA lock acquire karna padega — chahe model pehle se loaded ho. 100 concurrent calls = 100 baar lock acquire = slow.\n\nSOLUTION: Pehle BINA lock ke check karo (if self._loaded: return True). Sirf tab lock lo jab model loaded nahi hai. Lock ke andar DOBARA check karo — kyunki lock wait mein koi aur thread model load kar sakta tha.\n\nCode mein _ensure_loaded() mein:\nOuter if (no lock) → Lock acquire → Inner if (safety check) → Load model\n\nAgar 2 threads simultaneously pahunche — dono outer if fail karenge, dono lock mein queue honge. Pehla load karega, _loaded=True set karega. Doosra lock milne pe inner if se seedha return karega.","Hard"),

(4,"Why does _background_worker() use asyncio.shield(future) with asyncio.wait_for()?",
"Yeh subtle hai — dhyan se samjho.\n\nPROBLEM WITHOUT SHIELD: wait_for(future, timeout=2.0) — agar 2 second mein result nahi aaya, wait_for future ko CANCEL kar deta hai. Matlab background mein chal raha Ollama/tool call bhi cancel ho jaata. Bahut bura!\n\nSHIELD KA KAAM: asyncio.shield(future) ek WRAPPER future banata hai. wait_for sirf wrapper ko cancel karta hai — original future safe rehta hai, background task chal-ta rehta hai.\n\nToh hota yeh hai: 2s timeout fire hota hai → thinking_capability() return karta hai 'Kar rahi hoon, tu bol' → Background mein Ollama apna kaam karta rehta hai → Jab result aata hai, future._timed_out check se pata chalta hai ki sync path already reply kar chuka — toh result directly say_to_user() se bolti hai Vani.","Hard"),

(5,"Explain asyncio.run_coroutine_threadsafe(). When is it used and why can't you just await from those threads?",
"Simple rule: await sirf async function ke andar kaam karta hai. HTTP handler ek normal thread hai — wahan await karna ILLEGAL hai.\n\nspeak_to_user_from_thread() HTTP server thread se call hoti hai. Yeh thread event loop nahi jaanti.\n\nrun_coroutine_threadsafe(coroutine, loop) kya karta hai: loop ki queue mein coroutine schedule karta hai — thread-safe tarike se. Fir woh coroutine loop ke thread mein execute hoti hai, caller thread return kar jaati hai.\n\nReal example: User ne browser se text bheja → HTTP handler thread mein request aayi → woh thread say_to_user() await nahi kar sakti → run_coroutine_threadsafe() se Vani ke event loop mein speech schedule ho gayi.","Medium"),

(6,"What does asyncio.create_task() return and how does it differ from await coroutine?",
"await coroutine: Current function RUKE, coroutine complete ho, tab aage badhe. Sequential execution — ek ke baad ek.\n\ncreate_task(coroutine): Coroutine ko BACKGROUND mein schedule karo aur turant Task object return karo. Main code aage badhta rehta hai. Concurrent execution.\n\nVani mein example: asyncio.create_task(say_to_user(announce_msg)) — voice announcement schedule hoti hai, aur main code turant mic recording shuru kar deta hai. Agar await karta, toh pehle poori announcement wait karni padti, tab recording. 0.8s ka sleep dono ke beech sync ke liye hai.","Easy"),

(7,"In _run_single_tool(), why check future._timed_out before calling future.set_result()?",
"Race condition hai yahan.\n\nTimeline: Tool start hota hai → 2 second baad timeout fire hota hai → thinking_capability() 'Kar rahi hoon' return karta hai → Future ALREADY resolved ho gayi timeout path se.\n\nAb agar tool 3 second mein finish ho aur blindly future.set_result(result) call kare — InvalidStateError aayega! 'Tum ek already-resolved future pe dobara result set nahi kar sakte.'\n\nFix: future._timed_out flag check karo. Agar True hai, future pe set_result mat karo — instead asyncio.create_task(say_to_user(result)) se result directly bol do. User ko late result mil jaata hai via speech, no crash.","Hard"),

(8,"What is asyncio.Semaphore in _get_parallel_semaphore()? What does _MAX_PARALLEL_TOOLS control?",
"Semaphore ek TICKET system hai. _MAX_PARALLEL_TOOLS=3 matlab sirf 3 tickets hain.\n\nKoi bhi tool chalane se pehle: async with sem — ek ticket lo. Kaam khatam: ticket wapas do.\n\nAgar 3 tools pehle se chal rahe hain, 4th tool WAIT karega jab tak koi ticket wapas na de.\n\nKyun zaroori hai: Ollama (local LLM) RAM limited hai. Browser automation bhi system resources leta hai. Unlimited parallel tools = system crash ya bahut slow response. 3 ka balance achha hai — parallelism bhi hai, overload bhi nahi.","Easy"),

(9,"How does run_in_executor() make blocking code non-blocking? Give an example.",
"asyncio single-threaded hai. Agar blocking code directly event loop mein chale, POORA Vani freeze ho jaaye.\n\nrun_in_executor(None, blocking_fn) kya karta hai: blocking function ko ThreadPoolExecutor ke ek alag thread mein bhej deta hai. Main event loop FREE rehta hai — Vani baat kar sakti hai, dusre tasks handle kar sakti hai.\n\nExample — _blocking_record():\nsounddevice.rec() 5 SECONDS tak block karta hai (mic se recording). Agar event loop mein direct chale, 5 second kuch nahi hoga. run_in_executor() se yeh background thread mein chala, event loop free raha, aur jab recording done hoi tab await wapas result le aaya.","Medium"),

(10,"What does 'atomic write' mean and how does _flush() in ConversationMemory achieve it?",
"Atomic write = ya toh POORA data likh gaya, ya kuch nahi likha. Beech ka state kabhi nahi hoga.\n\nProblem without atomic write: File write hote waqt power cut ya crash — file CORRUPT ho sakti hai — half-written JSON = parse error = all memory lost.\n\n_flush() ka process:\nStep 1: memory.json.tmp file mein likho\nStep 2: f.flush() — Python buffer disk pe bhejo\nStep 3: os.fsync() — OS kernel buffer bhi disk pe bhejo (hardware level)\nStep 4: os.replace(tmp, memory.json) — ATOMIC rename\n\nos.replace() POSIX pe atomic hai — kernel level pe single operation. Reader kabhi half-written file nahi dekhega. Ya purani file milegi, ya nayi — kabhi corrupt nahi.","Medium"),
]))

# SECTION 2
ALL_SECTIONS.append(("2. Architecture & Design Patterns", "System design, OOP, and structural decisions", [
(11,"Describe the overall architecture of Vanni. What are the main layers?",
"Vani 6 layers mein kaam karta hai — ek pipeline ki tarah:\n\nLAYER 1 — Wake Listener: Hamesha ON. Mic sun raha hai. 'Vani' suna → aage bheja.\nLAYER 2 — Deterministic Router: Regex patterns se check karo — kya yeh WhatsApp/YouTube/Media command hai? Agar haan, seedha dispatch karo. LLM ki zaroorat nahi — 0ms overhead.\nLAYER 3 — LatestWinsQueue Worker: Agar router nahi pakad paya, Qwen LLM ko bhejo. Queue last-write-wins maintain karta hai.\nLAYER 4 — Ollama/Qwen (LLM): Tool decide karta hai — kaunsa tool call karna hai, kya arguments.\nLAYER 5 — Tool Registry + Tools: Actual kaam karta hai — WhatsApp kholta hai, browser control karta hai, notes save karta hai.\nLAYER 6 — LiveKit Session: Voice in/out handle karta hai — Vani ki awaaz user tak aati hai, user ki awaaz Vani tak jaati hai.","Medium"),

(12,"What design pattern does LatestWinsQueue implement? Give a real-world analogy.",
"Pattern: Last-Write-Wins Queue (Replace Queue bhi bolte hain)\n\nAnalogy 1 — Elevator button: Tune 3rd floor press kiya, phir 7th floor press kiya. Elevator sirf 7th floor jaayega — 3rd floor cancel. Purana instruction irrelevant ho gaya.\n\nAnalogy 2 — TV remote: Channel 5 press kiya, phir Channel 8 press kiya — TV seedha Channel 8 pe jaayega.\n\nVani mein exactly yahi: 'YouTube kholo' bola, turant 'WhatsApp kholo' bola — Vani sirf WhatsApp kholegi. YouTube ka kaam cancel.","Easy"),

(13,"Why is the tool registry (_TOOLS dict) separate from tool implementations?",
"Teen reasons hain:\n\n1. SINGLE SOURCE OF TRUTH: Naya tool add karna? Sirf registry.py mein ek line. Ollama prompt automatically update ho jaata hai kyunki _TOOL_DESCRIPTIONS registry se generate hoti hai.\n\n2. ALIAS SUPPORT: Qwen (LLM) kabhi kabhi wrong tool name hallucinate karta hai — 'whatsapp_chats', 'screen_read'. Registry mein aliases hain jo wrong names ko correct tools pe map karte hain. Bina registry ke, har galat naam pe crash hota.\n\n3. DECOUPLING: Tool implementation change karo — registry touch mat karo. Router ko pata nahi ki tool kaise kaam karta hai, bas naam jaanta hai.","Medium"),

(14,"The router has two layers: _router_classify() and _qwen_decide_and_run(). When does control pass from one to the other?",
"Layer 1 — _router_classify() (Regex, ~0.1ms):\nCompiled regex patterns se check karta hai. WhatsApp commands, YouTube, media, study mode, voice enrollment — sab predefined patterns.\nAGAR match mila → seedha _dispatch_intent() call, Qwen ki zaroorat NAHI.\nAGAR match nahi mila → Layer 2 ko pass.\n\nLayer 2 — _qwen_decide_and_run() (Ollama LLM, ~500ms-2s):\nQwen ko poora tool description deta hai. LLM decide karta hai kaunsa tool call karna hai.\n\nKYUN DO LAYERS: LLM expensive hai — tokens cost hain, latency hai. Common commands (70-80%) regex se instantly handle hote hain. Sirf ambiguous/complex queries LLM tak pahunchti hain.","Medium"),

(15,"SpeakerEncoder uses a module-level singleton _ENCODER. Pros and cons?",
"PROS:\n- VoiceEncoder model (50MB) sirf ONCE load hota hai — memory efficient\n- Sab jagah se same encoder instance — consistent state\n- Lazy loading ke saath: import cost zero, load sirf pehli baar\n\nCONS:\n- Testing mein mushkil: Singleton mock karna hard hai. test_speaker_verification.py mein actual VoiceEncoder load karna padta hai ya complex patching.\n- Thread safety manually handle karni padti hai (isliye _load_lock hai)\n- Global state = hidden dependency. Koi bhi module bina explicitly pass kiye encoder use kar sakta hai — yeh code readability ke liye thoda bura hai.","Medium"),

(16,"Explain Fail-Open design in speaker_encoder.verify(). When would you want Fail-Closed?",
"FAIL-OPEN matlab: Agar verification system FAIL ho (encoder load nahi hua, numpy error, kuch bhi), toh user ko ACCESS DE DO.\n\nVani mein kyun Fail-Open: Yeh ghar ka assistant hai. Agar Resemblyzer install nahi hai ya model corrupt hai, Vani completely kaam karna band kar de? Unacceptable. Better hai Vani kaam kare — thodi security loose karo, availability maintain karo.\n\nCode mein: verify() mein kisi bhi exception pe return True.\n\nFAIL-CLOSED kab chahiye:\n- Banking app: Agar biometric fail ho, transaction BLOCK karo\n- Medical device: Unknown user ko access mat do\n- Enterprise data: Agar auth fail, access deny karo\nRule of thumb: Availability > Security (personal assistant) vs Security > Availability (sensitive systems)","Hard"),

(17,"How does lazy loading work in _ensure_loaded()? Why NOT load at __init__ time?",
"Lazy loading = 'Jab zaroorat ho tab load karo, pehle se nahi.'\n\n__init__ pe load karne ki problem:\n- VoiceEncoder 500ms+ leta hai load hone mein\n- 50MB RAM immediately allocate ho jaata\n- Agar user ne kabhi voice enrollment use nahi ki, yeh sab waste\n\n_ensure_loaded() ka logic:\n1. self._loaded True hai? Return immediately (already loaded, 0ms)\n2. self._failed True hai? Return False immediately (pehle try fail ho chuka, retry mat karo)\n3. Pehli baar: Lock lo, model load karo, _loaded=True set karo\n\nResult: Vani startup bahut fast. Speaker verification pehli baar ~500ms lagta hai, baad mein instantaneous.","Easy"),

(18,"What is the _COMPAT dict in router.py? What problem does it solve?",
"Backward compatibility problem.\n\nV3 mein browser_regex.py update hua — usne naye short intent names dene shuru kiye: YT_PLAY, YT_PAUSE, SEARCH_GOOGLE, BROWSER_URL.\n\nLekin _dispatch_intent() ke andar purane names the: YOUTUBE_PLAY, YOUTUBE_PAUSE, GOOGLE_SEARCH, OPEN_URL.\n\nBina COMPAT dict ke: V3 router YT_PLAY return karta → _dispatch_intent() mein koi case nahi milta → kuch nahi hota.\n\nCOMPAT dict YT_PLAY → YOUTUBE_PLAY map karta hai. Toh V3 ka output V1 handlers pe correctly route hota hai. Bina saare handlers rename kiye. Smart incremental migration.","Easy"),

(19,"Describe the event-driven architecture of _background_worker(). What events drive it?",
"_background_worker() ek INFINITE LOOP hai jo events pe jaag-ta hai:\n\nNormal state: await queue.get() pe BLOCK — koi kaam nahi, CPU use nahi, loop soya hua.\n\nEVENT 1 — User bolta hai: put_nowait() call hoti hai → _event.set() → queue.get() return karta hai → Worker jaagta hai → Task create karta hai.\n\nEVENT 2 — Naya command aaya jab task chal raha tha: LatestWinsQueue active task CANCEL karta hai → CancelledError propagate hoti hai → Worker CancelledError pakad-ta hai → Loop dobara queue.get() pe block.\n\nEVENT 3 — Task complete: future.set_result() → Worker loop dobara await queue.get() pe jaata hai.\n\nYeh architecture CPU-efficient hai — worker sirf tab active hai jab kaam hai.","Hard"),

(20,"Why does _dispatch_intent_in_thread() use asyncio.run() instead of the existing event loop?",
"Yeh tab call hota hai jab Ollama (sync HTTP call) ne response parse kiya aur compound intent mila.\n\nPROBLEM: _call_ollama_sync() ek normal synchronous function hai — event loop nahi hai wahan. Usse await nahi kar sakte. Existing event loop thread-safe nahi hai direct calling ke liye.\n\nrun_coroutine_threadsafe() bhi nahi use kar sakte — woh sirf ek coroutine schedule karta hai, asyncio.run() ki need hai full intent dispatch ke liye jo khud async functions call karta hai.\n\nSOLUTION: Nayi thread banao, us thread mein asyncio.run() se fresh event loop banao, _dispatch_intent() us loop mein run karo, thread khatam ho jaata hai.\n\nDaemon=True isliye: Agar main program exit kare, yeh background thread automatically kill ho jaaye, hang nahi kare.","Hard"),
]))

# SECTION 3
ALL_SECTIONS.append(("3. Voice Pipeline & Wake Detection", "Audio processing, Vosk, double-clap detector", [
(21,"Explain the two parallel wake detectors. What are the tradeoffs?",
"Dono detectors EK hi mic stream share karte hain, parallel chal-te hain:\n\nDETECTOR 1 — Vosk Keyword Spotter:\nKya karta hai: 'Vani', 'Vanni', 'Hey Vani' patterns sun-ta hai\nPros: Offline (no internet), ~50ms latency, 40MB model, bahut accurate\nCons: Vosk install karna padta, model download karna padta\n\nDETECTOR 2 — Double Clap:\nKya karta hai: Do energy spikes detect karta hai 0.8s ke andar\nPros: ZERO extra dependencies — sirf numpy chahiye. Music bajte waqt bhi kaam karta hai.\nCons: False positives — table thokne se, door band karne se bhi trigger ho sakta hai.\n\nCombined: Dono mein se koi bhi fire kare, Vani jaag-ti hai. Yeh redundancy hai — Vosk fail ho toh clap backup.","Medium"),

(22,"What sample rate does wake listener use? Why is 16kHz chosen?",
"16,000 Hz (16kHz) use hota hai.\n\nNyquist Theorem: Sample rate se aadhi frequency tak ki sounds capture ho sakti hain. 16kHz → 8kHz tak capture.\n\nHuman speech range: 80Hz se 8,000Hz tak. Toh 16kHz EXACTLY enough hai — speech ke liye kuch bhi miss nahi hota.\n\n44.1kHz (CD quality) kyun nahi: Speech ke liye unnecessary. 16kHz se 44.1kHz mein 2.75x zyada data — zyada RAM, zyada CPU, koi benefit nahi.\n\nVosk model bhi 16kHz expect karta hai — isliye consistent hai. Resemblyzer bhi internally 16kHz pe process karta hai.","Easy"),

(23,"What is a ring buffer? Why is _AUDIO_RING used instead of a simple list?",
"Ring buffer (circular buffer) = fixed-size container. Jab full ho jaaye, purana data automatically overwrite ho jaata hai.\n\nPython mein: collections.deque(maxlen=125)\n\nSimple list ki problem: Hamesha growing. Agar list use karo aur clear na karo, RAM continuously bhar-ti jaayegi. Manually clean karna bhi complex hai.\n\nRing buffer ka fayda:\n- Hamesha last N frames sirf — exactly jo speaker verification ko chahiye (~2.5s audio)\n- maxlen=125 matlab 125 audio blocks x 512 frames x (1/16000s) ≈ 4 seconds\n- Automatically oldest drop hota hai — koi manual management nahi\n- O(1) append aur access — bahut fast","Medium"),

(24,"How does the double-clap detector work? What two timing thresholds does it check?",
"Algorithm:\n1. Har audio block ka RMS energy calculate karo\n2. Energy agar baseline x CLAP_THRESHOLD (default 4.0) se zyada hai → SPIKE detected\n3. Pehla spike store karo with timestamp\n4. Doosra spike aaya? Do checks:\n\nCHECK 1 — GAP_MIN (0.15 seconds):\nDono spikes ke beech MINIMUM 0.15s hona chahiye.\nKyun: Ek hi loud sound ke reverb se double-trigger prevent karta hai. Ek zor ki awaaz → echo → 0.05s baad dusra spike → ye clap nahi, echo hai.\n\nCHECK 2 — GAP_MAX (0.8 seconds):\nDono spikes 0.8s ke ANDAR hone chahiye.\nKyun: Agar 2 second baad doosra clap, toh random sounds hain — intentional double-clap nahi.","Medium"),

(25,"What is VANI_WAKE_COOLDOWN and why is it needed?",
"Default 3 seconds.\n\nProblem without cooldown: Tune 'Vani' bola → audio buffer mein woh sound 0.5s tak rehti hai → Vosk woh same audio ke alag segments se multiple times 'Vani' detect karta hai → Vani 5-6 baar ek saath jaag jaati hai → multiple overlapping tasks.\n\nWAKE_COOLDOWN solution: Ek wake trigger ke baad 3 second tak koi naya trigger nahi. _last_wake_time store hoti hai, _wake_lock se thread-safe comparison.\n\nTiming chosen: 3s = enough time for user to say command after waking. Too short (0.5s) = false re-triggers. Too long (10s) = user frustrated if real second wake needed.","Easy"),

(26,"Why use a shared sounddevice InputStream instead of two separate streams?",
"OS level pe mic ek resource hai — multiple exclusive streams possible nahi (most systems pe).\n\nEK stream ke fayde:\n1. Resource conflict nahi — dono detectors same handle use karte hain\n2. Perfect sync — dono detectors exactly same audio data process karte hain\n3. Half CPU — ek callback, do detectors. Separate streams = do callbacks = extra overhead\n4. Simple cleanup — ek stream band karo, dono detectors stop\n\nFan-out pattern: mic_callback() → ring buffer update + Vosk queue + clap detector sab ek hi callback mein.","Medium"),

(27,"What is ENROLLMENT_MIN_SECONDS? Why 4.0 seconds?",
"Minimum 4.0 seconds ki audio enrollment ke liye required hai.\n\nResemblyzer ka mel spectrogram process: Audio ko frequency frames mein convert karta hai. Kam audio = kam frames = unreliable voiceprint.\n\n4 seconds se kam ka problem:\n- Mel spectrogram mein enough variation nahi milti\n- Embedding noisy hota hai — ek hi sentence se pattern extrapolate karna mushkil\n- Real-world: 3 second mein tune sirf 'Hello Vani register karo' bola — yeh ek hi sentence — enough data nahi\n\n4 seconds safe minimum hai. Enrollment flow actually 5 seconds record karta hai for extra margin.","Easy"),

(28,"Describe the enrollment flow end-to-end from voice command to disk save.",
"Complete pipeline:\n\nStep 1 — DETECT: _VOICE_ENROLL_RE regex 'register my voice' ya 'meri awaaz register karo' pakad-ta hai\nStep 2 — ANNOUNCE: say_to_user('5 second ke liye clearly bolo...') — asyncio.create_task se fire-and-forget\nStep 3 — SLEEP 0.8s: TTS announcement complete ho sake\nStep 4 — RECORD (blocking): sounddevice.rec(5s, 16kHz) run_in_executor mein — event loop block nahi hoti\nStep 5 — DURATION CHECK: 4 seconds se kam? Error return karo\nStep 6 — EMBED: embed_averaged(wav, sr, n_augments=5) — 5 pitch-shifted versions ka average embedding\nStep 7 — ATOMIC SAVE: voiceprint.npy.tmp mein likho → os.replace() se atomic rename\nStep 8 — CACHE RELOAD: reload_voiceprint() call — wake_verifier ka in-memory cache refresh karo\nStep 9 — REPLY: 'Teri awaaz successfully register ho gayi!'","Hard"),

(29,"How does _normalize_for_tts() from hinglish_speech.py improve TTS quality?",
"Problem: English TTS engines (jaise Google WaveNet, ElevenLabs) Hindi/Hinglish words ko galat pronounce karte hain.\n\nExamples:\n- 'karo' → TTS bolega 'KAY-roh' instead of 'KAH-roh'\n- 'hoon' → bilkul galat sound aata hai\n\nnormalize_for_tts() kya karta hai: Hinglish words ko phonetic English spellings mein convert karta hai jo TTS engine sahi pronounce kare.\n\nExample transformation:\n'Kar rahi hoon' → 'Kur rahi hoon' (phonetic approximation)\n\nYeh TTS pe bhejne SE PEHLE run hota hai — isliye user ko natural-sounding Hinglish speech milti hai.","Medium"),

(30,"What does VANI_WAIT_FOR_SPEECH_PLAYOUT do when set to '1'?",
"Default: OFF (0) — Vani speech trigger kare aur IMMEDIATELY aage badhe\n\nVANI_WAIT_FOR_SPEECH_PLAYOUT=1 mein: handle.wait_for_playout() await karo — matlab poori speech complete hone tak wait karo.\n\nProblem yeh solves karta hai: Vani pehla response bol rahi hai, doosra response turant aa jaata hai → overlap, interruption, user ko samajh nahi aata.\n\nKyun DEFAULT OFF hai: Responsiveness ke liye. Off hone pe: speech fire karo, next action shuru karo — faster feel.\n\nProduction mein ON karo jab: Sequential multi-step actions hain jahan order important hai.","Medium"),
]))

# SECTION 4
ALL_SECTIONS.append(("4. Speaker Verification & Machine Learning", "Resemblyzer, embeddings, cosine similarity, pitch robustness", [
(31,"What is a speaker embedding (d-vector)? What does the 256-dim output represent?",
"Speaker embedding = teri VOCAL TRACT ka mathematical fingerprint — 256 numbers ka ek array.\n\nVocal tract kya hai: Teri throat, mouth, nasal cavity ka shape. Yeh UNIQUE hai — jaise fingerprint. Baap-bete ki awaaz milti-julti hai kyunki vocal tract similar hota hai.\n\nResemblyzer kya karta hai:\n1. Audio ko mel spectrogram mein convert karta hai (frequency vs time)\n2. LSTM neural network se d-vector extract karta hai\n3. 256 numbers — har number ek abstract vocal feature\n\nKEY INSIGHT: Yeh 256 numbers CONTENT se independent hain. 'Hello' bolo ya 'Namaste' — same speaker ki embedding bahut similar hogi. Different speakers ki embedding door hogi cosine space mein.","Medium"),

(32,"Explain cosine similarity. Why prefer it over Euclidean distance?",
"Cosine similarity = dono vectors ke BEECH KA ANGLE. Range: -1 to 1. 1 = same direction = same speaker.\n\nFormula: cos(A,B) = (A.B) / (|A| x |B|)\n\nEuclidean distance ki problem: |A - B| — magnitude sensitive hai. Agar tune enrollment mein BAHUT SLOWLY bola (quiet, small vector) aur verification mein ZAAR SE bola (loud, large vector) — Euclidean distance badi hogi even though same speaker. False reject!\n\nCosine ka fayda: Division se magnitude CANCEL ho jaati hai. Quiet recording aur loud recording same speaker ki — SAME cosine similarity. Sirf direction matter karta hai, scale nahi.\n\nVani mein: L2-normalise karte hain embeddings — tab cosine similarity = simple dot product (even faster computation).","Medium"),

(33,"What is pitch-robust verification and why was it added?",
"ATTACK: Koi deliberately bahut OONCHI ya NEECHI awaaz mein bolta hai → embedding shift ho jaati → cosine similarity threshold ke neeche → Vani reject karti.\n\nFIX — Pitch-robust verification:\n5 pitch-shifted copies of live audio banao: -4, -2, 0, +2, +4 semitones\nHar copy ka embedding nikalo\nMAXIMUM similarity lo saari 5 copies mein\nAgar ANY copy threshold pass kare → ACCEPT\n\nLOGIC: Owner ki vocal tract shape same rehti hai at all pitches. Maximum across 5 shifts = real owner natural pitch dhundh leta hai. Impostor ki vocal tract different — chahe kitni bhi shifts karo, max similarity below threshold rehti hai.","Hard"),

(34,"Explain _pitch_shift_resample(). What operation implements pitch shifting?",
"Pitch shift = RESAMPLING TRICK (speed-change method).\n\nConcept: Agar audio ko 2x fast play karo (double speed), pitch double ho jaati hai (+1 octave = +12 semitones). Agar half speed, pitch half ho jaati.\n\nMath: ratio = 2^(semitones/12)\n+4 semitones: ratio = 2^(4/12) = 1.26 — 26% faster\n-4 semitones: ratio = 2^(-4/12) = 0.79 — 21% slower\n\nImplementation: Linear interpolation se nayi length ke audio samples generate karo:\nold_idx = linspace(0, old_len-1, new_len)\nshifted = np.interp(old_idx, arange(old_len), wav)\n\nSpeed: ~0.5ms per shift — bahut fast.","Hard"),

(35,"What is embed_averaged() and why does it make a better voiceprint?",
"Problem with single embed(): Tune enrollment ke time thoda OONCHI awaaz mein bola. Teri natural speaking pitch thodi neechi hai. Verification pe fail — embedding slightly different.\n\nembed_averaged() solution:\n1. 5 pitch offsets lete hain: -4, -2, 0, +2, +4 semitones\n2. Har offset pe pitch-shift karo\n3. Har shifted audio ka embedding nikalo\n4. Saare 5 embeddings ka AVERAGE nikalo\n5. L2 normalize karo\n\nResult: Stored voiceprint teri natural pitch range cover karta hai. -4 to +4 semitones ke beech tere baat karne ka CENTRE of mass.\n\nVerification pe: Chahe tu normal pitch mein bole ya thoda ooncha-neecha — tu stored range ke andar hoga. Impostor ki vocal tract fundamentally alag — woh range ke bahar.","Hard"),

(36,"Why is L2 normalisation applied to the averaged embedding?",
"Two reasons:\n\nREASON 1 — Cosine similarity = dot product:\nL2 norm = 1 wale vectors ke liye: cos(A,B) = A.B (normal vectors ka dot product).\nBina normalization: Division karna padti hai (slower).\nWith normalization: Sirf dot product — 3x faster.\n\nREASON 2 — Fair averaging:\n5 pitch-shifted embeddings average kar rahe hain. Agar kuch embeddings ki magnitude badi hai, woh DOMINATE karenge average ko.\nL2 normalize karne se sab embeddings equal weight pe contribute karte hain average mein.\n\nFormula: avg = avg / ||avg|| (divide by vector length)\nResult: ||avg|| = 1 (unit vector)","Medium"),

(37,"What threshold is used for verification? What happens if too high or too low?",
"Codebase mein: ~0.72-0.75 (configurable)\n\nTOO HIGH (e.g., 0.95):\n- Owner ka din ka pehla sentence thoda rough tha (subah uthke) → similarity 0.88 → REJECT\n- User frustrated — Vani apne owner ko hi nahi sun rahi\n- FAR (False Accept Rate) very low, but FRR (False Reject Rate) bahut high\n\nTOO LOW (e.g., 0.40):\n- Koi bhi bole 'Vani' → similarity 0.45 → ACCEPT\n- Security completely useless\n\nSWEET SPOT 0.72-0.75:\n- Real owner: 0.80-0.95 (comfortably passes)\n- Family member with similar voice: 0.60-0.70 (mostly rejected)\n- Complete stranger: 0.20-0.50 (well below)\n\nEER (Equal Error Rate) pe set karo — jahan FAR = FRR. Test multiple speakers aur plot ROC curve.","Medium"),

(38,"SpeakerEncoder class appears TWICE in speaker_encoder.py. What bug does this cause?",
"YEH EK REAL BUG HAI TERE CODE MEIN!\n\nPython mein second class definition first ko OVERWRITE kar deta hai.\n\nFirst SpeakerEncoder: Pitch-robust verify() — 5 pitch variants test karta hai, maximum similarity leta hai.\nSecond SpeakerEncoder: Simple verify() — sirf ek embed() call, single similarity check.\n\nModule-level _ENCODER = SpeakerEncoder() — yeh SECOND (simpler, less secure) class se banata hai.\n\nMatalab: Poori pitch-robust verification jo tune implement ki — DEAD CODE hai. Kabhi execute nahi hogi.\n\nFIX: Second SpeakerEncoder class delete karo. Sirf pehli (pitch-robust) wali rakho. _ENCODER = SpeakerEncoder() last mein hona chahiye, ek hi class ke baad.","Hard"),

(39,"What does Resemblyzer's preprocess_wav() do before embedding?",
"preprocess_wav() 4 cheezein karta hai:\n\n1. RESAMPLE TO 16kHz: Agar audio 44.1kHz hai, 16kHz pe resample karo. VoiceEncoder 16kHz expect karta hai.\n\n2. AMPLITUDE NORMALIZE: Audio peaks ko consistent level pe laao. Quiet recording aur loud recording comparable ban jaaye.\n\n3. VOICE ACTIVITY DETECTION (VAD): Silence detect karo aur remove karo. Sirf actual speech segments rakho. Embedding silence se affect nahi hogi.\n\n4. TRIM & CHUNK: Long audio ko sliding window chunks mein process karta hai (1.6s windows, 0.8s hop). Har chunk ka embedding nikalta hai, average karta hai.\n\nResult: Clean, normalized, speech-only audio — consistent embeddings regardless of recording conditions.","Medium"),

(40,"How would you evaluate the speaker verification system's performance?",
"Complete evaluation framework:\n\nMETRICS:\n- FAR (False Accept Rate): Kitne impostors accept hue / total impostors\n- FRR (False Reject Rate): Kitne times owner reject hua / total owner attempts\n- EER (Equal Error Rate): Threshold jahan FAR = FRR — lower = better model\n\nTEST SETUP:\n- 10+ different speakers record karo (impostors)\n- Owner multiple sessions mein record karo — morning, evening, sick, normal\n- Pitch variations test karo: -4 to +4 semitones manually\n- Background noise test karo: TV on, AC on\n\nPLOT ROC CURVE: X-axis FAR, Y-axis (1-FRR). AUC (Area Under Curve) — closer to 1 = better.\n\nCURRENT SYSTEM TEST: pitch-robust zyada FRR reduce karti hai owner ke liye vs non-pitch-robust. Quantify this improvement.","Hard"),
]))

# SECTION 5
ALL_SECTIONS.append(("5. Intent Routing & NLP", "Regex classifiers, Hinglish NLP, deterministic routing", [
(41,"What is the two-layer routing strategy? What % of queries does each layer handle?",
"LAYER 1 — Deterministic Regex Router (_router_classify()):\n~70-80% queries yahan handle hoti hain\nKya pakadta hai: WhatsApp (send/read/call), YouTube controls, media (play/pause/next), study mode, voice enrollment, Instagram, browser controls, Google search, app open/close\nSpeed: <1ms — regex compiled at module load\nCost: ZERO tokens, ZERO API calls\n\nLAYER 2 — Ollama/Qwen LLM:\n~20-30% complex/ambiguous queries\nKya pakadta hai: Multi-intent commands, ambiguous phrasing, new commands not in regex\nSpeed: 500ms-2s\nCost: Local compute (no API cost but CPU/RAM)\n\nWHY THIS MATTERS: Agar sab Qwen se jaaye, har simple 'pause karo' pe 1s+ wait. Regex se 0.5ms mein handle.","Medium"),

(42,"Explain the COMPAT dict. Why are YT_PLAY and YOUTUBE_PLAY both needed?",
"Version migration problem:\n\nHISTORY:\n- V1/V2: Router intent names: YOUTUBE_PLAY, YOUTUBE_PAUSE, GOOGLE_SEARCH\n- V3 browser_regex.py: Short names introduce kiye: YT_PLAY, YT_PAUSE, SEARCH_GOOGLE\n\n_dispatch_intent() mein PURANE names ke cases hain. Naye names ke cases NAHI hain.\nToh V3 router YT_PLAY return kare → dispatch switch mein miss → kuch nahi hota.\n\nCOMPAT dict ek translation layer hai:\n_COMPAT = {'YT_PLAY': 'YOUTUBE_PLAY', 'YT_PAUSE': 'YOUTUBE_PAUSE', ...}\nmapped = _COMPAT.get(bi_intent, bi_intent)\n\nElegant solution: Naye tools rename nahi kiye, purana interface preserve kiya, bech mein mapping layer.","Easy"),

(43,"Why are regex patterns compiled at module load with __import__('re').compile()?",
"TWO REASONS:\n\nREASON 1 — Performance:\nre.compile() ek EXPENSIVE operation hai — regex ko NFA/DFA state machine mein convert karta hai. Agar har request pe compile karo → har 'Vani' ke baad 10+ compiles → slow.\nModule load pe ek baar compile → instance life bhar use karo.\n\nREASON 2 — __import__('re') hack:\nModule top pe 're' import kiya hua hai. Lekin kuch lines mein inline __import__('re').compile() use kiya — shayad circular import issue tha ya quick workaround tha.\n\nBETTER PRACTICE: File ke top pe import re karo, module level pe variables define karo:\n_STUDY_START_RE = re.compile(r'...', re.IGNORECASE)\nHar compile pe 3-5x speedup compared to per-request compilation.","Medium"),

(44,"What is Hinglish and how does the codebase handle it? Give examples.",
"Hinglish = Hindi + English mix. 'Yaar, WhatsApp pe Shrey ko bol kal milte hain' — yeh Hinglish hai.\n\nCodebase mein handling:\n\n1. REGEX PATTERNS WITH HINGLISH:\n_VOICE_ENROLL_RE: 'meri awaaz register karo' AND 'register my voice' — dono pakadta hai\n_STUDY_START_RE: 'study shuru karo' AND 'padhai start karo' AND 'start study'\n\n2. HINGLISH SEARCH CLASSIFIER:\nclassify_hinglish_question_as_search(): 'kya hai artificial intelligence', 'kaise karte hain Python install' → Google search intent\n\n3. WA_SURNAME_NOISE set:\n'Harshit Sharma ko message bhejo' → strip 'Sharma' → search 'Harshit'\n\n4. TTS NORMALIZATION:\nHindi words ko English TTS ke liye phonetic forms mein convert","Easy"),

(45,"Explain _classify_search_intent(). What edge case does _looks_like_url() guard against?",
"_classify_search_intent() SEARCH TRIGGER WORDS detect karta hai:\n\nPatterns:\n'google karo X' → search X\n'search for X' → search X\n'X dhundo' → search X\n\n_looks_like_url() edge case:\n'google.com kholo' → yeh URL hai, search nahi!\nBina URL check ke: 'google.com' extract hota → google_search('google.com') → Google pe 'google.com' search hota (wrong!)\n\nURL check: regex se check karo — agar extracted text domain-like hai (has dot, no spaces, valid TLD) → return None (not a search, it's a URL intent)\n\nPhir router.py mein: URL intent ko open_url_in_browser route karo.","Medium"),

(46,"Why does the router check _VOICE_DELETE_RE before _VOICE_ENROLL_RE?",
"Priority order matter karta hai jab patterns overlap kar sakte hain.\n\nCONSIDER: 'meri awaaz delete karo aur naya enroll karo'\n- _VOICE_ENROLL_RE check: 'enroll karo' match → ENROLL intent return → DELETE kabhi execute nahi hoga\n\nLEKIN agar _VOICE_DELETE_RE pehle:\n- 'delete karo' match → DELETE intent return → correct!\n- Second part (enroll) handle hoga next query mein\n\nDelete more DESTRUCTIVE action hai — pehle catch karo. Better safe than sorry. Accidental enrollment undo karna easy, accidental deletion ka pata nahi chalega.\n\nGENERAL RULE: Destructive/specific patterns pehle check karo, generic/constructive baad mein.","Medium"),

(47,"Instagram patterns use named capture groups (?P<contact1>). What's the advantage?",
"Named vs numbered groups comparison:\n\nNUMBERED (bad for alternatives):\nm.group(1) — kaunse alternative ne match kiya? Unknown. Har alternative mein group count alag ho sakta hai.\n\nNAMED (pattern mein use):\n(?P<contact1>\\w+)...(?P<contact2>\\w+)...(?P<contact3>\\w+)\n\nCode:\ncontact = (m.group('contact1') or m.group('contact2') or m.group('contact3') or '').strip()\n\nMatlab: Teen alag alternatives mein contact group ho sakta hai. Or chain se pehla non-None value lo.\n\nREADABILITY: m.group('contact1') clearly batata hai kya extract ho raha hai. m.group(3) ka pata nahi bina pattern padhe.\n\nMAINTENANCE: Pattern mein naya group add karo — existing group numbers shift nahi hote.","Medium"),

(48,"What does re.compile() with re.IGNORECASE do? Why is it critical for voice input?",
"re.IGNORECASE flag case-insensitive matching karta hai.\n\n'WhatsApp' == 'whatsapp' == 'WHATSAPP' == 'Whatsapp' — sab match.\n\nKyun CRITICAL for voice-to-text (STT):\nSTT engines inconsistent hain casing mein:\n- Google STT: Proper nouns capitalize karta hai → 'WhatsApp', 'YouTube'\n- Whisper: Sentence start capitalize karta hai → 'Send whatsapp message'\n- Some STT: All lowercase → 'send whatsapp message to shrey'\n\nBina IGNORECASE:\nPattern r'whatsapp' hai\nInput 'WhatsApp ko message bhejo' → NO MATCH → Qwen fallback → slower\n\nWith IGNORECASE:\nSab match → instant router hit","Easy"),

(49,"How would you add a new intent for 'Vani, set a timer for X minutes'? Walk through all files.",
"Step-by-step implementation:\n\nFILE 1 — router.py:\n_TIMER_RE = re.compile(r'(\\d+)\\s*min(?:ute)?s?\\s*(?:ka\\s+)?timer', re.IGNORECASE)\n\nAdd in _router_classify():\nm = _TIMER_RE.search(q)\nif m: return 'TIMER_SET', {'minutes': int(m.group(1))}\n\nFILE 2 — reasoning/tools/timer.py (new file):\nfrom livekit.agents import function_tool\nasync def set_timer(minutes: int) -> str: ...\n\nFILE 3 — registry.py:\nfrom vani.reasoning.tools.timer import set_timer\n_TOOLS['set_timer'] = set_timer\n_TOOL_DESCRIPTIONS += '\\nset_timer(minutes) - Timer set karo'\n\nFILE 4 — router.py _dispatch_intent():\nelif intent == 'TIMER_SET':\n    from vani.reasoning.tools.timer import set_timer\n    return await set_timer(**data)","Hard"),

(50,"What is _router_classify_many() for? When do you need multiple intents?",
"Compound commands handle karne ke liye — ek sentence mein do kaam.\n\nExamples:\n'Shape of You bajao aur Shrey ko bhej do' → [YOUTUBE_PLAY('Shape of You'), WHATSAPP_SEND('Shrey', 'Shape of You sun')]\n'Notes save karo aur WhatsApp pe Rahul ko bata do' → [SAVE_NOTE(...), WHATSAPP_SEND('Rahul', ...)]\n\nImplementation: List of (intent, data) tuples return karta hai.\n\n_dispatch_intent_in_thread() mein: Iterate karo aur PARALLEL threads mein dono actions fire karo.\n\nChallenge: Natural language splitting — 'bajao aur bhej do' mein 'aur' separator hai. Regex se identify karna mushkil. Isliye yeh path mostly LLM (Qwen) se handle hota hai jo better NLU karta hai.","Hard"),
]))

# SECTION 6
ALL_SECTIONS.append(("6. Memory Architecture & Storage", "SQLite, JSON persistence, caching, TTL, context retrieval", [
(51,"Describe the two memory systems: ConversationMemory (JSON) and human_memory (SQLite). When is each used?",
"DO ALAG SYSTEMS hain — alag purposes ke liye:\n\nConversationMemory (JSON files):\n- Kya store karta hai: Raw conversation history — user ne kya poocha, Vani ne kya jawab diya, timestamps\n- Format: JSON array of conversation objects\n- Per-user: {user_id}_memory.json\n- Use case: 'Hum kya baat kar rahe the?' — recent context ke liye\n\nhuman_memory (SQLite database):\n- Kya store karta hai: STRUCTURED data — documents (PDFs, notes), permanent facts, preferences, chunks\n- Tables: temp_documents, temp_document_chunks, permanent_memory\n- WAL mode: Concurrent reads + writes\n- Use case: 'Uss PDF mein kya tha?' — document retrieval, long-term facts\n\nKEY DIFFERENCE: JSON fast aur simple (conversation log). SQLite queryable aur scalable (knowledge base).","Medium"),

(52,"What is WAL mode in SQLite? Why does human_memory enable it?",
"WAL = Write-Ahead Logging. Default SQLite mode = DELETE journal (readers block writers aur vice versa).\n\nWAL ka fayda:\n- Writers ek alag WAL file mein likhte hain\n- Readers purani consistent state read kar sakte hain WHILE writer write kar raha hai\n- CONCURRENT READS POSSIBLE during write — no blocking\n\nVani mein specifically kyun:\nImagine: Vani ek PDF ka chunk database mein save kar rahi hai (write) aur SAATH SAATH user ne poocha 'document mein kya tha?' (read).\n- Without WAL: Reader write complete hone ka wait karega — lagta hai Vani freeze ho gayi\n- With WAL: Read aur write simultaneously — smooth experience\n\nPRAGMA journal_mode=WAL; — ek line, massive concurrency improvement.","Hard"),

(53,"Explain the in-memory cache in ConversationMemory. What is _cache_dirty and why needed?",
"Cache logic:\n\n_cache (List): Memory ka in-memory copy. Pehli load_memory() call pe disk se padha, baad mein _cache return karta hai directly. No disk I/O on subsequent calls.\n\n_cache_dirty (bool): 'Kya in-memory data disk se alag hai?'\n- False: Disk aur memory same hain\n- True: Memory mein changes hain jo abhi disk pe nahi hain\n\n_flush() mein: if not _cache_dirty: return True immediately — bina disk write kiye. Efficient!\n\nPROBLEM YEH SOLVES: Agar 5 baar save_conversation() call ho, bina cache ke 5 disk reads + 5 disk writes. With cache: 1 disk read (first), 5 in-memory updates, 1 disk write (at flush). 9 disk operations → 2. Fast!\n\nRISK: External process file modify kare → cache stale. Acceptable single-writer assumption.","Medium"),

(54,"What is chunking in document storage? Why CHUNK_SIZE=1800 and CHUNK_OVERLAP=250?",
"Chunking = bade document ko chote pieces mein todna.\n\nCHUNK_SIZE=1800 characters kyun:\nLLM context window limited hai. 10 page PDF = 50,000 chars — sab ek saath LLM ko nahi de sakte. 1800 chars ≈ ek paragraph ya ek topic ka section — meaningful unit.\n\nCHUNK_OVERLAP=250 kyun:\nBina overlap ke: '...yeh formula important' [chunk 1 end] | [chunk 2 start] 'isliye result aata hai...'\nChunk boundary pe sentence split ho gayi — dono chunks mein context incomplete hai.\n\n250 chars overlap: Chunk 1 end ke 250 chars Chunk 2 ke shuru mein bhi honge. Sentence kabhi completely lost nahi hogi. Retrieval mein relevant chunk milne ki probability badh jaati hai.\n\nIndustry standard: 100-500 overlap typical hai. 250 balanced choice hai.","Medium"),

(55,"What is TEMP_DOC_TTL_DAYS? How would expiry cleanup be implemented?",
"TTL = Time To Live. Documents 2 din (configurable via env var) ke baad expire ho jaate hain.\n\nKyun: User ne interview PDF upload kiya — Vani ne padhla — 2 din baad irrelevant ho gayi. Storage waste mat karo.\n\nHOW STORED: expires_at = created_at + (2 x 86400 seconds) — UNIX timestamp.\n\nCLEANUP IMPLEMENTATION (2 strategies):\n\nStrategy 1 — On Access:\nJab bhi document retrieve karo, check karo: if expires_at < time.time(): delete and don't return.\nSimple, no background task needed.\n\nStrategy 2 — Periodic Cleanup:\nasyncio.create_task() se background task every hour:\nDELETE FROM temp_documents WHERE expires_at < strftime('%s', 'now')\nCASCADE DELETE automatically temp_document_chunks bhi delete karta hai.","Easy"),

(56,"The _is_conversation_update() uses a 5-minute heuristic. What edge cases does it miss?",
"Heuristic: Agar dono conversations ke beech 5 min se kam time hai aur nayi conversation mein zyada messages hain → update considered.\n\nEDGE CASES YEH MISS KARTA HAI:\n\n1. Two different topics in 4 minutes:\nUser: 'Weather kya hai Patna mein?' (2:00 PM)\nUser: 'Mujhe Python dictionary explain karo' (2:03 PM)\n→ 3 min → WRONGLY merged as update. Unrelated conversations ek ho gayi.\n\n2. Long pause mid-conversation:\nUser: 'Yeh code explain karo' (2:00 PM)\nUser: 'Aur main kya changes karun?' (2:08 PM)\n→ 8 min → NOT merged. Related conversation split ho gayi.\n\n3. Message count manipulation:\nEdit/delete karo messages → count change → wrong merge decision.\n\nBETTER APPROACH: Topic similarity check (embeddings), explicit session markers, user-defined session boundaries.","Hard"),

(57,"Why does _flush() use os.fsync() before os.replace()? What failure does it prevent?",
"3-STEP SAFE WRITE:\n\nStep 1 — json.dump() to .tmp file: Data Python memory se OS buffer mein jaata hai\nStep 2 — f.flush(): OS buffer se kernel page cache mein jaata hai\nStep 3 — os.fsync(): Kernel page cache se PHYSICAL DISK pe jaata hai (hardware level)\nStep 4 — os.replace(): Atomic rename .tmp → .json\n\nFAILURE SCENARIO WITHOUT fsync():\n- f.flush() call kiya — OS ne accept kiya\n- os.replace() call kiya — success return kiya\n- POWER CUT — data abhi bhi RAM (kernel cache) mein tha, disk pe nahi gaya\n- Boot pe: .json file corrupt ya empty\n\nWITH fsync():\n- Physical disk pe guarantee hai data likha gaya\n- Power cut ke baad bhi: Complete data disk pe\n\nCOST: fsync() slow hai (5-20ms). Tradeoff between durability aur speed. Memory log ke liye durability worth it.","Hard"),

(58,"What does get_recent_context(max_messages=30) do? How does flattening affect LLM quality?",
"get_recent_context() kya karta hai:\n1. Sab conversations load karo\n2. Har conversation se messages extract karo (flatten)\n3. Sab messages ek list mein daalo\n4. Last 30 messages return karo\n\nFLATTENING KI PROBLEM:\nConversation 1 (last week): User ne Python poocha tha\nConversation 2 (yesterday): User ne Java poocha tha\nConversation 3 (today): User poocha 'woh wala concept explain karo'\n\nFlattened: Python messages + Java messages + today — LLM ko pata nahi 'woh wala' kaunsa — Python ya Java?\n\nBETTER APPROACH:\n- Conversation boundaries maintain karo with separators\n- Recency-weighted context — recent conversations zyada weight\n- Topic-based retrieval — current query se similar past messages laao (semantic search)","Medium"),

(59,"How would you implement semantic search over stored memories?",
"Current system: Keyword-based — stop words filter ke baad exact word match.\n\nSEMANTIC SEARCH UPGRADE:\n\nStep 1 — Embedding at storage time:\nJab bhi document chunk ya memory save ho: sentence-transformers se 384-dim embedding nikalo, SQLite BLOB column mein store karo.\n\nStep 2 — Schema update:\nALTER TABLE temp_document_chunks ADD COLUMN embedding BLOB;\n\nStep 3 — Query time:\nUser ka question embed karo → stored embeddings se cosine similarity calculate karo → top-5 chunks return karo\n\nStep 4 — Better: FAISS index:\nSabhi embeddings ko FAISS IndexFlatIP mein load karo → approximate nearest neighbor search — 1M chunks mein bhi <10ms.\n\nRESULT: 'Uss wali cheez jo triangle se related thi' → exact keyword nahi hai, lekin semantically similar chunk mil jaata hai.","Hard"),

(60,"What are STOP_WORDS in human_memory.py? Give three Hinglish examples.",
"Stop words = common words jo retrieval mein noise add karte hain — filter kar do.\n\nEnglish examples: 'the', 'and', 'for', 'with', 'that'\nHinglish examples from code: 'hai', 'kya', 'mujhe', 'bata', 'samjha'\n\nWHY REMOVE: Query 'kya hai artificial intelligence' se:\n- Stop words hatao: {'kya', 'hai'} → remaining: 'artificial intelligence'\n- Search: chunks with 'artificial intelligence' — relevant!\n- Without filter: 'kya' aur 'hai' se BAHUT SAARE chunks match honge — useless results\n\n'explain' bhi stop word hai kyunki bahut common instruction word hai — actual topic nahi batata.\n\n'vani', 'rudra' bhi stop words hain — ye Vani ka aur shayad developer ka naam hai — yeh bhi query mein common hain but topic-specific nahi.","Easy"),
]))

# SECTION 7
ALL_SECTIONS.append(("7. Messaging & Social Media Automation", "WhatsApp, Instagram, Telegram, UI automation", [
(61,"What approach does Vanni use for WhatsApp automation? What are the limitations?",
"APPROACH: Browser/Desktop UI Automation — WhatsApp Web ko browser mein open karo, keyboard shortcuts aur pyautogui se control karo.\n\nKaise kaam karta hai:\n1. WhatsApp Web browser mein already open hona chahiye\n2. Contact search ke liye Ctrl+K shortcut ya search box click\n3. Message type karna: type_text_tool se\n4. Send: Enter key press\n\nLIMITATIONS:\n1. WhatsApp Web open + logged in hona ZAROOR hai — har baar manual setup\n2. UI change hogi (WhatsApp update) → automation toot jaayegi\n3. Screenshot-based verification nahi → pata nahi message gaya ya nahi\n4. Rate limiting — bahut fast messages → WhatsApp ban kare\n5. No official API — Terms of Service violation risk\n\nBETTER ALTERNATIVE: WhatsApp Business API (paid, but stable aur official).","Medium"),

(62,"Explain _normalize_whatsapp_contact(). Why do contacts need normalisation?",
"PROBLEM: STT (voice to text) contact names inconsistently produce karta hai:\nUser bolta hai: 'Harshit Upadhyay ko message bhejo'\nWhatsApp search mein: 'Harshit Upadhyay' → NO RESULT (contacts mein sirf 'Harshit' saved)\n\nNORMALIZATION STEPS:\n1. WA_SURNAME_NOISE se surnames strip karo: 'Upadhyay' → remove → 'Harshit'\n2. Title words remove karo: 'bhai', 'ji', 'sir' → 'Shrey bhai' → 'Shrey'\n3. Lowercase karo aur trim karo\n4. Phonetic matching: 'Harshitt' → 'Harshit' (common STT errors)\n\nRESULT: 'Harshit Upadhyay' → 'Harshit' → WhatsApp search mein milega!\n\nEdge case: Common names — 'Sharma ko bhejo' → strip surname → koi name nahi milega. Router ko pehle contact name extract karna chahiye.","Medium"),

(63,"What does _clean_whatsapp_message() do? Give a transformation example.",
"Purpose: User ke complete voice command se SIRF message body extract karo — filler words remove karo.\n\nExamples:\n\nInput: 'Shrey ko WhatsApp pe bhejo kal meeting hai 3 baje'\nAfter _clean_whatsapp_message(): 'kal meeting hai 3 baje'\nRemoved: 'ko', 'WhatsApp pe', 'bhejo'\n\nInput: 'Rahul ko message karo please hi bhai kya scene hai'\nAfter cleaning: 'hi bhai kya scene hai'\nRemoved: 'ko message karo please'\n\nWHAT IT REMOVES (from _SEND_CLEANUP patterns):\n- 'ko message bhejo/karo/send karo'\n- 'ko WhatsApp pe/par'\n- 'please', 'pls', filler words at start\n\nCHALLENGE: 'Bol do please meet karo' — 'please' remove karo lekin 'meet karo' message ka part hai.","Easy"),

(64,"How does Instagram inbox automation work? What function opens it?",
"Instagram ke liye BROWSER-BASED automation hai (koi desktop app nahi):\n\n_ig_open_inbox() flow:\n1. Browser mein https://www.instagram.com/direct/inbox/ open karo\n2. Logged in hai? → inbox dikhega. Nahi → login page → user manually login kare\n\nProfile open flow (_ig_open_profile_by_username()):\n1. _ig_open_inbox() call karo — ensure IG open hai\n2. 1.5 second sleep (page load)\n3. Search bar mein username type karo\n4. Profile pe navigate karo\n\nUsername resolution:\nNickname → real @handle: 'SK' → 'hey_imsk11'\n_ig_resolve_username('SK') → lookup table se real username\n\nLIMITATION: Instagram Web bahut restrictive hai — frequently anti-bot measures update karta hai. Automation brittle hai.","Medium"),

(65,"Why is WA_SURNAME_NOISE a set? How does removing surnames help?",
"SET kyun: O(1) lookup — 'sharma' in WA_SURNAME_NOISE → instantaneous. List mein O(n) hota.\n\nCommon Indian surnames included: sharma, verma, singh, kumar, gupta, agarwal, patel, yadav, pandey, khan...\n\nHELPS KYUN:\nIndian users typically save contacts by first name only in phone. STT full name produce karta hai:\n'Ankit Sharma ko call karo' → WhatsApp mein 'Ankit Sharma' → NOT FOUND\nRemove 'Sharma' → 'Ankit' → FOUND\n\nEDGE CASE 1: Unique surnames: 'Sachin Tendulkar ko message bhejo' — 'Tendulkar' NOT in noise set → full name search → might not find.\n\nEDGE CASE 2: Message contains surname: 'Sharma ji aaj aa rahe hain batao usse' — surname message mein hai, contact extraction ke baad message corrupt ho jaata.","Easy"),

(66,"What does extract_contact_and_payload() do? What ambiguity must it resolve?",
"MAIN CHALLENGE: Ek hi string mein contact name aur message dono hain — kahan split karein?\n\n'Shrey ko bolo kal milte hain coffee pe'\n→ Contact: 'Shrey'\n→ Message: 'kal milte hain coffee pe'\n\nAMBIGUITY:\n'Raj ko batao meeting postpone ho gayi aur Shrey ko bhi bata do'\n→ Contact: 'Raj' ya 'Raj aur Shrey'?\n\nSplitting strategy:\n1. Keyword-based: 'ko bolo', 'ko message karo', 'ko bhejo' ke pehle contact, baad mein message\n2. Named entity recognition: Proper nouns pakdo (harder)\n3. WA_MESSAGE_STARTERS: Agar message 'hi', 'hello', 'ok' se start ho → previous word contact hai\n\nLIMITATION: 'Ananya ko batao Ananya ne kya kiya' → 'Ananya' contact, 'Ananya ne kya kiya' message. First Ananya contact, second Ananya message mein. Tricky!","Hard"),

(67,"What library powers Telegram vs WhatsApp automation?",
"TELEGRAM:\nOfficial MTProto API use hoti hai. Library: Telethon ya Pyrogram (Python libraries).\n\nKya milta hai:\n- telegram_read(): messages directly API se fetch karo\n- telegram_send(): message directly API se bhejo\n- No browser required, no UI automation\n- Reliable, stable, fast\n\nWHATSAPP:\nNO official personal account API. WhatsApp Business API exists (paid, enterprise).\nVani use karta hai: Browser UI automation — WhatsApp Web pe keyboard/mouse control.\n\nYEH DIFFERENCE IMPORTANT HAI:\n- Telegram messages: <100ms (direct API)\n- WhatsApp messages: 2-5s (browser launch, search, type, send)\n- Telegram reliable, WhatsApp fragile (UI changes break it)\n\nAgar WhatsApp ka official API milta, browser automation replace ho jaata immediately.","Medium"),

(68,"How would you make WhatsApp sending more reliable? Three failure modes?",
"FAILURE MODE 1 — Contact not found:\nWhatsApp search mein contact nahi mila (name mismatch)\nFIX: Fuzzy matching (fuzzywuzzy library) — 80% similarity threshold. Try variations: first name only, normalized spelling.\n\nFAILURE MODE 2 — Chat not loaded:\nMessage box click kiya but page fully load nahi hua — click wrong element pe gaya\nFIX: Explicit waits (WebDriverWait conditions). Screenshot le ke verify karo message box visible hai.\n\nFAILURE MODE 3 — Message not sent:\nType kiya, Enter press kiya — lekin koi error pop-up aaya (blocked, no internet)\nFIX: Screenshot after send → check for 'Message sent' tick or error icon. Retry logic with exponential backoff.\n\nBONUS RELIABILITY:\n- Selenium/Playwright use karo pyautogui ke bajaye — DOM-based, more reliable\n- ARIA labels use karo elements find karne ke liye (UI change resistant)\n- Logging har step ka — debug karna easy hoga","Hard"),

(69,"What is WHATSAPP_SHORTCUT intent? Give three examples.",
"WhatsApp Web keyboard shortcuts use karta hai — UI scraping ki zaroorat nahi, sirf keypresses.\n\nWHY SHORTCUTS > UI SEARCH:\n- Faster (0.1s vs 2s)\n- No element finding needed\n- Works even if WhatsApp UI updates (shortcuts stable hain)\n\nEXAMPLES:\n1. next_chat → Ctrl+Tab: 'Agle chat pe jao'\n2. end_call → Escape: 'Call khatam karo'\n3. mute_mic → Ctrl+D: 'Mic mute karo'\n4. archive_chat → Ctrl+E: 'Yeh chat archive karo'\n5. search_chat → Ctrl+F: 'Is chat mein search karo'\n\nwhatsapp_shortcut(action) → press_hotkey_tool(keys) → pyautogui.hotkey()\n\nShortcut-based automation BEST PRACTICE hai automation mein — stable, fast, semantic.","Easy"),

(70,"Why does Instagram profile opener call _ig_open_inbox() first?",
"Session management problem.\n\nInstagram Web ke liye browser mein logged-in session honi chahiye. Agar directly profile URL pe navigate karo bina session check kiye:\n\nSCENARIO 1: Instagram tab already open, logged in → Direct navigation kaam karega\nSCENARIO 2: Instagram tab closed → Browser opens homepage, requires login → Profile navigation fails\n\n_ig_open_inbox() kya karta hai:\n1. instagram.com/direct/inbox/ open karta hai\n2. Session valid hai → inbox load hota hai → logged in confirmed\n3. Fir 1.5s sleep → page fully load ho\n4. Tab ab active aur authenticated\n\nPhir profile navigation smooth hoti hai kyunki session already verified hai.\n\nBETTER IMPLEMENTATION:\nSession health check endpoint ping karo. Ya instagram.com/accounts/login/ detect karo — agar redirect hua matlab logged out.","Medium"),
]))

# SECTION 8
ALL_SECTIONS.append(("8. LLM Integration & Ollama", "Qwen model, prompt engineering, response caching, streaming", [
(71,"Why use a local Ollama model (Qwen2.5:3b) instead of GPT-4?",
"4 strong reasons:\n\n1. PRIVACY:\nUser ki WhatsApp messages, screen content, personal commands → sab local raha. GPT-4 call karo toh yeh data OpenAI ke servers pe jaayega. Unacceptable for personal assistant.\n\n2. ZERO API COST:\nGPT-4 Turbo: ~$10/1M tokens. Agar Vani din mein 200 commands le aur har command 500 tokens = 100K tokens/day = $1/day = $365/year. Local: electricity cost only.\n\n3. OFFLINE CAPABILITY:\nInternet nahi hai? Vani kaam karti rehti hai. Cloud LLM requires internet for every query.\n\n4. TOOL DISPATCH TASK SIMPLE HAI:\nVani ko creative writing ya complex reasoning nahi chahiye. Sirf: 'User ne yeh bola → kaunsa tool → kya arguments?' — 3B model perfectly capable hai is task ke liye.\n\nTRADEOFF: Complex reasoning mein Qwen3B weak — 'iss Python code mein kya bug hai?' GPT-4 better answer dega.","Easy"),

(72,"What is streaming in Ollama API calls? Why does it improve TTFT?",
"Non-streaming (stream=False):\n- Ollama poori response generate karta hai (200 tokens)\n- Sab complete hone ke baad SINGLE response return karta hai\n- TTFT = poori generation time = 1-3 seconds\n\nStreaming (stream=True):\n- Ollama har token generate karte hi immediately send karta hai\n- JSON response ka PEHLA TOKEN aa jaata hai after ~100ms\n- JSON structure hamesha: {'tool': 'tool_name', ... } se start hota hai\n\nOPTIMIZATION:\nJSON tool name typically first 30-40 tokens mein aa jaata hai. Stream parse karo:\nJab 'tool': 'open_application' dekha → dispatch IMMEDIATELY karo.\n\nCode mein: resp.iter_lines() se har line process hoti jaati hai → parts.append(chunk['response']) → join karo.","Medium"),

(73,"Explain _OLLAMA_RESPONSE_CACHE (LRU, maxsize=30). What queries benefit? What's the risk?",
"LRU Cache = Least Recently Used. 30 entries. 31st entry aane pe SABSE PURANI entry evict hoti hai.\n\nQUERIES JO BENEFIT KARTE HAIN:\n- 'Shape of You bajao' — roz same command → Cache hit → 0ms LLM call\n- 'Weather batao' — daily pattern → Cache hit\n- 'YouTube pause karo' — frequent → Cache hit\n\nRISK — STALE CACHE:\n- Morning mein 'news padho' cache hua → news_read tool called → response cached\n- Sham ko user ne news tool REMOVE kiya → lekin cache mein purana response → CRASH on tool execution\n\nANOTHER RISK:\n- 'Shrey ko message bhejo hi' → cached\n- Kal 'Shrey ko message bhejo kya scene hai' → different message → but agar cache hit → 'hi' bhej dega galti se\n\nFIX: Cache key mein arguments include karo ya dynamic content ke commands cache mat karo.","Medium"),

(74,"Analyse the Qwen prompt in _build_qwen_prompt(). Why is 'Respond ONLY with valid JSON' critical?",
"Qwen (aur sabhi LLMs) tend to ADD extra text:\nBina instruction: 'I'll help you with that! Let me open WhatsApp for you. {\"tool\": \"open_application\"...}'\n\nJSON parse karo: json.loads() fail — preamble text JSON nahi hai. Crash.\n\n'ONLY valid JSON' instruction:\nResponse: {\"tool\": \"open_application\", \"args\": {\"app_name\": \"WhatsApp\"}}\njson.loads() → success.\n\nADDITIONAL RULES IN PROMPT:\n'No markdown fences' — ```json ... ``` → JSON parse fail\n'No explanation' — verbose model tendency rok-ta hai\nExample-based few-shot learning — model ko exact format dikhao\n\nEXAMPLE FORMAT IN PROMPT:\n'open example.com' → {\"tool\": \"open_url_in_browser\", \"args\": {\"url\": \"example.com\"}}\n\nYeh format reinforcement sabse effective hai — model dekh-ta hai exact expected output.","Medium"),

(75,"What is the 'hallucinated tool name' problem? How does registry handle it?",
"PROBLEM: Qwen kabhi kabhi tool names INVENT karta hai jo exist nahi karte.\n\nExamples of hallucinated names:\n- 'whatsapp_chats' (real: notifications_read)\n- 'screen_read' (real: read_screen)\n- 'open_whatsapp' (real: open_application with app_name='WhatsApp')\n- 'analyze_screen' (real: read_screen)\n\nWithout aliases: tool = _TOOLS.get('whatsapp_chats') → None → tool nahi mila → kuch nahi hota → user confused.\n\nREGISTRY FIX:\n'whatsapp_chats': notifications_read,  # alias\n'screen_read':    read_screen,         # alias\n'analyze_screen': read_screen,         # alias\n\n_TOOLS.get('whatsapp_chats') → notifications_read function → kaam ho jaata hai.\n\nYeh PRAGMATIC solution hai — ideal world mein LLM fine-tune karo sahi names ke liye.","Hard"),

(76,"How does the codebase decide between immediate dispatch (router) vs queuing (worker)?",
"IMMEDIATE DISPATCH — Router path:\n_router_classify() ek known intent return karta hai → _dispatch_intent() directly call hota hai → kaam hota hai\nNo LLM needed, no queue needed, ~1ms\n\nWORKER QUEUE — Ollama path:\n_router_classify() return karta hai (None, None) → thinking_capability() call hoti hai → LatestWinsQueue mein queue hota hai → _background_worker() Qwen call karta hai\n\nWHEN EACH:\nImmediate: 'YouTube pause karo', 'WhatsApp bhejo Shrey ko hi', 'study shuru karo'\nQueue: 'Mujhe Python dictionary samjhao', 'mere screen pe kya problem hai?', novel/ambiguous commands\n\nHYBRID: Kuch intents router pakad-ta hai (SCREEN_READ, GOOGLE_SEARCH) aur directly dispatch karta hai — Qwen se fast.","Hard"),

(77,"What is VANI_TOOL_SYNC_TIMEOUT (2.0s)? What happens when it fires?",
"SCENARIO: User ne 'mera kal ka schedule batao' bola → Ollama 3 second mein process karta hai → User 3 second silence mein wait kare? Awkward!\n\nSYNC TIMEOUT SOLUTION:\n2 second ke baad thinking_capability() immediately return karta hai: 'Kar rahi hoon, tu bol.'\n\nBackground mein Ollama/tool CONTINUE karta hai apna kaam. Jab result aata hai: future._timed_out = True check → future already resolved → result asyncio.create_task(say_to_user(result)) se directly speak karta hai.\n\nUSER EXPERIENCE:\n0s: User bolta hai command\n2s: Vani bolta hai 'Kar rahi hoon' — user ko pata hai Vani ne suna\n4s: Tool result aata hai — Vani result bolta hai\n\nvs. WITHOUT TIMEOUT:\n0s: Command\n4s: Response — 4 second silence — lagta hai Vani ne suna hi nahi\n\nEnv var se tune karo: VANI_TOOL_SYNC_TIMEOUT=3.0 for slower machines.","Medium"),

(78,"Why do explicit MESSAGING RULES and IMPORTANT RULES exist in the prompt for a capable LLM?",
"3B model (Qwen2.5-3B) is NOT GPT-4. Iske limitations hain:\n\nWITHOUT RULES — WRONG BEHAVIOR:\nUser: 'Harshit ke chats padhao'\nQwen: {\"tool\": \"google_search\", \"args\": {\"query\": \"Harshit chats\"}} WRONG\n\nRULES FIX THESE:\n'X ke chats padhao → whatsapp_read with contact=X' — explicit mapping\n'NEVER use open_youtube_and_play for messaging' — explicit prohibition\n\nFEW-SHOT EXAMPLES work best:\nModel ko abstract rules se better sikhata hai concrete examples. Isliye prompt mein examples section hai.\n\nTECHNICAL: Yeh 'prompt engineering' hai — LLM ka behavior rules aur examples se guide karna. Small models pe yeh CRITICAL hai. Large models (GPT-4) zyada instruction-following capable hain.","Medium"),

(79,"How would you improve LLM response latency from 1-3s to under 500ms?",
"5 strategies:\n\n1. REGEX FIRST (already done): Common commands regex se — 70-80% queries never hit LLM. Biggest win.\n\n2. QUANTIZED MODEL:\nQwen2.5-3B Q4_K_M (4-bit quantized): ~1.5GB RAM instead of 6GB, 2x faster inference. Marginal quality loss for tool dispatch task.\nollama pull qwen2.5:3b-instruct-q4_K_M\n\n3. GPU INFERENCE:\nCPU: 2-3s. GPU (even integrated): 300-500ms. VANI_OLLAMA_GPU=1 flag.\n\n4. PROMPT REDUCTION:\n_TOOL_DESCRIPTIONS 2000+ chars hai. Trim unused tools for common cases. Shorter prompt = fewer tokens to process.\n\n5. STREAMING + EARLY DISPATCH:\n{\"tool\": \"open_app... — pehle 20 tokens mein tool naam aa gaya. Parse karo aur dispatch shuru karo.\n\n6. SMALLER SPECIALIZED MODEL:\nFine-tune ek 1B model sirf tool dispatch ke liye — 80% faster, same accuracy for this specific task.","Hard"),

(80,"What does 'tool: null' response from Qwen mean and how is it handled?",
"{\"tool\": null, \"args\": {}} — Qwen ne decide kiya: koi tool call nahi karna.\n\nScenarios where this happens:\n1. Conversational query: 'Achha, theek hai' — koi action needed nahi\n2. Simple factual question: 'Python kya hai?' — just answer karo\n3. Chitchat: 'Kya haal hai?' — answer dena hai\n\nHANDLING:\n_qwen_decide_and_run() mein:\nif not tool_name: return None / return ''\n\nthinking_capability() return karti hai '' ya None.\n\nVani ke LiveKit session ke main handler ko:\n- '' ya None return aayi toh Vani ka BASE LLM (Gemini) handle karega query ko naturally\n- Vani conversationally respond karti hai — tool bina\n\nGOOD DESIGN: Yeh 'graceful degradation' hai. Koi tool nahi milaa? Vani phir bhi helpful response de sakti hai.","Easy"),
]))

# SECTION 9
ALL_SECTIONS.append(("9. Security & Privacy", "Voice security, fail-open/closed, threat modelling", [
(81,"What is security_state.py responsible for? What states does it likely track?",
"Security_state.py ek STATE MACHINE hai Vani ki security ke liye:\n\nSTATES:\n- UNLOCKED: Normal operation — sab commands accept\n- LOCKED: Sensitive operations blocked — only safe commands allowed\n- VERIFICATION_PENDING: Voice print verify ho raha hai\n- LOCKOUT: Too many failed attempts — temporary ban\n\nWHAT IT TRACKS:\n- Current security state (locked/unlocked)\n- Failed verification attempt count\n- Last verification timestamp\n- Lockout expiry time\n\nTRANSITIONS:\nEnrolled voice detected → UNLOCKED\nWrong voice → failed_count++ → LOCKED (after 3 attempts) → LOCKOUT (15 min)\nVoice enrollment deleted → Always UNLOCKED (fail-open)\n\nCOMMAND FILTERING:\nUNLOCKED: All commands\nLOCKED: Only safe (weather, time, music) — no WhatsApp, no screen read, no sensitive operations","Medium"),

(82,"What is voice_security_prompt.py? What kind of prompts might it contain?",
"Yeh SECURITY-AWARE SYSTEM PROMPTS define karta hai Vani ke liye.\n\nDifferent prompts different security contexts ke liye:\n\nENROLLED + VERIFIED PROMPT:\n'You are Vani, personal assistant. Full access. Read messages, execute all commands.'\n\nENROLLED + UNVERIFIED PROMPT:\n'You are Vani. Security mode active. Do NOT read personal messages. Do NOT execute financial or sensitive commands. Politely ask user to verify their voice first.'\n\nNO ENROLLMENT PROMPT:\n'You are Vani. No voice verification set up. All commands available. Consider setting up voice enrollment for privacy.'\n\nLOCKED OUT PROMPT:\n'Multiple failed verification attempts. Restricted mode. Only non-sensitive commands allowed.'\n\nYeh prompts Gemini realtime model ko bheje jaate hain — iska behavior change karte hain dynamically based on security state.","Medium"),

(83,"What are the security implications of Fail-Open? When is it acceptable?",
"FAIL-OPEN: Verification fail hone pe ACCESS GRANT karo.\n\nVani mein: resemblyzer install nahi → return True → koi bhi command execute kar sakta hai.\n\nSECURITY IMPLICATION:\nAttacker dependency corrupt kar sakta hai (pip uninstall resemblyzer) → Vani fails open → speaker verification BYPASS.\n\nACCEPTABLE SCENARIOS (Fail-Open):\n- Home personal assistant: Inconvenience (Vani band hona) > Security risk\n- Development environment: Frequently dependencies change hoti hain\n- Non-sensitive data: Weather, music — koi data leak nahi\n\nNOT ACCEPTABLE (Fail-Closed needed):\n- Banking transactions: Agar biometric fail → BLOCK, log the incident\n- Medical device access: Safety critical\n- Enterprise data: 'If in doubt, deny'\n- Multi-user household: Siblings Vani use na kar sakein owner ke bina\n\nRULE: Fail-Open when AVAILABILITY > SECURITY. Fail-Closed when SECURITY > AVAILABILITY.","Hard"),

(84,"How does pitch-robust verification mitigate spoofing? What attacks does it NOT prevent?",
"MITIGATES:\nPitch shifting attack: Tu deliberately bahut high ya low pitch mein bolta hai → Single embedding fail → Pitch-robust check: 5 shifts mein se ek toh match karega original pitch pe → CAUGHT.\n\nDOES NOT PREVENT:\n\n1. REPLAY ATTACK:\nKisi ne teri awaaz record ki ('Hey Vani') → Speaker pe replay kiya → Mic ne exact wahi signal capture kiya → Embedding match → Access granted.\n\n2. VOICE CLONING (Deep Fake):\nElevenLabs ya RVC se teri awaaz clone ki → Synthesized 'Vani kholo YouTube' → Very similar embedding → Might pass threshold.\n\n3. ACOUSTIC RELAY ATTACK:\nTeri awaaz Bluetooth speaker pe play kiya side room se.\n\n4. ADVERSARIAL AUDIO:\nSignal processing se engineered audio jo exactly threshold pe similarity produce kare.\n\nMITIGATIONS for above: Liveness detection, anti-spoofing models (AASIST), challenge-response (ask random phrase), ultrasonic watermarks.","Hard"),

(85,"What data is in voiceprint.npy? Privacy implications if stolen?",
"STORED DATA: 256-dimensional float32 numpy array — teri vocal tract ka mathematical representation.\n\nWHAT AN ATTACKER CAN DO with stolen voiceprint:\n1. CHECK IF SOMEONE IS YOU: Teri awaaz record karo → embedding nikalo → cosine similarity against stolen voiceprint → pata chal jaayega 'yeh wahi banda hai'\n2. THRESHOLD CALIBRATION: Jaano exact threshold kya hai\n\nWHAT THEY CANNOT DO:\n1. RECONSTRUCT YOUR VOICE: d-vector one-directional hai — voice recreate nahi kar sakte from numbers.\n2. DIRECTLY BYPASS: Stolen voiceprint ek .npy file hai — Vani ki software mein inject karna padega\n\nREAL RISK LEVEL: Medium. Not your bank password, but biometric data — sensitive.\n\nPROTECTION:\n- File permissions: chmod 600 voiceprint.npy\n- Encrypted at rest\n- Never send over network\n- Include in .gitignore (!!!). Never commit to GitHub.","Hard"),

(86,"How should VOICEPRINT_PATH file be protected at OS level?",
"MINIMUM PROTECTION:\n\n1. FILE PERMISSIONS:\nchmod 600 conversations/voiceprint.npy\n→ Owner read/write only. Nobody else can read.\n\n2. DIRECTORY PERMISSIONS:\nchmod 700 conversations/\n→ Only owner can list/access directory\n\n3. .gitignore:\nconversations/voiceprint.npy\nconversations/*.npy\nCRITICAL: Ek baar GitHub pe push hua → har version mein hai → permanently exposed\n\n4. ENCRYPTION AT REST (advanced):\ncryptography library se encrypt:\nkey = os.urandom(32) (store securely, e.g., keychain)\nFernet(key).encrypt(np.tobytes(voiceprint))\n\n5. MEMORY CLEANUP:\nArrays del karo aur gc.collect() baad mein — RAM forensics se protect\n\n6. SECURE STORAGE (macOS):\nmacOS Keychain mein store karo — hardware-backed encryption","Medium"),

(87,"What is a replay attack in voice authentication? How would you detect it?",
"REPLAY ATTACK:\n1. Attacker records owner saying 'Hey Vani'\n2. Owner nahi hai ghar mein\n3. Attacker speaker pe woh recording play karta hai\n4. Microphone wahi audio capture karta hai\n5. Embedding match → Vani access deti hai\n\nDETECTION METHODS:\n\n1. LIVENESS DETECTION:\nRandom challenge: 'Please say the word: [random word]' har baar alag. Attacker ke paas specific recording nahi hai.\n\n2. ANTI-SPOOFING MODEL (AASIST):\nML model jo LIVE voice vs RECORDED voice distinguish karta hai. Recording artifacts detect karta hai — room acoustics mismatch, compression artifacts.\n\n3. ACOUSTIC ENVIRONMENT:\nBackground noise fingerprint match karo enrollment se. Recording mein different background → different acoustic fingerprint → flag.\n\n4. ULTRASONIC CHALLENGE:\n20kHz ultrasonic tone emit karo, check karo mic ne receive kiya — speaker usually doesn't reproduce ultrasonic frequencies accurately.","Hard"),

(88,"The wake listener shows macOS notifications. What data leakage risk does this create?",
"NOTIFICATION CONTENT LEAK:\n\nScenario: User ka phone locked hai. Koi pass mein hai. Vani 'Reading message from Shrey: Aaj raat 8 baje milte hain' notification dikhata hai.\n\nRISKS:\n1. LOCK SCREEN VISIBILITY: macOS notifications lock screen pe dikhte hain by default — sensitive content publicly visible\n2. NOTIFICATION CENTER: Koi bhi notification center scroll kare → poora history visible\n3. SCREEN RECORDING: Screen recording chal rahi ho (work meeting) → Vani notification record ho jaata hai\n4. SCREENSHOTS: Screenshot mein notification capture ho jaaye\n\nMITIGATIONS:\n1. Sensitive notifications: Content hide karo — 'New WhatsApp message' instead of actual content\n2. macOS Notification Settings: 'Show Previews: When Unlocked' force karo\n3. VANI_MAC_NOTIFICATIONS=0: Completely disable karo agar privacy important hai\n4. Notification pe click required: Direct content dikhana avoid karo","Medium"),
]))

# SECTION 10
ALL_SECTIONS.append(("10. Performance & Optimization", "Latency, concurrency, caching, profiling", [
(89,"What is the total latency budget? Name the main contributors.",
"COMPLETE LATENCY BREAKDOWN:\n\nWake Detection: 50ms (Vosk keyword) / 0ms (double clap — instant)\n\nRouter Classification: <1ms (compiled regex) / 0.1ms typical\n\nOllama/Qwen (if needed): 500ms - 2000ms (3B model, CPU inference)\n\nTool Execution:\n- App open: 200-500ms\n- Browser navigation: 500-2000ms\n- WhatsApp send: 2000-5000ms (UI automation)\n- Google search: 300-800ms\n- Screen read: 500-1000ms (screenshot + Gemini API)\n\nTTS (Vani ka response): 200-400ms (LiveKit realtime)\n\nTOTAL COMMON PATH:\nFast command (regex + simple tool): 300-700ms — EXCELLENT\nMedium command (Qwen + app open): 1.5-3s — ACCEPTABLE\nComplex (Qwen + WhatsApp): 4-8s — NEEDS WORK\n\nTARGET: <2s for 90% of commands. Currently: ~60% under 2s.","Hard"),

(90,"How does LatestWinsQueue reduce perceived latency even when processing is slow?",
"PERCEIVED vs ACTUAL LATENCY:\n\nActual latency: Tool execute hone mein 3 second lagta hai.\nPerceived latency: User ko lagta hai Vani responsive hai.\n\nHOW:\n\n1. IMMEDIATE ACK: thinking_capability() 2 second timeout ke baad 'Kar rahi hoon, tu bol' return karta hai. User ko 2s mein feedback milta hai — not 3s silence.\n\n2. STALE CANCELLATION: User ne 3 commands diye rapidly — purane 2 commands instant cancel. 3rd command immediately execute. User feel karta hai 'Vani ne meri latest instruction suni'.\n\n3. PARALLEL SPEECH: say_to_user() non-blocking hai. Vani result bol rahi hai saath hi saath next command sun sakti hai.\n\nPSYCHOLOGICAL PRINCIPLE:\nHumans time estimate karte hain response count se, duration se nahi. Har 2 second mein ek response = feels faster than 4 second silence then full response.","Medium"),

(91,"_get_parallel_semaphore() recreates semaphore on loop change. What problem if it didn't?",
"PROBLEM: asyncio.Semaphore ek specific event loop se BOUND hota hai — woh loop jab create hua tha.\n\nSCENARIO:\n- LiveKit session start hota hai, Loop A banta hai\n- _parallel_semaphore = asyncio.Semaphore(3) on Loop A\n- LiveKit reconnect → Loop A close → Loop B banta hai\n- Naya tool call aata hai on Loop B\n- async with _parallel_semaphore — YEH CRASH/DEADLOCK\n\nERROR: 'Future attached to different loop' ya silent deadlock — tool kabhi execute nahi hota, Vani freeze.\n\nFIX IN CODE:\nloop = asyncio.get_running_loop()\nif _parallel_semaphore_loop is not loop:\n    _parallel_semaphore = asyncio.Semaphore(_MAX_PARALLEL_TOOLS)  # recreate\n    _parallel_semaphore_loop = loop\n\nHar baar loop check karo. Loop change hoi? Fresh semaphore banao.\n\nYeh LiveKit ka quirk hai — reconnection pe loop change ho sakta hai.","Hard"),

(92,"Why is Ollama semaphore capped at 1 but parallel tools allow 3?",
"DO ALAG RESOURCES:\n\nOLLAMA SEMAPHORE = 1 (sequential):\nQwen3B model RAM mein load hai — ~2-3GB. Ek hi process.\nConcurrent calls = shared context = garbled responses.\nContext window limited — do concurrent queries ek dusre ke context mein interfere.\nResult: Serialized queue — ek query complete hone ke baad doosri shuru.\n\nPARALLEL TOOLS SEMAPHORE = 3 (concurrent):\nTools I/O bound hain:\n- WhatsApp send: Keyboard/mouse operations — CPU idle mostly\n- Google search: Network wait — CPU idle\n- Screen read: Gemini API call — network wait\nI/O bound tasks pe parallelism HUGE speedup deta hai.\n3 concurrent: 3 alag tools simultaneously = 3x throughput.\n\nRULE: CPU-bound (LLM inference) → serialize. I/O-bound (network, disk, UI) → parallelize.","Hard"),

(93,"ConversationMemory has in-memory cache. What is the hidden cost of this optimization?",
"BENEFIT: Disk reads avoid — fast access.\n\nHIDDEN COSTS:\n\n1. MEMORY USAGE:\nHar user ka conversation history RAM mein. 100 users x 1MB average = 100MB RAM permanently occupied. Single-user app pe fine — multi-user pe problem.\n\n2. STALE DATA RISK (main concern):\nExternal process file modify kare (manual edit, backup restore) → Cache stale → Old data serve karo → Data loss.\nSingle-writer assumption must hold.\n\n3. CACHE COHERENCE ON CRASH:\nProgram crash hue bina _flush() call kiye → _cache_dirty = True → changes lost.\nMitigation: signal handlers register karo SIGTERM/SIGINT pe flush karne ke liye.\n\n4. LARGE CONVERSATIONS:\nUser ka 1 year ka history load karo → 50MB in RAM → Memory pressure.\nFix: Sliding window — sirf last N conversations cache karo.","Medium"),

(94,"What is VANI_MAX_PARALLEL_TOOLS? How would you tune it for a low-resource device?",
"Default: 3 (configurable via environment variable)\n\nTUNING GUIDE:\n\nLOW-RAM DEVICE (2GB RAM, Raspberry Pi):\nVANI_MAX_PARALLEL_TOOLS=1\n- Qwen model already 2GB le raha hai\n- Tools mein pyautogui, browser — ye bhi memory lete hain\n- 3 parallel tools = OOM (Out of Memory) crash risk\n- Sequential safe hai\n\nMID-RANGE (4-8GB RAM, normal laptop):\nVANI_MAX_PARALLEL_TOOLS=2-3\n- Sufficient RAM for Qwen + 2-3 I/O tools\n- Most tools I/O bound — parallelism helps\n\nHIGH-END (16GB+ RAM, desktop):\nVANI_MAX_PARALLEL_TOOLS=5\n- Can handle more concurrent operations\n\nCPU CONSIDERATION:\nTool mein CPU-heavy work (OCR, image processing) → reduce parallel count.\nPure network/keyboard tools → increase parallel count safe.","Medium"),

(95,"How does streaming Ollama response improve UX specifically?",
"NON-STREAMING TIMELINE:\n0ms: Query bheja\n1500ms: Poori 200-token response aayi\n1500ms: JSON parse kiya\n1500ms: Tool dispatch start\n\nSTREAMING TIMELINE:\n0ms: Query bheja\n80ms: First tokens aane lage: {\"tool\":\n120ms: Tool name complete: {\"tool\": \"open_application\"\n150ms: Tool call karo IMMEDIATELY — args still streaming\n200-400ms: Remaining args aa rahe hain\nResult: 1500ms → 150ms dispatch start = 10x faster tool initiation!\n\nIMPLEMENTATION DETAIL:\nStreaming JSON parsing tricky hai — partial JSON nahi parse hota.\nStrategy: Tool name extract karo regex se stream mein hi:\nif '\"tool\": \"' in accumulated → naam extract karo immediately.\nFull args ke liye complete JSON wait karo — usually 100-200ms more.","Medium"),
]))

# SECTION 11
ALL_SECTIONS.append(("11. Testing & Quality", "Unit tests, mocking, test strategies from the test suite", [
(96,"What makes speaker verification hard to unit test?",
"5 CHALLENGES:\n\n1. REAL AUDIO REQUIRED:\nFake numpy array se meaningful embedding nahi nikalta. Test ke liye actual voice recordings chahiye. Fixtures maintain karne padte hain.\n\n2. MODEL DEPENDENCY:\nVoiceEncoder load hona chahiye (50MB, 500ms). Unit tests fast hone chahiye — model load slow karta hai. Mock karna complex — NumPy arrays return karne waale mock encoder likhna.\n\n3. CONTINUOUS THRESHOLD:\nsimilarity >= 0.75 → True. Yeh binary nahi hai — threshold tuning test hona chahiye. 0.70, 0.72, 0.75, 0.80 sab test karo alag recordings pe.\n\n4. PITCH VARIATIONS:\nPitch-robust test ke liye: same speaker, alag pitches. 5 variants x multiple speakers = large test fixture set.\n\n5. NON-DETERMINISM:\nResemblyzer internally kuch randomness use karta hai? Exact same audio → same embedding guarantee? Test repeatability ensure karna mushkil.\n\nSOLUTION: pytest fixtures with pre-recorded audio, mocked VoiceEncoder returning known embeddings, parametrized threshold tests.","Hard"),

(97,"How would you mock the Ollama HTTP call in test_optimization.py?",
"MOCKING STRATEGY:\n\nfrom unittest.mock import patch, MagicMock\n\n@patch('vani.reasoning.ollama.requests.post')\ndef test_cache_hit(mock_post):\n    mock_response = MagicMock()\n    mock_response.iter_lines.return_value = [\n        b'{\"response\": \"{\\\\\"tool\\\\\": \\\\\"open_application\\\\\"\", \"done\": false}',\n        b'{\"response\": \", \\\\\"args\\\\\": {}}\", \"done\": true}',\n    ]\n    mock_response.raise_for_status.return_value = None\n    mock_post.return_value = mock_response\n\n    result1 = _call_ollama_sync('Chrome kholo')\n    assert mock_post.call_count == 1\n\n    # Second identical call should hit cache\n    result2 = _call_ollama_sync('Chrome kholo')\n    assert mock_post.call_count == 1  # Still 1 — cache hit!\n    assert result1 == result2\n\nTEST CASES:\n- Cache hit (same query twice)\n- Cache miss (different query)\n- Cache eviction (31+ unique queries)\n- Connection error handling\n- Malformed JSON response","Medium"),

(98,"What should test_intent_classifier.py test for Hinglish inputs?",
"COMPREHENSIVE TEST SUITE:\n\n1. KNOWN PATTERNS:\nassert _router_classify('Shrey ko WhatsApp pe bhejo hi') == ('WHATSAPP_SEND', ('Shrey', 'hi'))\nassert _router_classify('YouTube pause karo') == ('YOUTUBE_PAUSE', None)\nassert _router_classify('meri awaaz register karo') == ('VOICE_ENROLL', {})\n\n2. HINGLISH VARIANTS (same intent, alag phrasing):\n'WhatsApp Shrey ko bhej do hi' → WHATSAPP_SEND\n'Shrey WhatsApp hi bhejo' → WHATSAPP_SEND\n'Bhai Shrey ko message karo hi bol' → WHATSAPP_SEND\n\n3. NEGATIVE CASES (should NOT match):\n'Shrey ka WhatsApp number kya hai?' → NOT WHATSAPP_SEND (question hai)\n\n4. PERFORMANCE:\nimport time; t = time.perf_counter()\nfor _ in range(1000): _router_classify('test query')\nassert (time.perf_counter() - t) < 1.0  # 1000 calls < 1 second\n\n5. EDGE CASES:\nEmpty string, single word, very long query, special characters","Medium"),

(99,"Why is test_browser_control.py hard to write as a pure unit test?",
"BROWSER CONTROL = OS LEVEL OPERATIONS:\n\nWhat browser_control does:\n- pyautogui.hotkey('ctrl', 't') → Actually presses keyboard\n- pyautogui.click(x, y) → Actually clicks mouse\n- subprocess.run(['open', 'http://...']) → Actually opens browser\n\nUNIT TEST PROBLEMS:\n\n1. ACTUAL OS INTERACTION:\nTest machine pe actually browser open ho jaayega. CI/CD pipeline mein (headless server) browser nahi hai → crash.\n\n2. SCREEN COORDINATES:\nclick(850, 400) — yeh coordinates ek machine pe kaam karte hain, doosri pe nahi (different screen resolutions).\n\n3. TIMING DEPENDENCIES:\nBrowser open hone mein 1-2 second — test wait karna padega. Flaky tests.\n\nSOLUTIONS:\n- pyautogui mock karo: patch('pyautogui.hotkey', MagicMock())\n- Virtual display: Xvfb (Linux) ya headless Chrome\n- Integration tests alag rakho unit tests se — only run on actual machine\n- Playwright/Selenium ke saath headless testing","Hard"),

(100,"What testing strategy for LatestWinsQueue to verify Last-Write-Wins?",
"COMPLETE TEST STRATEGY:\n\nimport asyncio, pytest\n\n@pytest.mark.asyncio\nasync def test_last_write_wins():\n    queue = LatestWinsQueue()\n\n    f1 = asyncio.get_event_loop().create_future()\n    f2 = asyncio.get_event_loop().create_future()\n    f3 = asyncio.get_event_loop().create_future()\n\n    queue.put_nowait(('query1', f1))\n    queue.put_nowait(('query2', f2))  # f1 should become STALE\n    queue.put_nowait(('query3', f3))  # f2 should become STALE\n\n    # f1 aur f2 STALE sentinel se resolve honi chahiye\n    assert f1.done() and f1.result() is LatestWinsQueue._STALE\n    assert f2.done() and f2.result() is LatestWinsQueue._STALE\n\n    # Sirf f3 pending honi chahiye\n    assert not f3.done()\n\n    # Worker run karo\n    query, future = await queue.get()\n    assert query == 'query3'  # ONLY latest\n\nTEST ACTIVE TASK CANCELLATION:\nactive_task = asyncio.create_task(asyncio.sleep(10))\nqueue.set_active_task(active_task)\nqueue.put_nowait(('new_query', asyncio.get_event_loop().create_future()))\nassert active_task.cancelled()","Hard"),
]))

# SECTION 12
ALL_SECTIONS.append(("12. System Design & Open-Ended", "Architecture decisions, scalability, future improvements", [
(101,"How would you scale Vanni to 10 simultaneous users? What components change?",
"CURRENT: Single user ke liye designed.\n\nCHANGES NEEDED:\n\n1. ConversationMemory (already user_id keyed — easy):\nHar user ka alag {user_id}_memory.json already hai. Bas concurrent file access lock karo.\n\n2. LatestWinsQueue — PER USER:\nEk global queue nahi — Dict[user_id, LatestWinsQueue] banao. User A ka command User B ko affect nahi karna chahiye.\n\n3. Voiceprint — PER USER:\nconversations/{user_id}/voiceprint.npy. Enrollment flow user_id aware karo.\n\n4. Ollama BOTTLENECK (biggest problem):\nEk Ollama instance = ek query at a time. 10 users simultaneously? 9 wait karte hain.\nSolution A: Ollama instances pool karo (3 instances = 3 concurrent queries)\nSolution B: Per-user queue with fair scheduling\n\n5. Wake Listener:\nPer-user wake word? 'Hey Vani Shrey' vs 'Hey Vani Ananya'. Or same wake word, verify identity after wake.\n\n6. LiveKit Sessions:\nAlready multi-session capable — each user gets own room. Already handles this.","Hard"),

(102,"When would you replace compiled regex with a fine-tuned intent model?",
"CURRENT REGEX WORKS WELL WHEN:\n- Fixed set of commands (<100 intents)\n- Predictable patterns ('play X', 'send to Y')\n- Speed critical (<1ms requirement)\n- Minimal data needed\n\nSWITCH TO ML MODEL WHEN:\n\n1. HINGLISH VARIETY TOO LARGE:\nHar city, har age group alag Hinglish bolti hai. 'Yaar ek kaam kar mera', 'bhai jara YouTube on kar' — infinite variations. Regex impossible.\n\n2. >100 INTENTS:\nRegex file unmaintainable ho jaati hai. 500+ patterns = spaghetti code.\n\n3. COMPOUND QUERIES COMMON:\n'Batao weather aur YouTube pe trending kya hai aaj' — regex se split karna near-impossible.\n\n4. ACCURACY <95%:\nIf regex misses >5% queries → user frustrated → model worth it.\n\nTRADEOFF:\nRegex: 0.1ms, no training data, no server\nModel (DistilBERT fine-tuned): 10-50ms, 1000+ labeled examples, GPU needed\n\nRECOMMENDATION: Hybrid — keep regex for top-30 most common patterns, model for rest.","Hard"),

(103,"Design a better conversation memory with semantic search. What would the schema look like?",
"CURRENT PROBLEM: Keyword search miss karta hai synonyms aur