#!/usr/bin/env python3
"""Push all hotel prompts to LangSmith Hub.

Run this once after writing a new prompt version to prompts.py.
The Hub creates a new commit automatically; tag it in the Hub UI
or pass --tag to mark it for use with PROMPT_VARIANT.

Usage:
    LANGCHAIN_API_KEY=lsv2_... python scripts/push_prompts.py
    LANGCHAIN_API_KEY=lsv2_... python scripts/push_prompts.py --tag v2
"""
import argparse
import os
import sys


def main() -> None:
    if not os.getenv("LANGCHAIN_API_KEY"):
        print("ERROR: LANGCHAIN_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Push prompts to LangSmith Hub")
    parser.add_argument(
        "--tag",
        default=None,
        help="Version tag to apply in the Hub UI after pushing (e.g. v1, v2). "
             "Tags must be set in the LangSmith UI or SDK tag API after the push URL is returned.",
    )
    args = parser.parse_args()

    from langchain import hub
    from langchain_core.prompts import PromptTemplate

    from app.rag.prompts import (
        _RAG_PROMPT_DEFAULT as RAG,
        _INTENT_PROMPT_DEFAULT as INTENT,
        _EXTRACTION_PROMPT_DEFAULT as EXTRACTION,
    )

    prompts: dict[str, str] = {
        "hotel-assistant/rag-prompt":        RAG,
        "hotel-assistant/intent-classifier": INTENT,
        "hotel-assistant/extraction":        EXTRACTION,
    }

    for name, template in prompts.items():
        obj = PromptTemplate.from_template(template)
        url = hub.push(name, obj, new_repo_is_public=False)
        print(f"Pushed  {name}  →  {url}")

    if args.tag:
        print(
            f"\nTo pin PROMPT_VARIANT={args.tag}, apply the tag '{args.tag}' to the "
            "new commit in the LangSmith Hub UI (Prompts → select repo → Commits → Add tag)."
        )


if __name__ == "__main__":
    main()
