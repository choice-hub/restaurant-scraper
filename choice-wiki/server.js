import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WIKI_DIR = path.join(__dirname, "wiki");

// Load all wiki files into memory at startup
function loadWiki() {
  const wiki = {};

  function readDir(dir, prefix = "") {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        readDir(fullPath, prefix + entry.name + "/");
      } else if (entry.name.endsWith(".md")) {
        const key = prefix + entry.name.replace(".md", "");
        wiki[key] = fs.readFileSync(fullPath, "utf-8");
      }
    }
  }

  readDir(WIKI_DIR);
  return wiki;
}

const wiki = loadWiki();

// Build a flat searchable index: array of { key, title, content }
const index = Object.entries(wiki).map(([key, content]) => {
  const firstLine = content.split("\n").find((l) => l.startsWith("# ")) || key;
  return { key, title: firstLine.replace(/^# /, ""), content };
});

// Simple keyword search — returns ranked results
function search(query) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  return index
    .map((doc) => {
      const text = (doc.title + " " + doc.content).toLowerCase();
      const score = terms.reduce((s, t) => s + (text.split(t).length - 1), 0);
      return { ...doc, score };
    })
    .filter((d) => d.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

const server = new McpServer({
  name: "choice-wiki",
  version: "1.0.0",
});

// ── Resources: expose each wiki file ──────────────────────────────────────────

server.resource("wiki-index", "wiki://index", async () => ({
  contents: [
    {
      uri: "wiki://index",
      mimeType: "text/plain",
      text: index
        .map((d) => `• ${d.key}  →  ${d.title}`)
        .join("\n"),
    },
  ],
}));

for (const { key, title, content } of index) {
  const uri = `wiki://${key}`;
  server.resource(key, uri, async () => ({
    contents: [{ uri, mimeType: "text/markdown", text: content }],
  }));
}

// ── Tools ──────────────────────────────────────────────────────────────────────

server.tool(
  "search_choice_wiki",
  "Search the Choice product knowledge base. Use this for any question about Choice: products, pricing, integrations, features, FAQ.",
  { query: z.string().describe("What you want to know about Choice") },
  async ({ query }) => {
    const results = search(query);
    if (results.length === 0) {
      return {
        content: [
          {
            type: "text",
            text: "No results found. Try different keywords or use list_wiki_topics to see all available topics.",
          },
        ],
      };
    }
    const text = results
      .map((r) => `## ${r.title}\n\n${r.content}`)
      .join("\n\n---\n\n");
    return { content: [{ type: "text", text }] };
  }
);

server.tool(
  "get_choice_topic",
  "Get the full content of a specific Choice wiki topic by its key (e.g. '01_overview', 'products/pricing', '03_pricing').",
  { topic: z.string().describe("The wiki topic key") },
  async ({ topic }) => {
    const doc = index.find(
      (d) =>
        d.key === topic ||
        d.key.toLowerCase().includes(topic.toLowerCase()) ||
        d.title.toLowerCase().includes(topic.toLowerCase())
    );
    if (!doc) {
      return {
        content: [
          {
            type: "text",
            text: `Topic "${topic}" not found. Available topics:\n${index.map((d) => `• ${d.key}: ${d.title}`).join("\n")}`,
          },
        ],
      };
    }
    return {
      content: [{ type: "text", text: `# ${doc.title}\n\n${doc.content}` }],
    };
  }
);

server.tool(
  "list_wiki_topics",
  "List all available topics in the Choice wiki knowledge base.",
  {},
  async () => ({
    content: [
      {
        type: "text",
        text:
          "**Available Choice Wiki Topics:**\n\n" +
          index.map((d) => `• \`${d.key}\` — ${d.title}`).join("\n"),
      },
    ],
  })
);

// ── Start ──────────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
