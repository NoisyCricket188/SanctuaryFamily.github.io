#!/usr/bin/env python3
"""
blog_publisher_git.py — publish posts by pushing a folder to a Git repo.

Assumes:
- You have a repo cloned locally (e.g. ~/lumin/family_blog_site)
- The repo has a remote set up (GitHub) with credentials already working.

Usage:
  python3 blog_publisher_git.py --site-repo /home/tricia/lumin/family_blog_site
"""

from __future__ import annotations
from env_bootstrap import load_sanctuary_env
load_sanctuary_env()

import argparse
import shutil
import subprocess
from pathlib import Path

OUTBOX = Path("family_blog/outbox")

def run(cmd, cwd: Path):
    subprocess.run(cmd, cwd=str(cwd), check=False)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-repo", required=True)
    args = ap.parse_args()

    site = Path(args.site_repo).expanduser().resolve()
    posts = site / "posts"
    posts.mkdir(parents=True, exist_ok=True)

    md_files = sorted(OUTBOX.glob("*.md"))
    if not md_files:
        print("⚠️ No posts to publish.")
        return 0

    for f in md_files:
        shutil.copy2(f, posts / f.name)

    run(["git", "add", "."], cwd=site)
    run(["git", "commit", "-m", f"Publish {len(md_files)} Sanctuary posts"], cwd=site)
    run(["git", "push"], cwd=site)

    print(f"✅ Published {len(md_files)} posts.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
