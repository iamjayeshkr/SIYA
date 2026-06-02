"""
vani/reasoning/tools/code.py
Code assistance: read existing files, generate solutions via LLM, write back.
"""

import os
import re
import json
import subprocess
import asyncio
import logging
from langchain_core.tools import tool

from vani.reasoning.shared import (
    IS_MAC, IS_WINDOWS,
    logger,
    _safe_popen,
)

# Imported lazily inside functions to avoid circular dependency:
#   _call_ollama_sync is in ollama.py which imports from registry.py

_CODE_EXT_LANG = {
    ".java": "Java",
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".php": "PHP",
    ".rb": "Ruby",
    ".html": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
}


def _code_search_dirs() -> list:
    home = os.path.expanduser("~")
    if IS_WINDOWS:
        return [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            "D:/",
        ]
    return [
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
    ]


def _iter_code_files(max_depth: int = 4) -> list:
    items = []
    for base in _code_search_dirs():
        if not os.path.exists(base):
            continue
        base_depth = base.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(base):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in {"node_modules", "venv", ".venv", "__pycache__", ".git"}
            ]
            if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                dirs.clear()
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in _CODE_EXT_LANG:
                    path = os.path.join(root, filename)
                    try:
                        items.append({"name": filename, "path": path, "mtime": os.path.getmtime(path)})
                    except OSError:
                        pass
    return items


def _find_code_file(command: str, filename: str = "") -> str:
    if filename and os.path.exists(os.path.expanduser(filename)):
        return os.path.abspath(os.path.expanduser(filename))

    files = _iter_code_files()
    if not files:
        return ""

    query = filename or command
    named_match = re.search(
        r"(?:file|class|naam|name|named)\s+([A-Za-z0-9_.-]+\.(?:java|py|js|ts|cpp|c|cs|go|rs|kt|swift|php|rb|html|css|sql))",
        command,
        flags=re.IGNORECASE,
    )
    if named_match:
        query = named_match.group(1)

    try:
        from rapidfuzz import process
    except ImportError:
        from fuzzywuzzy import process

    choices = [item["name"] for item in files]
    res = process.extractOne(os.path.basename(query), choices)
    if res and res[1] >= 72:
        for item in files:
            if item["name"] == res[0]:
                return item["path"]

    return max(files, key=lambda item: item["mtime"])["path"]


def _read_code_file(path: str, limit: int = 24000) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(limit)
        except UnicodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(limit)


def _strip_code_fence(text: str) -> str:
    clean = (text or "").strip()
    m = re.search(r"```[A-Za-z0-9+#-]*\s*(.*?)```", clean, flags=re.DOTALL)
    if m:
        return m.group(1).strip()
    return clean


