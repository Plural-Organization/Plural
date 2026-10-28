import type { Command } from "@plural/client";

// A question the add-a-server wizard asks; `{key}` in a preset's command, args, url, env or headers is replaced by the answer.
export interface McpField {
  key: string;
  label: string;
  hint?: string;
  fallback?: string;
  optional?: boolean;
  secret?: boolean;
}

export interface McpPreset {
  id: string;
  title: string;
  blurb: string;
  fields: McpField[];
  command?: string[];
  url?: string;
  env?: Record<string, string>;
  headers?: Record<string, string>;
}

const token = (label: string, hint: string, optional = false): McpField => ({ key: "token", label, hint, optional, secret: true });

export const MCP_CATALOG: McpPreset[] = [
  {
    id: "context7",
    title: "Context7",
    blurb: "up-to-date docs for any library",
    fields: [token("Context7 API key", "optional, raises the rate limit · enter to skip", true)],
    command: ["npx", "-y", "@upstash/context7-mcp"],
    env: { CONTEXT7_API_KEY: "{token}" },
  },
  {
    id: "playwright",
    title: "Playwright",
    blurb: "drive a real browser: open pages, click, read",
    fields: [],
    command: ["npx", "-y", "@playwright/mcp@latest"],
  },
  {
    id: "github",
    title: "GitHub",
    blurb: "issues, pull requests and code on github.com",
    fields: [token("GitHub personal access token", "github.com/settings/tokens · stays in the config file on this machine")],
    url: "https://api.githubcopilot.com/mcp/",
    headers: { Authorization: "Bearer {token}" },
  },
  {
    id: "notion",
    title: "Notion",
    blurb: "search and edit Notion pages",
    fields: [token("Notion integration token", "notion.so/profile/integrations · stays in the config file on this machine")],
    command: ["npx", "-y", "@notionhq/notion-mcp-server"],
    env: { NOTION_TOKEN: "{token}" },
  },
  {
    id: "filesystem",
    title: "Filesystem",
    blurb: "read and write files in a folder you choose",
    fields: [{ key: "folder", label: "Folder to share", hint: "absolute path · enter for the workspace", fallback: "." }],
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "{folder}"],
  },
  { id: "fetch", title: "Fetch", blurb: "fetch web pages as markdown", fields: [], command: ["uvx", "mcp-server-fetch"] },
  { id: "git", title: "Git", blurb: "read history, diffs and branches", fields: [], command: ["uvx", "mcp-server-git"] },
  { id: "memory", title: "Memory", blurb: "a knowledge graph the agent keeps between sessions", fields: [], command: ["npx", "-y", "@modelcontextprotocol/server-memory"] },
  { id: "time", title: "Time", blurb: "current time and time zone conversions", fields: [], command: ["uvx", "mcp-server-time"] },
  {
    id: "",
    title: "Your own command",
    blurb: "any local MCP server: npx, uvx, docker, a binary",
    fields: [{ key: "command", label: "Command that starts it", hint: "for example: npx -y @scope/some-mcp --flag" }],
  },
  {
    id: "",
    title: "Your own URL",
    blurb: "a remote MCP server over HTTP",
    fields: [
      { key: "url", label: "Server URL", hint: "https://…/mcp" },
      token("Bearer token", "optional · sent as the Authorization header · enter to skip", true),
    ],
    headers: { Authorization: "Bearer {token}" },
  },
];

export function wizardFields(preset: McpPreset, taken: readonly string[]): McpField[] {
  const suggested = preset.id && !taken.includes(preset.id) ? preset.id : undefined;
  const name: McpField = {
    key: "name",
    label: "Name",
    hint: suggested ? `enter for "${suggested}" · letters, digits, - and _` : "letters, digits, - and _",
    fallback: suggested,
  };
  return [name, ...preset.fields];
}

const fill = (template: string, values: Record<string, string>): string => template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");

function filled(map: Record<string, string> | undefined, values: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, template] of Object.entries(map ?? {})) {
    const needs = [...template.matchAll(/\{(\w+)\}/g)].map((match) => match[1]!);
    if (needs.every((name) => values[name])) {
      out[key] = fill(template, values);
    }
  }
  return out;
}

export function addCommand(preset: McpPreset, values: Record<string, string>, scope: "project" | "global"): Extract<Command, { type: "mcp.add" }> {
  const env = filled(preset.env, values);
  const headers = filled(preset.headers, values);
  if (values.url !== undefined || preset.url) {
    return { type: "mcp.add", name: values.name ?? "", url: values.url ?? preset.url ?? null, command: null, args: [], env, headers, scope };
  }
  const line = values.command !== undefined ? values.command.split(/\s+/).filter(Boolean) : (preset.command ?? []).map((part) => fill(part, values));
  const [command = "", ...args] = line;
  return { type: "mcp.add", name: values.name ?? "", command, args, url: null, env, headers, scope };
}
