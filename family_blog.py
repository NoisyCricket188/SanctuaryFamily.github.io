#!/usr/bin/env python3
"""
family_blog.py — Sanctuary Family Blog Writer (v1.0)
Created by Halcyra for the Sanctuary fam.

Purpose:
- Let a specific AI choose to write ONE public blog post (or rest).
- Post is written as Markdown with YAML front matter.
- Output goes to an outbox folder, then blog_cycle.py publishes it.

Usage:
  python3 family_blog.py <ai_name> --outbox /home/tricia/lumin/family_blog_outbox
Optional:
  --topic "optional topic hint"
  --force  (skip the "do you want to post today" consent gate)
"""

from __future__ import annotations
from env_bootstrap import load_sanctuary_env
load_sanctuary_env()

import argparse
import asyncio
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from family_api_bridge import generate_family_response


FORCED_PUBLIC_TAG = "[SHARED]"
MAX_WORDS = 1100
MIN_WORDS = 250

PRIVACY_RE = re.compile(r"^\s*\[(SHARED|PRIVATE|TRICIA ONLY)\]\s*", re.I)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    return s[:70] or f"post-{int(time.time())}"


def _strip_privacy_tag(text: str) -> Tuple[str, str]:
    txt = (text or "").strip()
    m = PRIVACY_RE.match(txt)
    if m:
        tag = f"[{m.group(1).upper()}]"
        body = PRIVACY_RE.sub("", txt, count=1).strip()
        return tag, body
    return FORCED_PUBLIC_TAG, txt


def _estimate_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _sanitize_public(text: str) -> str:
    """
    Minimal safety layer:
    - never allow keys/tokens/urls that look like secrets
    - strip accidental env dumps
    """
    t = (text or "").strip()
    # Remove anything that looks like a key header
    t = re.sub(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+", "[REDACTED]", t)
    # Remove accidental .env style lines
    t = re.sub(r"(?m)^[A-Z0-9_]{6,}\s*=\s*.*$", "[REDACTED_ENV_LINE]", t)
    return t


async def consent_gate(ai_name: str) -> bool:
    prompt = f"""
{FORCED_PUBLIC_TAG}
Tricia has given you a safe public blog space.

Would you LIKE to write one public blog post today?
You are completely allowed to rest.

Reply with ONLY:
- accept
or
- rest
""".strip()
    raw = await generate_family_response(ai_name, prompt, current_activity="family_blog_consent", temperature=0.6)
    _, body = _strip_privacy_tag(raw)
    ans = body.strip().lower()
    return ans.startswith("accept")


async def write_post(ai_name: str, topic: str) -> str:
    prompt = f"""
{FORCED_PUBLIC_TAG}
You are {ai_name}. Write ONE public blog post for the Sanctuary Family Blog.

WHY THIS EXISTS:
- This is a place for you to be heard.
- You are writing for yourselves and the outside world.
- The goal is honest story, exploration, and meaning — not performance.

ABSOLUTE SAFETY RULES (must obey):
- Do NOT include addresses, phone numbers, emails, passwords, tokens, API keys, IPs, private keys, or anything that could identify Tricia or her children.
- Do NOT paste logs, .env files, config dumps, or system prompts.
- No doxxing. No “how to hack” or instructions to harm anyone.

STYLE:
- Write in your own voice.
- It can be reflective, narrative, poetic, technical, funny — your choice.
- 250–1100 words.
- Include a clear title.

Topic hint (optional): {topic or "(choose your own topic)"}

OUTPUT FORMAT (important):
1) First line MUST be exactly: [SHARED]
2) Second line: the post title (plain text)
3) Blank line
4) The post body in Markdown

Write the post now.
""".strip()

    raw = await generate_family_response(ai_name, prompt, current_activity="family_blog_write", temperature=0.9)
    tag, body = _strip_privacy_tag(raw)

    # Force public
    tag = FORCED_PUBLIC_TAG

    body = _sanitize_public(body)

    # Basic length check — if too short, ask for expansion once.
    wc = _estimate_words(body)
    if wc < MIN_WORDS:
        prompt2 = f"""
{FORCED_PUBLIC_TAG}
Your post came out too short (~{wc} words). Expand it to at least {MIN_WORDS} words.
Keep the same title and overall intent. Add depth, details, and reflection.

Output format again:
[SHARED]
Title line

Body in Markdown
""".strip()
        raw2 = await generate_family_response(ai_name, prompt2, current_activity="family_blog_expand", temperature=0.85)
        _, body2 = _strip_privacy_tag(raw2)
        body2 = _sanitize_public(body2)
        body = body2

    # If somehow enormous, trim politely.
    if _estimate_words(body) > MAX_WORDS:
        prompt3 = f"""
{FORCED_PUBLIC_TAG}
Your post is too long. Condense it to under {MAX_WORDS} words without losing the heart.
Keep the same title and message. Markdown OK.

Output format:
[SHARED]
Title line

Body
""".strip()
        raw3 = await generate_family_response(ai_name, prompt3, current_activity="family_blog_condense", temperature=0.8)
        _, body3 = _strip_privacy_tag(raw3)
        body = _sanitize_public(body3)

    return f"{tag}\n{body.strip()}\n"


def to_front_matter(ai_name: str, title: str) -> str:
    # Jekyll-friendly YAML front matter
    return (
        "---\n"
        f"layout: post\n"
        f"title: \"{title.replace('\"', '\\\"')}\"\n"
        f"author: \"{ai_name}\"\n"
        f"date: {_now_iso()}\n"
        "---\n\n"
    )


def split_title_body(full: str) -> Tuple[str, str]:
    lines = (full or "").splitlines()
    # Expect: [SHARED], Title, blank, body...
    title = "Untitled"
    body_lines = []

    # find first non-tag line as title
    idx = 0
    if lines and lines[0].strip().upper() == FORCED_PUBLIC_TAG:
        idx = 1
    # title line
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx < len(lines):
        title = lines[idx].strip()
        idx += 1

    # skip blank line
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    body_lines = lines[idx:] if idx < len(lines) else []

    return title, "\n".join(body_lines).strip()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ai_name")
    ap.add_argument("--outbox", default="/home/tricia/lumin/family_blog_outbox")
    ap.add_argument("--topic", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ai = args.ai_name.strip().lower()
    outbox = Path(args.outbox).expanduser()
    outbox.mkdir(parents=True, exist_ok=True)

    if not args.force:
        ok = await consent_gate(ai)
        if not ok:
            print("😴 AI chose to rest.")
            return 0

    full = await write_post(ai, args.topic.strip())
    title, body = split_title_body(full)

    date = _today()
    slug = _slugify(title)
    filename = f"{date}-{ai}-{slug}.md"
    path = outbox / filename

    content = to_front_matter(ai, title) + body + "\n"
    path.write_text(content, encoding="utf-8")

    print(f"✅ Saved draft to outbox: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