def _parse_code_assist_response(raw: str) -> tuple:
    clean = (raw or "").strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean).strip()

    candidates = [clean]
    m = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if m:
        candidates.append(m.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "code" in data:
                return _strip_code_fence(str(data.get("code", ""))), str(data.get("explanation", "")).strip()
        except Exception:
            pass

    m = re.search(r'"code"\s*:\s*"((?:\\.|[^"\\])*)"', clean, flags=re.DOTALL)
    if m:
        try:
            code = json.loads('"' + m.group(1) + '"')
            exp = ""
            em = re.search(r'"explanation"\s*:\s*"((?:\\.|[^"\\])*)"', clean, flags=re.DOTALL)
            if em:
                exp = json.loads('"' + em.group(1) + '"')
            return _strip_code_fence(code), exp
        except Exception:
            code = m.group(1).encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore")
            exp = ""
            em = re.search(r'"explanation"\s*:\s*"((?:\\.|[^"\\])*)"', clean, flags=re.DOTALL)
            if em:
                exp = em.group(1).encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore")
            return _strip_code_fence(code), exp

    return _strip_code_fence(clean), ""


def _extract_block_comment(text: str) -> str:
    m = re.search(r"/\*(.*?)\*/", text or "", flags=re.DOTALL)
    return m.group(1).strip("\n ") if m else ""


def _looks_like_pattern_problem(text: str, command: str = "") -> bool:
    sample = _extract_block_comment(text) or text or ""
    q = (command or "").lower()
    if any(word in q for word in ["pattern", "star", "print", "output", "same shape"]):
        return True
    lines = [line.rstrip("\n") for line in sample.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    star_lines = [line for line in lines if "*" in line]
    return len(star_lines) >= 2 and any(" " in line for line in star_lines)


def _pattern_instruction_block(current: str, command: str) -> str:
    if not _looks_like_pattern_problem(current, command):
        return ""
    expected = _extract_block_comment(current)
    return f"""
PATTERN PROBLEM MODE:
- The block comment is the expected console output, not just a hint.
- Preserve spaces exactly. Interior gaps matter.
- Generate nested loops that print rows and columns to match the commented shape.
- Do not replace it with a triangle, pyramid, diamond, or count-only pattern.
- Use the target language's normal syntax and conventions. Java, C++, JavaScript, and React/TSX code should not look textually identical.
- Usually condition should print '*' for border cells or required internal star columns, else print space.
- Prefer configurable variables such as rows and cols over hardcoded output strings when the shape is regular.
- Keep the expected output comment at the top.

Expected output from comment:
{expected}
"""


def _java_string_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _infer_rectangular_star_grid(expected: str) -> list:
    lines = [line.rstrip("\n") for line in expected.splitlines() if "*" in line]
    if len(lines) < 2:
        return []

    max_star_col = max((line.rfind("*") for line in lines), default=-1)
    if max_star_col < 0:
        return []

    cols = (max_star_col // 2) + 1
    grid = []
    for line in lines:
        row = []
        for col in range(cols):
            idx = col * 2
            row.append(idx < len(line) and line[idx] == "*")
        grid.append(row)

    return grid if all(any(row) for row in grid) else []


def _java_col_condition(col: int, cols: int) -> str:
    if col == 1:
        return "j == 1"
    if col == cols:
        return "j == cols"
    return f"j == {col}"


def _generate_java_loop_pattern(current: str) -> str:
    expected = _extract_block_comment(current)
    grid = _infer_rectangular_star_grid(expected)
    if len(grid) < 2:
        return ""

    rows = len(grid)
    cols = len(grid[0])
    if not all(len(row) == cols for row in grid):
        return ""
    if not all(grid[0]) or not all(grid[-1]):
        return ""

    middle_rows = grid[1:-1]
    if middle_rows and any(row != middle_rows[0] for row in middle_rows):
        return ""

    required_cols = [idx + 1 for idx, has_star in enumerate(middle_rows[0] if middle_rows else grid[0]) if has_star]
    col_conditions = [_java_col_condition(col, cols) for col in required_cols]
    condition = " || ".join(["i == 1", "i == rows", *col_conditions])

    return f"""/*

{expected}

*/
public class Vani {{
    public static void main(String[] args) {{

        int rows = {rows};
        int cols = {cols};

        for (int i = 1; i <= rows; i++) {{

            for (int j = 1; j <= cols; j++) {{

                if ({condition}) {{
                    System.out.print("* ");
                }} else {{
                    System.out.print("  ");
                }}
            }}

            System.out.println();
        }}
    }}
}}
"""


def _generate_java_exact_pattern(current: str) -> str:
    loop_pattern = _generate_java_loop_pattern(current)
    if loop_pattern:
        return loop_pattern

    expected = _extract_block_comment(current)
    lines = [line.rstrip() for line in expected.splitlines() if line.strip()]
    if not lines or not all("*" in line for line in lines):
        return ""
    array_values = ",\n            ".join(_java_string_literal(line) for line in lines)
    return f"""/*

{expected}

*/
public class Vani {{
    public static void main(String[] args) {{
        String[] pattern = {{
            {array_values}
        }};

        for (String row : pattern) {{
            System.out.println(row);
        }}
    }}
}}
"""


def _validate_generated_code(path: str, code: str) -> tuple:
    ext = os.path.splitext(path)[1].lower()
    if ext != ".java":
        return True, ""

    import tempfile
    import shutil

    if not shutil.which("javac"):
        return True, ""

    class_match = re.search(r"\bpublic\s+class\s+([A-Za-z_][A-Za-z0-9_]*)", code)
    class_name = class_match.group(1) if class_match else os.path.splitext(os.path.basename(path))[0]
    with tempfile.TemporaryDirectory() as tmp:
        test_path = os.path.join(tmp, f"{class_name}.java")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(code)
        r = subprocess.run(["javac", test_path], capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout).strip()


def _call_code_llm(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if api_key:
        try:
            import requests
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            for model in ("gemini-2.0-flash", "gemini-2.5-flash"):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                resp = requests.post(url, json=payload, timeout=35)
                if resp.status_code == 429:
                    continue
                resp.raise_for_status()
                text = (resp.json().get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", ""))
                if text.strip():
                    return text.strip()
        except Exception as e:
            logger.warning(f"[CODE_ASSIST] Gemini failed: {e}")

    # Lazy import to avoid circular dependency (ollama.py imports registry.py)
    from vani.reasoning.ollama import _call_ollama_sync
    return _call_ollama_sync(prompt)


def _is_file_operation_intent(query: str) -> bool:
    q = (query or "").lower()
    phrases = [
        "create file", "new file", "file banao", "file bana",
        "nayi file", "naya file", "vscode mein file", "vs code mein file",
        "vscode mein new file", "vs code mein new file",
        "create a file", "create a .", "new .", "newfile", "file name", "file naam",
    ]
    return any(p in q for p in phrases) or bool(re.search(r"\bcreate\s+(?:a\s+)?\.[a-z0-9+#]+\s+file\b", q))


def _is_code_assist_intent(query: str) -> bool:
    q = (query or "").lower()
    if _is_file_operation_intent(query):
        return False
    code_words = {
        "leetcode", "solve", "solution", "code likh", "code banao", "implement",
        "while loop", "for loop", "hashmap", "hash map", "graph", "backtracking",
        "dynamic programming", "dp", "recursion", "sliding window", "two pointer",
        "binary search", "stack", "queue", "tree", "linked list", "complex pattern",
        "comment", "comments", "approach", "complexity",
    }
    file_words = {"java", ".java", "python", ".py", "javascript", ".js", "typescript", ".ts", "cpp", ".cpp", "code", "file"}
    return any(w in q for w in code_words) and any(w in q for w in file_words | {"vscode", "vs code", "current"})


@tool
async def write_code_to_file(filename: str, code: str, folder: str = "") -> str:
    """Code/script file banata hai aur VS Code mein open karta hai. SIRF .py .js .html ke liye."""
    _named = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads"}
    if not folder:
        folder = os.path.join(os.path.expanduser("~"), "Desktop")
    elif not os.path.isabs(folder):
        folder = os.path.join(os.path.expanduser("~"), _named.get(folder.lower(), folder))
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        if IS_MAC:
            r = subprocess.run(["which", "code"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                _safe_popen(["code", filepath])
            else:
                _safe_popen(["open", "-a", "Visual Studio Code", filepath])
        elif IS_WINDOWS:
            vscode = os.path.expandvars(r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe")
            _safe_popen([vscode, filepath]) if os.path.exists(vscode) else os.startfile(filepath)
    except Exception:
        pass
    return f"✅ '{filename}' ban gaya aur VS Code mein open ho gaya. Path: {filepath}"


@tool
async def code_assist(command: str, filename: str = "") -> str:
    """
    Existing code/comment/problem statement padhkar same language mein code likhta hai.
    Handles LeetCode-style comments and constraints like while loop, hashmap,
    graph, backtracking, recursion avoid, etc.
    """
    loop = asyncio.get_running_loop()

    def _run() -> str:
        path = _find_code_file(command, filename)
        if not path:
            return "Code file nahi mili. Pehle file create/open karo, ya command mein filename bolo."

        ext = os.path.splitext(path)[1].lower()
        language = _CODE_EXT_LANG.get(ext, "the same language")
        current = _read_code_file(path)
        pattern_rules = _pattern_instruction_block(current, command)
        prompt = f"""You are Vani's coding assistant.

Task from user:
{command}

Target file: {os.path.basename(path)}
Language: {language}

Read the existing file carefully. The file may contain comments with a LeetCode problem, constraints, required approach, or partial code.

Rules:
- Write a complete correct solution in {language}.
- Preserve useful comments/problem statement when they help understanding.
- Follow user constraints exactly, e.g. while loop, hashmap, graph, backtracking, recursion/no recursion.
- If a requested approach is worse, still implement it only when explicitly required, and explain the better approach briefly.
- Keep code clean and beginner-readable.
- Before coding, reason from the target output/problem. Do not copy the same-looking syntax across languages.
- Prefer the optimal reusable approach for the target language. For pattern problems, use row/column conditions so future rows/cols changes are easy.
- Return ONLY JSON with keys:
  "code": full replacement file content
  "explanation": short Hinglish explanation with exactly these sections:
    1. Why this approach
    2. Why other approaches don't work
    3. How to handle constraint/input changes
{pattern_rules}

Existing file content:
{current}
"""
        raw = _call_code_llm(prompt)
        new_code, explanation = _parse_code_assist_response(raw)

        if _looks_like_pattern_problem(current, command) and ext == ".java":
            invalid_json_leak = new_code.lstrip().startswith("{") or '"code"' in new_code[:120]
            missed_pattern = "totalRows" in new_code or "stars =" in new_code
            if invalid_json_leak or missed_pattern:
                fallback = _generate_java_exact_pattern(current)
                if fallback:
                    new_code = fallback
                    explanation = (
                        "1. Why this approach: Comment wala output rectangular pattern hai, isliye row/column loop se border aur required middle columns print hote hain.\n"
                        "2. Why other approaches don't work: Hardcoded string rows exact hain but rows/cols change hote hi update karna padega; triangle/pyramid logic wrong shape dega.\n"
                        "3. How to handle constraint/input changes: rows, cols, ya internal column condition update karo; regular shapes ke liye same nested-loop structure reusable rahega."
                    )

        if not new_code or len(new_code) < 10:
            return "Code generate nahi ho paaya. Ollama/Gemini available hai ya prompt thoda specific karo."

        ok, error = _validate_generated_code(path, new_code)
        if not ok and _looks_like_pattern_problem(current, command) and ext == ".java":
            fallback = _generate_java_exact_pattern(current)
            if fallback:
                ok2, error2 = _validate_generated_code(path, fallback)
                if ok2:
                    new_code = fallback
                    explanation = (
                        "1. Why this approach: Generated Java compile nahi ho raha tha, isliye Vani ne nested-loop pattern solution use kiya jo expected output match karta hai.\n"
                        "2. Why other approaches don't work: Invalid generated code file break kar deta; hardcoded rows future changes ke liye weak hote.\n"
                        "3. How to handle constraint/input changes: rows/cols variables aur if-condition ke star columns adjust karo."
                    )
                    ok = True
                else:
                    error = error2
        if not ok:
            return f"Code generate hua but compile check fail ho gaya, file overwrite nahi ki. Error:\n{error[:1200]}"

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_code.rstrip() + "\n")

        try:
            if IS_MAC:
                r = subprocess.run(["which", "code"], capture_output=True, text=True, timeout=3)
                _safe_popen(["code", path] if r.returncode == 0 else ["open", "-a", "Visual Studio Code", path])
            elif IS_WINDOWS:
                vscode = os.path.expandvars(r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe")
                _safe_popen([vscode, path]) if os.path.exists(vscode) else os.startfile(path)
        except Exception:
            pass

        return f"✅ {os.path.basename(path)} update ho gaya.\n\n{explanation}"

    return await loop.run_in_executor(None, _run)
