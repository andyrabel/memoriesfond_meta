"""
Drafts Facebook post captions via the Anthropic API from structured source
facts — never from a hardcoded template. The model is constrained to the
given facts so it can't invent details, dates, or claims.
"""
import os

import anthropic

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
MAX_CAPTION_WORDS = 60

SYSTEM_PROMPT = (
    "You write short Facebook post captions for a page's scheduled-posting pipeline. "
    "Use only the facts listed below the post type — never invent details, dates, names, "
    "numbers, or claims that aren't present in them. "
    f"Keep the caption under {MAX_CAPTION_WORDS} words, in a warm, direct voice, "
    "and don't add hashtags unless one is explicitly given as a fact. "
    "Respond with the caption text only — no preamble, no quotation marks."
)


def draft_caption(source_facts: dict, post_type: str) -> str:
    facts_text = "\n".join(f"- {k}: {v}" for k, v in source_facts.items()) or "(no facts provided)"
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Post type: {post_type}\n\nFacts:\n{facts_text}\n\nWrite the caption.",
        }],
    )
    return next(block.text for block in response.content if block.type == "text").strip()
