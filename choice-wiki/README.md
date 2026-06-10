# Choice Wiki — MCP Server

An MCP (Model Context Protocol) server that gives Claude a knowledge base about the **Choice restaurant platform** (choiceqr.com). Anyone you give access to can connect it to Claude and ask questions about Choice products, pricing, integrations, and features.

---

## Setup

### 1. Requirements

- Python 3.10+ with the `mcp` package installed
- Install if needed: `pip install mcp` or `pip3 install mcp`

### 2. Add to Claude Code settings

**Claude Code** — add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "choice-wiki": {
      "command": "python3",
      "args": ["/path/to/choice-wiki/server.py"]
    }
  }
}
```

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "choice-wiki": {
      "command": "python3",
      "args": ["/path/to/choice-wiki/server.py"]
    }
  }
}
```

Replace `/path/to/choice-wiki/` with the actual path to this folder.

### 3. Restart Claude

After adding the config, restart Claude. The server will load automatically.

---

## What It Does

The MCP server exposes three tools Claude can use:

| Tool | Description |
|------|-------------|
| `search_choice_wiki` | Search the knowledge base by keyword or question |
| `get_choice_topic` | Get the full content of a specific topic |
| `list_wiki_topics` | List all available wiki topics |

It also exposes every wiki file as a **resource** accessible via `wiki://` URIs.

---

## Wiki Structure

```
wiki/
├── 01_overview.md          — What is Choice, key stats, company info
├── 02_products_index.md    — All products overview table
├── 03_pricing.md           — All plans, prices, features, add-ons
├── 04_integrations.md      — Marketplace, POS, payment integrations
├── 05_faq.md               — Common questions and answers
└── products/
    ├── website.md          — Restaurant website product
    ├── qr_menu.md          — QR / contactless menu
    ├── delivery_takeaway.md — Delivery & takeaway ordering
    ├── qr_orders_to_table.md — QR table ordering
    ├── qr_payment.md       — QR payment at table
    ├── collection_point.md — Marketplace aggregator
    ├── reservation.md      — Table reservation system
    ├── crm.md              — CRM system
    ├── loyalty.md          — Loyalty program
    ├── marketing.md        — Marketing tools
    ├── reviews.md          — Reviews management
    └── mobile_app.md       — Custom mobile app
```

---

## Example Questions It Can Answer

- "What does Choice do?"
- "What's included in the Smart plan?"
- "How does Collection Point work?"
- "Which POS systems does Choice integrate with?"
- "What is the pricing for Choice in Czech Republic?"
- "How does the loyalty program work?"
- "Can guests split the bill?"
- "What marketplaces does Choice support?"
- "How long does it take to set up?"
- "What's the difference between Smart and Pro?"

---

## Sharing With Others

To give someone else access:

1. Share this folder (or the path to `server.js`)
2. They run `npm install` in the folder
3. They add the MCP config to their Claude settings
4. Done — Claude will answer questions about Choice automatically

---

## Keeping It Up to Date

Wiki files are plain Markdown in the `wiki/` folder. Edit any file to update the knowledge base — no restart needed for content changes (the server reads files at startup; restart if you add new files).
