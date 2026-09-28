"""Repo Radar Datensammler.

Ruft GitHub Trending (Woche und Monat) ab, ergaenzt jedes Repo mit Daten aus
der GitHub API und speichert alles als JSON in data/.
"""
import base64
import datetime as dt
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (repo-radar)"}
TOKEN = os.environ.get("GITHUB_TOKEN")
API_HEADERS = {"Accept": "application/vnd.github+json", **UA}
if TOKEN:
    API_HEADERS["Authorization"] = f"Bearer {TOKEN}"

README_CHARS = int(os.environ.get("README_CHARS", "3000"))
FETCH_README = os.environ.get("FETCH_README", "1") == "1"


def to_int(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def fetch_trending(since):
    url = f"https://github.com/trending?since={since}"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    repos = []
    for rank, art in enumerate(soup.select("article.Box-row"), 1):
        link = art.select_one("h2 a")
        if not link:
            continue
        name = link["href"].strip("/")
        desc = art.select_one("p")
        lang = art.select_one('[itemprop="programmingLanguage"]')
        stars = art.select_one('a[href$="/stargazers"]')
        forks = art.select_one('a[href$="/forks"]')
        gain = art.select_one("span.float-sm-right")
        repos.append({
            "rank": rank,
            "repo": name,
            "description": desc.get_text(" ", strip=True) if desc else "",
            "language": lang.get_text(strip=True) if lang else None,
            "stars": to_int(stars.get_text()) if stars else None,
            "forks": to_int(forks.get_text()) if forks else None,
            "gain": to_int(gain.get_text()) if gain else None,
        })
    if not repos:
        raise RuntimeError(f"Keine Repos auf {url} gefunden")
    return repos


def fetch_api(repo):
    r = requests.get(f"https://api.github.com/repos/{repo}", headers=API_HEADERS, timeout=30)
    if r.status_code == 404:
        return {"status": 404}
    if r.status_code != 200:
        return {"status": r.status_code, "error": r.text[:200]}
    d = r.json()
    info = {
        "status": 200,
        "stargazers_count": d.get("stargazers_count"),
        "description": d.get("description"),
        "created_at": d.get("created_at"),
        "pushed_at": d.get("pushed_at"),
        "topics": d.get("topics", []),
        "homepage": d.get("homepage"),
        "archived": d.get("archived"),
        "license": (d.get("license") or {}).get("spdx_id"),
    }
    if FETCH_README:
        rr = requests.get(f"https://api.github.com/repos/{repo}/readme", headers=API_HEADERS, timeout=30)
        if rr.status_code == 200:
            try:
                text = base64.b64decode(rr.json().get("content", "")).decode("utf-8", "ignore")
                info["readme_excerpt"] = text[:README_CHARS]
            except Exception:
                info["readme_excerpt"] = None
        else:
            info["readme_excerpt"] = None
    return info


def main():
    now = dt.datetime.now(dt.timezone.utc)
    week = fetch_trending("weekly")
    month = fetch_trending("monthly")

    names = sorted({r["repo"] for r in week} | {r["repo"] for r in month})
    details = {}
    for name in names:
        details[name] = fetch_api(name)
        time.sleep(0.2)

    iso = now.isocalendar()
    out = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "iso_week_running": f"{iso[0]}-W{iso[1]:02d}",
        "authenticated": bool(TOKEN),
        "weekly": week,
        "monthly": month,
        "details": details,
    }
    os.makedirs("data", exist_ok=True)
    for path in ("data/latest.json", f"data/raw-{out['date']}.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    ok = sum(1 for d in details.values() if d.get("status") == 200)
    print(f"Woche: {len(week)} Repos, Monat: {len(month)} Repos, API ok: {ok}/{len(details)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        sys.exit(1)
