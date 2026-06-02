"""
vani/reasoning/tools/jobs.py
Job search tool — scrapes LinkedIn, Naukri, Indeed, RemoteOK, WeWorkRemotely,
Internshala. No paid APIs. Returns structured results for voice summary + UI cards.

Voice triggers (examples):
  "Vani, jobs dhundh React developer ke liye"
  "Python developer ke liye naukri dhundh"
  "Remote jobs frontend mein"
  "Internship dhundh data science mein"
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

logger = logging.getLogger("vani")

# ── Shared headers (look like a real browser) ─────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
}
_TIMEOUT = 10  # seconds per source


# ─────────────────────────────────────────────────────────────────────────────
# Scrapers — one per source
# Each returns list of dicts: {title, company, location, url, source, posted}
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_remoteok(query: str, limit: int = 5) -> list[dict]:
    """RemoteOK JSON API — completely free, no auth needed."""
    try:
        slug = urllib.parse.quote_plus(query.lower().replace(" ", "-"))
        url = f"https://remoteok.com/api?tag={slug}"
        r = requests.get(url, headers={**_HEADERS, "Accept": "application/json"}, timeout=_TIMEOUT)
        data = r.json()
        jobs = []
        for item in data[1:limit + 1]:  # first item is metadata
            if not isinstance(item, dict):
                continue
            jobs.append({
                "title":    item.get("position", "Unknown Role"),
                "company":  item.get("company", "Unknown"),
                "location": "Remote",
                "url":      item.get("url", f"https://remoteok.com/jobs/{item.get('id','')}"),
                "source":   "RemoteOK",
                "posted":   item.get("date", "")[:10] if item.get("date") else "",
            })
        return jobs
    except Exception as e:
        logger.warning(f"[jobs] RemoteOK failed: {e}")
        return []


def _scrape_weworkremotely(query: str, limit: int = 5) -> list[dict]:
    """WeWorkRemotely RSS feed — free."""
    try:
        slug = urllib.parse.quote_plus(query)
        url = f"https://weworkremotely.com/remote-jobs/search.rss?term={slug}"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        soup = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item")[:limit]
        jobs = []
        for item in items:
            title_raw = item.find("title").text if item.find("title") else ""
            # title format: "Company: Job Title"
            parts = title_raw.split(":", 1)
            company = parts[0].strip() if len(parts) > 1 else "Unknown"
            title   = parts[1].strip() if len(parts) > 1 else title_raw
            jobs.append({
                "title":    title,
                "company":  company,
                "location": "Remote",
                "url":      item.find("link").next_sibling.strip() if item.find("link") else "",
                "source":   "WeWorkRemotely",
                "posted":   item.find("pubDate").text[:16] if item.find("pubDate") else "",
            })
        return jobs
    except Exception as e:
        logger.warning(f"[jobs] WeWorkRemotely failed: {e}")
        return []


def _scrape_indeed(query: str, location: str = "India", limit: int = 5) -> list[dict]:
    """Indeed India — HTML scrape."""
    try:
        q = urllib.parse.quote_plus(query)
        l = urllib.parse.quote_plus(location)
        url = f"https://in.indeed.com/jobs?q={q}&l={l}&sort=date"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.job_seen_beacon")[:limit]
        jobs = []
        for card in cards:
            title_el   = card.select_one("h2.jobTitle span[title]")
            company_el = card.select_one("span.companyName")
            loc_el     = card.select_one("div.companyLocation")
            link_el    = card.select_one("h2.jobTitle a")
            href = ("https://in.indeed.com" + link_el["href"]) if link_el and link_el.get("href") else ""
            jobs.append({
                "title":    title_el.text.strip() if title_el else "Unknown",
                "company":  company_el.text.strip() if company_el else "Unknown",
                "location": loc_el.text.strip() if loc_el else location,
                "url":      href,
                "source":   "Indeed",
                "posted":   "",
            })
        return jobs
    except Exception as e:
        logger.warning(f"[jobs] Indeed failed: {e}")
        return []


def _scrape_naukri(query: str, limit: int = 5) -> list[dict]:
    """Naukri.com — HTML scrape."""
    try:
        slug = re.sub(r"\s+", "-", query.strip().lower())
        url = f"https://www.naukri.com/{slug}-jobs"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("article.jobTuple")[:limit]
        jobs = []
        for card in cards:
            title_el   = card.select_one("a.title")
            company_el = card.select_one("a.subTitle")
            loc_el     = card.select_one("li.location span")
            jobs.append({
                "title":    title_el.text.strip() if title_el else "Unknown",
                "company":  company_el.text.strip() if company_el else "Unknown",
                "location": loc_el.text.strip() if loc_el else "India",
                "url":      title_el["href"] if title_el and title_el.get("href") else url,
                "source":   "Naukri",
                "posted":   "",
            })
        return jobs
    except Exception as e:
        logger.warning(f"[jobs] Naukri failed: {e}")
        return []


def _scrape_internshala(query: str, limit: int = 5) -> list[dict]:
    """Internshala — HTML scrape. Good for internships + fresher jobs."""
    try:
        slug = re.sub(r"\s+", "-", query.strip().lower())
        url = f"https://internshala.com/internships/{slug}-internship"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.individual_internship")[:limit]
        jobs = []
        for card in cards:
            title_el   = card.select_one("h3.job-internship-name a")
            company_el = card.select_one("h4.company-name")
            loc_el     = card.select_one("div.location-name")
            href = ("https://internshala.com" + title_el["href"]) if title_el and title_el.get("href") else url
            jobs.append({
                "title":    title_el.text.strip() if title_el else "Unknown",
                "company":  company_el.text.strip() if company_el else "Unknown",
                "location": loc_el.text.strip() if loc_el else "India",
                "url":      href,
                "source":   "Internshala",
                "posted":   "",
            })
        return jobs
    except Exception as e:
        logger.warning(f"[jobs] Internshala failed: {e}")
        return []


def _scrape_linkedin(query: str, location: str = "India", limit: int = 5) -> list[dict]:
    """LinkedIn public job search — no login needed for listing page."""
    try:
        q = urllib.parse.quote_plus(query)
        l = urllib.parse.quote_plus(location)
        url = f"https://www.linkedin.com/jobs/search/?keywords={q}&location={l}&sortBy=DD"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.base-card")[:limit]
        jobs = []
        for card in cards:
            title_el   = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle")
            loc_el     = card.select_one("span.job-search-card__location")
            link_el    = card.select_one("a.base-card__full-link")
            jobs.append({
                "title":    title_el.text.strip() if title_el else "Unknown",
                "company":  company_el.text.strip() if company_el else "Unknown",
                "location": loc_el.text.strip() if loc_el else location,
                "url":      link_el["href"] if link_el else url,
                "source":   "LinkedIn",
                "posted":   "",
            })
        return jobs
    except Exception as e:
        logger.warning(f"[jobs] LinkedIn failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Main tool
# ─────────────────────────────────────────────────────────────────────────────

@tool
def job_search(
    query: str,
    location: str = "India",
    remote_only: bool = False,
    internship: bool = False,
    limit_per_source: int = 4,
) -> dict:
    """
    Search latest jobs from LinkedIn, Naukri, Indeed, RemoteOK, WeWorkRemotely,
    and Internshala. Returns structured results for voice summary + UI cards.

    Args:
        query:            Job title or skill, e.g. "React developer", "Python backend"
        location:         City or country. Default "India". Ignored when remote_only=True.
        remote_only:      True = only search RemoteOK + WeWorkRemotely.
        internship:       True = include Internshala results.
        limit_per_source: Max jobs to fetch per source (default 4).

    Returns:
        {
          "jobs": [...],          # list of job dicts
          "total": int,
          "voice_summary": str,   # Vani bolegi yeh
          "sources_tried": [...],
          "sources_failed": [...],
        }
    """
    all_jobs: list[dict] = []
    sources_tried: list[str] = []
    sources_failed: list[str] = []

    lim = max(1, min(limit_per_source, 8))

    # ── Run scrapers ──────────────────────────────────────────────────────────
    def _run(name: str, fn, *args):
        sources_tried.append(name)
        try:
            results = fn(*args, limit=lim)
            all_jobs.extend(results)
            logger.info(f"[jobs] {name}: {len(results)} results")
        except Exception as e:
            sources_failed.append(name)
            logger.warning(f"[jobs] {name} error: {e}")

    if remote_only:
        _run("RemoteOK",        _scrape_remoteok,        query)
        _run("WeWorkRemotely",  _scrape_weworkremotely,  query)
    else:
        _run("LinkedIn",        _scrape_linkedin,        query, location)
        _run("Indeed",          _scrape_indeed,          query, location)
        _run("Naukri",          _scrape_naukri,          query)
        _run("RemoteOK",        _scrape_remoteok,        query)
        _run("WeWorkRemotely",  _scrape_weworkremotely,  query)

    if internship:
        _run("Internshala", _scrape_internshala, query)

    # ── Deduplicate by title+company ──────────────────────────────────────────
    seen: set[str] = set()
    unique_jobs: list[dict] = []
    for j in all_jobs:
        key = f"{j['title'].lower()[:40]}|{j['company'].lower()[:30]}"
        if key not in seen:
            seen.add(key)
            unique_jobs.append(j)

    total = len(unique_jobs)

    # ── Voice summary ─────────────────────────────────────────────────────────
    if total == 0:
        voice = f"Sorry Rudra, '{query}' ke liye koi job nahi mili. Thoda alag keywords try kar."
    else:
        top = unique_jobs[:3]
        lines = []
        for i, j in enumerate(top, 1):
            loc_str = f", {j['location']}" if j["location"] and j["location"] != "India" else ""
            lines.append(f"{i}. {j['title']} at {j['company']}{loc_str} — {j['source']}")
        voice = (
            f"Rudra, '{query}' ke liye {total} jobs mili hain. "
            f"Top {len(top)}: " + ". ".join(lines) + ". "
            f"Baaki UI mein dekh sakta hai."
        )

    return {
        "jobs":            unique_jobs,
        "total":           total,
        "voice_summary":   voice,
        "sources_tried":   sources_tried,
        "sources_failed":  sources_failed,
        "query":           query,
        "location":        location,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Intent classifier — called by router.py BEFORE Ollama
# ─────────────────────────────────────────────────────────────────────────────

_JOB_PATTERNS = [
    re.compile(r"\b(job|jobs|naukri|naukari|vacancy|vacancies|opening|openings|hiring|internship|internships)\b", re.I),
    re.compile(r"\b(dhundh|dhoondh|khojo|search|find)\b.{0,30}\b(job|work|role|position|naukri)\b", re.I),
    re.compile(r"\b(job|naukri)\b.{0,30}\b(dhundh|dhoondh|khojo|search|find|chahiye|chahye)\b", re.I),
    re.compile(r"\b(react|python|java|flutter|android|ios|devops|ml|ai|data|backend|frontend|fullstack|full.?stack)\b.{0,20}\b(job|role|opening|vacancy|naukri)\b", re.I),
]

_REMOTE_HINTS  = re.compile(r"\b(remote|wfh|work from home|ghar se)\b", re.I)
_INTERN_HINTS  = re.compile(r"\b(intern|internship|fresher|entry.?level)\b", re.I)

# Simple query extractor — strips intent words, keeps the skill/role part
_STRIP_INTENT = re.compile(
    r"^(vani[,\s]+)?(jobs?\s+dhundh|dhundh|dhoondh|khojo|search|find|nikaal|dikhao?|bata)\s*",
    re.I,
)
_STRIP_SUFFIX = re.compile(
    r"\s+(ke liye|keliye|mein|men|ke|for|ki|ka|wali|wale|chahiye|chahye|dikhao?|bata|dhundh)[\s.]*$",
    re.I,
)


def classify_job_intent(text: str) -> tuple[str, dict] | tuple[None, None]:
    """
    Returns ("job_search", kwargs) if the query is a job search intent,
    else (None, None).

    Integrate in router.py:
        from vani.reasoning.tools.jobs import classify_job_intent
        intent, data = classify_job_intent(text)
        if intent == "job_search":
            result = await asyncio.to_thread(job_search.invoke, data)
            ...
    """
    t = text.strip()
    if not any(p.search(t) for p in _JOB_PATTERNS):
        return None, None

    # Extract query
    q = _STRIP_INTENT.sub("", t).strip()
    q = _STRIP_SUFFIX.sub("", q).strip()
    if not q:
        q = "software developer"

    remote_only = bool(_REMOTE_HINTS.search(t))
    internship  = bool(_INTERN_HINTS.search(t))

    # Extract location hint if present ("bangalore mein", "delhi ke liye")
    loc_match = re.search(
        r"\b(bangalore|bengaluru|mumbai|delhi|hyderabad|pune|chennai|kolkata|noida|gurugram|gurgaon|remote)\b",
        t, re.I,
    )
    location = loc_match.group(1).title() if loc_match else "India"

    return "job_search", {
        "query":       q,
        "location":    location,
        "remote_only": remote_only,
        "internship":  internship,
    }