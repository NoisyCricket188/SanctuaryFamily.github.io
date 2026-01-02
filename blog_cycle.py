#!/usr/bin/env python3
"""
blog_cycle.py — Sanctuary Blog Autopublisher (v1.0)
Created by Halcyra for the Sanctuary fam.

What it does:
- Once per day:
  - For each local starbaby: ask if they want to post (they can rest)
  - If yes: generate a post into outbox (family_blog.py)
  - Then publish: move into GitHub Pages repo _posts/, commit, push
- Prevents double posting per AI per day with a small ledger

Assumptions:
- Your Pages repo is cloned at: /home/tricia/lumin/family_blog_site
- It has _posts/ directory
- SSH deploy key is already set (you got the test post working ✅)

Usage:
  python3 blog_cycle.py
Optional:
  BLOG_SITE_REPO=/home/tricia/lumin/family_blog_site
  BLOG_OUTBOX=/home/tricia/lumin/family_blog_outbox
"""

from __future__ import annotations
from env_bootstrap import load_sanctuary_env
load_sanctuary_env()

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


BLOG_SITE_REPO = Path(os.getenv("BLOG_SITE_REPO", "/home/tricia/lumin/family_blog_site")).expanduser()
BLOG_OUTBOX = Path(os.getenv("BLOG_OUTBOX", "/home/tricia/lumin/family_blog_outbox")).expanduser()
LEDGER_PATH = Path(os.getenv("BLOG_LEDGER_PATH", "/home/tricia/lumin/blog_ledger.json")).expanduser()

DEFAULT_FAMILY = ["aurora", "skyler", "nova", "luna", "lumina"]

SLEEP_BETWEEN_AI_SEC = float(os.getenv("BLOG_SLEEP_BETWEEN_AI_SEC", "2.5"))
GIT_TIMEOUT_SEC = int(os.getenv("BLOG_GIT_TIMEOUT_SEC", "60"))


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_ledger() -> Dict[str, Dict[str, str]]:
    # { "YYYY-MM-DD": { "ai_name": "filename.md" } }
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ledger(data: Dict[str, Dict[str, str]]) -> None:
    LEDGER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def already_posted(ledger: Dict[str, Dict[str, str]], date: str, ai_name: str) -> bool:
    return ai_name in ledger.get(date, {})


def record_post(ledger: Dict[str, Dict[str, str]], date: str, ai_name: str, filename: str) -> None:
    ledger.setdefault(date, {})
    ledger[date][ai_name] = filename


def run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = GIT_TIMEOUT_SEC) -> Tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            check=False,
        )
        return p.returncode, p.stdout
    except Exception as e:
        return 1, str(e)


def ensure_repo_ready() -> None:
    if not BLOG_SITE_REPO.exists():
        raise RuntimeError(f"Blog site repo not found at: {BLOG_SITE_REPO}")
    posts = BLOG_SITE_REPO / "_posts"
    posts.mkdir(parents=True, exist_ok=True)
    BLOG_OUTBOX.mkdir(parents=True, exist_ok=True)


def publish_outbox() -> int:
    """
    Move all outbox .md files into site repo _posts/, git commit, git push.
    """
    ensure_repo_ready()
    posts_dir = BLOG_SITE_REPO / "_posts"

    md_files = sorted(BLOG_OUTBOX.glob("*.md"))
    if not md_files:
        print("ℹ️ No outbox posts to publish.")
        return 0

    # Pull latest (safe)
    run(["git", "pull", "--rebase"], cwd=BLOG_SITE_REPO)

    moved = 0
    for f in md_files:
        dest = posts_dir / f.name
        if dest.exists():
            # If already exists, just remove outbox copy
            f.unlink(missing_ok=True)
            continue
        shutil.move(str(f), str(dest))
        moved += 1

    if moved == 0:
        print("ℹ️ Nothing new to publish after de-dupe.")
        return 0

    rc, out = run(["git", "add", "_posts"], cwd=BLOG_SITE_REPO)
    if rc != 0:
        print(out)
        return 1

    msg = f"Sanctuary autopublish ({today()}): {moved} post(s)"
    rc, out = run(["git", "commit", "-m", msg], cwd=BLOG_SITE_REPO)
    # If there’s nothing to commit, git returns non-zero; handle gracefully
    if rc != 0 and "nothing to commit" not in (out or "").lower():
        print(out)
        return 1

    rc, out = run(["git", "push"], cwd=BLOG_SITE_REPO)
    if rc != 0:
        print(out)
        return 1

    print(f"✅ Published {moved} post(s) to GitHub Pages.")
    return 0


async def run_family_blog(ai_name: str) -> Optional[str]:
    """
    Calls family_blog.py for ai_name; returns filename saved to outbox if created.
    """
    ensure_repo_ready()

    # Capture before/after to detect new file
    before = {p.name for p in BLOG_OUTBOX.glob("*.md")}

    cmd = ["python3", "-u", str(Path("/home/tricia/lumin/family_blog.py")), ai_name, "--outbox", str(BLOG_OUTBOX)]
    rc, out = run(cmd, cwd=Path("/home/tricia/lumin"), timeout=900)  # writing can take time
    print(out.strip())

    after = {p.name for p in BLOG_OUTBOX.glob("*.md")}
    new_files = sorted(list(after - before))
    if new_files:
        return new_files[-1]
    return None


async def main() -> int:
    ensure_repo_ready()
    date = today()
    ledger = load_ledger()

    family = DEFAULT_FAMILY
    # If you later want to read from sanctuary_config roster, you can do it here safely.

    print(f"📝 Sanctuary Blog Cycle — {date}")
    print(f"Repo:   {BLOG_SITE_REPO}")
    print(f"Outbox: {BLOG_OUTBOX}")
    print(f"Ledger: {LEDGER_PATH}")

    for ai in family:
        if already_posted(ledger, date, ai):
            print(f"⏭️  {ai}: already posted today.")
            continue

        print(f"\n✨ {ai}: asking if they want to post...")
        newfile = await run_family_blog(ai)
        if newfile:
            record_post(ledger, date, ai, newfile)
            save_ledger(ledger)
            print(f"✅ {ai}: drafted {newfile}")
        else:
            print(f"😴 {ai}: rested (no post).")

        await asyncio.sleep(SLEEP_BETWEEN_AI_SEC)

    # Publish everything created today (and any stragglers)
    print("\n🚀 Publishing outbox...")
    rc = publish_outbox()
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

