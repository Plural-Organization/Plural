import type { FeedItem } from "@plural/client";

// A site the agent writes is rebuilt in the browser from its own tool calls: every client reads the
// same feed, so everyone sees the same page. Plain HTML, CSS and scripts go in as they are; modules,
// TypeScript and JSX are compiled here and their packages come from esm.sh.

type ToolItem = Extract<FeedItem, { kind: "tool" }>;

export interface Site {
  files: ReadonlyMap<string, string>;
  // Grows with each change that went through, so a preview rebuilds only when a file changed.
  version: number;
}

export interface Built {
  html: string;
  problems: string[];
}

export const PACKAGES = "https://esm.sh";
const SITE = "@site/";
const SCRIPT_EXTENSIONS = ["tsx", "ts", "jsx", "js", "mjs"];
const RESOLVE = ["", ".tsx", ".ts", ".jsx", ".js", ".mjs", "/index.tsx", "/index.ts", "/index.jsx", "/index.js"];

export function normalize(path: string): string {
  const out: string[] = [];
  for (const part of path.replace(/\\/g, "/").split("/")) {
    if (part === "" || part === ".") {
      continue;
    }
    if (part === "..") {
      out.pop();
    } else {
      out.push(part);
    }
  }
  return out.join("/");
}

function dirOf(path: string): string {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? "" : path.slice(0, cut);
}

