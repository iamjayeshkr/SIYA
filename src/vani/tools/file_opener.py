"""
vani_file_opener.py — Cross-Platform Edition (Windows + Mac)
Searches Desktop, Documents, Downloads (Mac) or D:/ (Windows) and opens the file.
"""

import os
import sys
import time
import subprocess
import logging
try:
    from rapidfuzz import process
except ImportError:
    from fuzzywuzzy import process
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

_FILE_INDEX_CACHE = None
_FILE_INDEX_TS = 0.0
_FILE_INDEX_TTL = 60.0  # 1-minute TTL

def _default_dirs():
    if IS_MAC:
        home = os.path.expanduser("~")
        return [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Movies"),
            os.path.join(home, "Music"),
        ]
    elif IS_WINDOWS:
        return ["D:/"]
    return [os.path.expanduser("~")]

async def _index_files(base_dirs):
    global _FILE_INDEX_CACHE, _FILE_INDEX_TS
    now = time.time()
    if _FILE_INDEX_CACHE is not None and (now - _FILE_INDEX_TS) < _FILE_INDEX_TTL:
        return _FILE_INDEX_CACHE

    file_index = []
    max_depth = 3
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        base_depth = base_dir.rstrip(os.path.sep).count(os.path.sep)
        for root, dirs, files in os.walk(base_dir):
            # Surgical ignore rules
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '.venv', '.git', '__pycache__')]
            for f in files:
                if not f.startswith('.'):
                    file_index.append({"name": f, "path": os.path.join(root, f)})
            cur_depth = root.rstrip(os.path.sep).count(os.path.sep)
            if cur_depth - base_depth >= max_depth:
                del dirs[:]  # Stop deeper recursion

    logger.info(f"Indexed {len(file_index)} files.")
    _FILE_INDEX_CACHE = file_index
    _FILE_INDEX_TS = now
    return file_index

async def _search_file(query, index):
    choices = [item["name"] for item in index]
    if not choices:
        return None
    res = process.extractOne(query, choices)
    if res:
        best_match, score = res[0], res[1]
        logger.info(f"Matched '{query}' → '{best_match}' (score {score})")
        if score > 70:
            for item in index:
                if item["name"] == best_match:
                    return item
    return None

def _open_file(path: str):
    if IS_MAC:
        subprocess.call(["open", path])
    elif IS_WINDOWS:
        os.startfile(path)
    else:
        subprocess.call(["xdg-open", path])


@tool
async def Play_file(name: str) -> str:
    """
    Searches for and opens a file by name from common locations.
    On Mac: searches Desktop, Documents, Downloads, Movies, Music.
    On Windows: searches D:/ drive.

    Example prompts:
    - "My resume kholo"
    - "project report open karo"
    - "MP4 file chalao"
    - "presentation.pptx open karo"
    """
    dirs  = _default_dirs()
    index = await _index_files(dirs)
    item  = await _search_file(name.strip(), index)

    if item:
        _open_file(item["path"])
        return f"✅ File khul gayi: {item['name']}"
    return f"❌ '{name}' nahi mila. Check karo file Desktop/Documents/Downloads mein hai?"
