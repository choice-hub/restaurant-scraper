#!/usr/bin/env python3
"""Choice Wiki MCP Server — answers questions about the Choice restaurant platform."""

import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

WIKI_DIR = Path(__file__).parent / "wiki"

PORT = int(os.environ.get("PORT", 8000))
IS_REMOTE = os.environ.get("RENDER") or os.environ.get("PORT")


def load_wiki():
    docs = {}
    for md_file in sorted(WIKI_DIR.rglob("*.md")):
        key = str(md_file.relative_to(WIKI_DIR)).replace(".md", "")
        docs[key] = md_file.read_text(encoding="utf-8")
    return docs


WIKI = load_wiki()

INDEX = []
for key, content in WIKI.items():
    lines = content.splitlines()
    title = next((l.lstrip("# ") for l in lines if l.startswith("# ")), key)
    INDEX.append({"key": key, "title": title, "content": content})


def keyword_search(query: str, top_n: int = 5):
    terms = query.lower().split()
    results = []
    for doc in INDEX:
        text = (doc["title"] + " " + doc["content"]).lower()
        score = sum(text.count(t) for t in terms)
        if score > 0:
            results.append((score, doc))
    results.sort(key=lambda x: -x[0])
    return [doc for _, doc in results[:top_n]]


mcp = FastMCP(
    "choice-wiki",
    instructions=(
        "You have access to a comprehensive knowledge base about Choice (choiceqr.com), "
        "an all-in-one restaurant platform. Use the tools below to answer any question "
        "about Choice products, pricing, integrations, features, or company info. "
        "Always search the wiki before answering from memory."
    ),
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
)


@mcp.tool()
def search_choice_wiki(query: str) -> str:
    """Search the Choice product knowledge base.

    Use this for ANY question about Choice: products, pricing, integrations,
    features, plans, FAQ, company info, or comparisons.

    Args:
        query: What you want to know (e.g. 'Smart plan features',
               'how does QR payment work', 'Wolt integration', 'pricing')
    """
    results = keyword_search(query)
    if not results:
        return "No results found. Try list_wiki_topics to see all available topics."
    parts = [f"## {r['title']}\n\n{r['content']}" for r in results]
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def get_choice_topic(topic: str) -> str:
    """Get the full content of a specific Choice wiki topic.

    Args:
        topic: Topic key (e.g. '01_overview', '03_pricing', 'products/loyalty') or keyword.
    """
    if topic in WIKI:
        doc = next(d for d in INDEX if d["key"] == topic)
        return f"# {doc['title']}\n\n{doc['content']}"

    topic_lower = topic.lower()
    for doc in INDEX:
        if topic_lower in doc["key"].lower() or topic_lower in doc["title"].lower():
            return f"# {doc['title']}\n\n{doc['content']}"

    available = "\n".join(f"• {d['key']}: {d['title']}" for d in INDEX)
    return f'Topic "{topic}" not found.\n\nAvailable topics:\n{available}'


@mcp.tool()
def list_wiki_topics() -> str:
    """List all available topics in the Choice wiki knowledge base."""
    lines = ["**Choice Wiki — Available Topics:**\n"]
    lines += [f"• `{d['key']}` — {d['title']}" for d in INDEX]
    return "\n".join(lines)


if __name__ == "__main__":
    if IS_REMOTE:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