function extOf(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

function replaceText(text: string, old: string, next: string, all: boolean): string | null {
  if (old === "" || !text.includes(old)) {
    return null;
  }
  return all ? text.split(old).join(next) : text.replace(old, () => next);
}

// The files the agent wrote or edited, as they are after its last change that went through.
export function siteFiles(items: FeedItem[]): Site {
  const files = new Map<string, string>();
  let version = 0;
  for (const item of items) {
    if (item.kind !== "tool" || item.status !== "ok") {
      continue;
    }
    const { args, name } = item.call;
    if (typeof args.path !== "string") {
      continue;
    }
    const path = normalize(args.path);
    if (name === "write" && typeof args.content === "string") {
      files.set(path, args.content);
      version += 1;
      continue;
    }
    const edits = name === "edit" ? [args] : name === "multi_edit" && Array.isArray(args.edits) ? (args.edits as Record<string, unknown>[]) : [];
    let text = files.get(path);
    if (text === undefined || edits.length === 0) {
      continue;
    }
    for (const edit of edits) {
      if (typeof edit.old !== "string" || typeof edit.new !== "string") {
        text = undefined;
        break;
      }
      const next = replaceText(text, edit.old, edit.new, edit.replace_all === true);
      if (next === null) {
        text = undefined;
        break;
      }
      text = next;
    }
    if (text !== undefined) {
      files.set(path, text);
      version += 1;
    }
  }
  return { files, version };
}

// The pages a preview opens on: each index.html, and an HTML file alone in a folder without one.
export function siteEntries(files: ReadonlyMap<string, string>): string[] {
  const html = [...files.keys()].filter((path) => extOf(path) === "html" || extOf(path) === "htm");
  const withIndex = new Set(html.filter((path) => /(^|\/)index\.html?$/.test(path)).map(dirOf));
  return html.filter((path) => /(^|\/)index\.html?$/.test(path) || !withIndex.has(dirOf(path)));
}

// A link inside the page at `from`; a path from `/` starts at the site's `root`. Null for one that leaves the site.
export function localTarget(from: string, href: string, root = dirOf(from)): string | null {
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("//") || href.startsWith("#")) {
    return null;
  }
  const path = href.split(/[?#]/)[0]!;
  return normalize(path.startsWith("/") ? `${root}/${path}` : `${dirOf(from)}/${path}`);
}

function base64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

const asModule = (code: string) => `data:text/javascript;base64,${base64(code)}`;
const svgUrl = (svg: string) => `data:image/svg+xml;base64,${base64(svg)}`;
const scriptSafe = (code: string) => code.replace(/<\/script/gi, "<\\/script");

// Every import and re-export names a module in quotes after one of these.
const SPECIFIER = /(\bimport\s*\(\s*|\b(?:import|export)\s*(?:[^'"();]*?\bfrom\s*)?)(['"])([^'"\n]+)\2/g;

export function rewriteImports(code: string, rewrite: (specifier: string) => string): string {
  return code.replace(SPECIFIER, (_match, head: string, quote: string, specifier: string) => `${head}${quote}${rewrite(specifier)}${quote}`);
}

function packageOf(specifier: string): string {
  const parts = specifier.split("/");
  return specifier.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0]!;
}

// The versions the project's package.json asks for, nearest to the page first.
function dependencies(files: ReadonlyMap<string, string>, root: string): Record<string, string> {
  for (let dir = root; ; dir = dirOf(dir)) {
    const text = files.get(dir === "" ? "package.json" : `${dir}/package.json`);
    if (text !== undefined) {
      try {
        const json = JSON.parse(text) as { dependencies?: Record<string, string>; devDependencies?: Record<string, string> };
        return { ...json.devDependencies, ...json.dependencies };
      } catch {
        return {};
      }
    }
    if (dir === "") {
      return {};
    }
  }
}

const REACT = ["react", "react-dom"];
// What a React page may import from React, mapped up front so packages that leave React out find it.
const REACT_SPECIFIERS = ["react", "react/jsx-runtime", "react-dom", "react-dom/client"];

// A package at the version the project asks for. With React on the page, every other package leaves
// React and React DOM to the page's import map, so the page runs one copy of React.
export function packageUrl(specifier: string, versions: Record<string, string>, react: boolean): string {
  const name = packageOf(specifier);
  const range = versions[name];
  const version = range && /^[\d^~<>=.*xX |-]+$/.test(range) ? `@${range.replace(/\s+/g, "")}` : "";
  const url = `${PACKAGES}/${name}${version}${specifier.slice(name.length)}`;
  if (name === "react" || !react) {
    return url;
  }
  return name === "react-dom" ? `${url}?external=react` : `${url}?external=${REACT.join(",")}`;
}

type Transform = (code: string, options: { transforms: ("typescript" | "jsx")[]; jsxRuntime: "automatic"; production: boolean; filePath: string }) => { code: string };

let compiler: Promise<Transform> | null = null;
function loadCompiler(): Promise<Transform> {
  compiler ??= import("sucrase").then((module) => module.transform as Transform);
  return compiler;
}

class Modules {
  readonly map: Record<string, string> = {};
  readonly problems: string[] = [];
  private readonly done = new Set<string>();
  private readonly packages = new Set<string>();

  constructor(
    private readonly files: ReadonlyMap<string, string>,
    private readonly root: string,
    private readonly versions: Record<string, string>,
  ) {}

  resolve(from: string, specifier: string): string | null {
    const wanted = specifier.startsWith("/") ? normalize(`${this.root}/${specifier}`) : normalize(`${from}/${specifier}`);
    return RESOLVE.map((suffix) => `${wanted}${suffix}`).find((path) => this.files.has(path)) ?? null;
  }

  // What a specifier becomes inside the page: a module of the site, or a package.
  async specifier(from: string, specifier: string): Promise<string> {
    if (/^(https?:|data:|blob:)/.test(specifier)) {
      return specifier;
    }
    if (!specifier.startsWith(".") && !specifier.startsWith("/")) {
      this.packages.add(specifier);
      return specifier;
    }
    const path = this.resolve(from, specifier);
    if (path === null) {
      const missing = normalize(specifier.startsWith("/") ? `${this.root}/${specifier}` : `${from}/${specifier}`);
      this.problems.push(`${missing} is not in the preview: the agent did not write it with write or edit`);
      return asModule(`throw new Error(${JSON.stringify(`${missing} is missing from the preview`)});`);
    }
    await this.add(path);
    return `${SITE}${path}`;
  }

  // The packages the page imports, mapped once the whole graph is known.
  mapPackages(): void {
    const react = this.versions.react !== undefined || [...this.packages].some((specifier) => REACT.includes(packageOf(specifier)));
    for (const specifier of react ? [...this.packages, ...REACT_SPECIFIERS] : this.packages) {
      this.map[specifier] ??= packageUrl(specifier, this.versions, react);
    }
  }

  async add(path: string): Promise<void> {
    if (this.done.has(path)) {
      return;
    }
    this.done.add(path);
    const source = this.files.get(path)!;
    const ext = extOf(path);
    let code: string;
    if (ext === "css") {
      code = `const style = document.createElement("style");\nstyle.textContent = ${JSON.stringify(source)};\ndocument.head.append(style);\nexport default ${JSON.stringify(source)};`;
    } else if (ext === "json") {
      code = `export default ${source.trim() || "null"};`;
    } else if (ext === "svg") {
      code = `export default ${JSON.stringify(svgUrl(source))};`;
    } else if (SCRIPT_EXTENSIONS.includes(ext)) {
      code = await this.compile(path, source, ext);
    } else {
      code = `export default ${JSON.stringify(path)};`;
    }
    this.map[`${SITE}${path}`] = asModule(code);
  }

  async compile(path: string, source: string, ext: string): Promise<string> {
    let code = source;
    try {
      const transform = await loadCompiler();
      const transforms: ("typescript" | "jsx")[] = ext === "ts" ? ["typescript"] : ext === "tsx" ? ["typescript", "jsx"] : ["jsx"];
      code = transform(source, { transforms, jsxRuntime: "automatic", production: true, filePath: path }).code;
    } catch (error) {
      this.problems.push(`${path} does not compile: ${error instanceof Error ? error.message : String(error)}`);
      return `throw new Error(${JSON.stringify(`${path} does not compile`)});`;
    }
    return this.imports(dirOf(path), code);
  }

  async imports(from: string, code: string): Promise<string> {
    const found: string[] = [];
    rewriteImports(code, (specifier) => {
      found.push(specifier);
      return specifier;
    });
    const resolved = new Map<string, string>();
    for (const specifier of found) {
      resolved.set(specifier, await this.specifier(from, specifier));
    }
    return rewriteImports(code, (specifier) => resolved.get(specifier) ?? specifier);
  }
}

const TAG = (name: string) => new RegExp(`<${name}\\b([^>]*)>`, "gi");
const attr = (attrs: string, name: string) => new RegExp(`\\b${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, "i").exec(attrs);
const attrValue = (attrs: string, name: string) => {
  const match = attr(attrs, name);
  return match ? (match[2] ?? match[3] ?? match[4] ?? "") : null;
};

// The page at `entry` as one self-contained document; `bridge` is a script put first in its head. A path
// from `/` starts at `root`, the folder of the page the site opened on.
export async function buildSite(files: ReadonlyMap<string, string>, entry: string, bridge = "", root = dirOf(entry)): Promise<Built> {
  const source = files.get(entry);
  if (source === undefined) {
    return { html: "", problems: [`${entry} is not in the preview`] };
  }
  const modules = new Modules(files, root, dependencies(files, root));
  const local = (href: string) => {
    const target = localTarget(entry, href, root);
    return target !== null && files.has(target) ? target : null;
  };
  let html = source;

  // Stylesheets and pictures the agent wrote go inline.
  html = html.replace(/<link\b([^>]*)>/gi, (tag, attrs: string) => {
    const href = attrValue(attrs, "href");
    const path = href === null ? null : local(href);
    if (path === null) {
      return tag;
    }
    if (/\bstylesheet\b/i.test(attrValue(attrs, "rel") ?? "")) {
      return `<style data-from="${path}">${files.get(path)!.replace(/<\/style/gi, "<\\/style")}</style>`;
    }
    return extOf(path) === "svg" ? tag.replace(attr(attrs, "href")![0], `href="${svgUrl(files.get(path)!)}"`) : tag;
  });
  html = html.replace(TAG("(?:img|source|image|use)"), (tag, attrs: string) => {
    const name = attrValue(attrs, "src") !== null ? "src" : "href";
    const value = attrValue(attrs, name);
    // A link to one symbol of a sprite keeps pointing into the file.
    const path = value === null || value.includes("#") ? null : local(value);
    return path !== null && extOf(path) === "svg" ? tag.replace(attr(attrs, name)![0], `${name}="${svgUrl(files.get(path)!)}"`) : tag;
  });

  // Scripts: a module, or anything TypeScript or JSX, joins the module graph; the rest goes inline.
  const scripts: { tag: string; replacement: Promise<string> }[] = [];
  html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi, (tag, attrs: string, body: string) => {
    const src = attrValue(attrs, "src");
    const module = /\btype\s*=\s*["']?module/i.test(attrs);
    let replacement: Promise<string> | null = null;
    if (src !== null) {
      const path = local(src);
      if (path === null) {
        if (!/^(https?:)?\/\//.test(src)) {
          modules.problems.push(`${normalize(`${root}/${src}`)} is not in the preview: the agent did not write it with write or edit`);
        }
      } else if (module || ["ts", "tsx", "jsx"].includes(extOf(path))) {
        replacement = modules.add(path).then(() => `<script type="module">import ${JSON.stringify(`${SITE}${path}`)};</script>`);
      } else {
        replacement = Promise.resolve(`<script>${scriptSafe(files.get(path)!)}</script>`);
      }
    } else if (module) {
      replacement = modules.imports(root, body).then((code) => `<script type="module">${scriptSafe(code)}</script>`);
    }
    if (replacement !== null) {
      scripts.push({ tag, replacement });
    }
    return tag;
  });
  for (const { tag, replacement } of scripts) {
    const next = await replacement;
    html = html.replace(tag, () => next);
  }

  modules.mapPackages();
  // The import map has to come before any module, so it goes first in the head, after the bridge.
  const map = Object.keys(modules.map).length > 0 ? `<script type="importmap">${scriptSafe(JSON.stringify({ imports: modules.map }))}</script>` : "";
  const head = `${bridge ? `<script>${scriptSafe(bridge)}</script>` : ""}${map}`;
  if (/<head\b[^>]*>/i.test(html)) {
    html = html.replace(/<head\b[^>]*>/i, (tag) => `${tag}${head}`);
  } else if (/<html\b[^>]*>/i.test(html)) {
    html = html.replace(/<html\b[^>]*>/i, (tag) => `${tag}<head>${head}</head>`);
  } else {
    html = `${head}${html}`;
  }
  return { html, problems: [...new Set(modules.problems)] };
}
