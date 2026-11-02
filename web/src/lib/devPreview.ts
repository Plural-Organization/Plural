import type { EventOf } from "@plural/client";

export type FetchPreview = (previewId: string, path: string) => Promise<EventOf<"preview.data">>;
const ORIGIN = "http://plural-preview.invalid";

export function previewPath(page: string, href: string): string | null {
  try {
    const url = new URL(href, ORIGIN + page);
    return url.origin === ORIGIN && !url.username && !url.password ? url.pathname + url.search + url.hash : null;
  } catch { return null; }
}

// A server-rendered preview. Only the Plural bridge executes; application JS/HMR is unsupported.
export async function buildDevPreview(id: string, page: string, fetchResource: FetchPreview, bridge: string): Promise<{ html: string; problems: string[] }> {
  const cache = new Map<string, EventOf<"preview.data">>();
  let total = 0;
  const get = async (path: string) => {
    path = path.split("#")[0]!;
    const cached = cache.get(path);
    if (cached) return cached;
    if (cache.size >= 80) throw new Error("preview exceeds 80 resources");
    const result = await fetchResource(id, path);
    if (result.status < 200 || result.status >= 300) throw new Error(`preview resource returned HTTP ${result.status}`);
    total += result.content_b64.length;
    if (total > 24_000_000) throw new Error("preview exceeds 18 MB");
    cache.set(path, result);
    return result;
  };
  const decode = (data: string) => new TextDecoder().decode(Uint8Array.from(atob(data), c => c.charCodeAt(0)));
  const asset = async (href: string, from: string): Promise<string> => {
    // Inlined already (an imported sheet is passed over twice) or written inline; the CSP keeps it to images and fonts.
    if (/^data:/i.test(href) || href.startsWith("#")) return href;
    const path = previewPath(from, href);
    if (path === null) return "data:,";
    // One missing picture or font leaves a gap, not an empty preview.
    const result = await get(path).catch(() => null);
    if (result === null) return "data:,";
    const mime = result.media_type.split(";")[0]!.trim();
    if (!/^(image\/|font\/|application\/(?:font|vnd\.ms-fontobject|octet-stream))/.test(mime)) return "data:,";
    return `data:${mime};base64,${result.content_b64}`;
  };
  // A stylesheet that is missing leaves the page unstyled there, not empty.
  const sheet = async (path: string, depth: number): Promise<string> => {
    const result = await get(path).catch(() => null);
    return result === null ? "" : css(decode(result.content_b64), path, depth);
  };
  const css = async (source: string, from: string, depth = 0): Promise<string> => {
    if (depth > 8) throw new Error("preview stylesheet nesting is too deep");
    for (const match of [...source.matchAll(/@import\s+(?:url\(\s*)?["']([^"']+)["']\s*\)?([^;]*);/gi)]) {
      const path = previewPath(from, match[1]!);
      const media = match[2]!.trim();
      const imported = path === null ? "" : await sheet(path, depth + 1);
      source = source.replace(match[0], () => media ? `@media ${media}{${imported}}` : imported);
    }
    for (const match of [...source.matchAll(/url\(\s*(["']?)([^"')]+)\1\s*\)/gi)]) {
      const url = await asset(match[2]!.trim(), from);
      source = source.replace(match[0], () => `url("${url}")`);
    }
    return source;
  };
  const response = await get(page);
  if (!response.media_type.toLowerCase().includes("text/html")) throw new Error("preview entry must return HTML");
  const doc = new DOMParser().parseFromString(decode(response.content_b64), "text/html");
  const problems = ["Server-rendered preview · reload to update · application JavaScript and HMR are not supported yet"];
  // The app's JS never runs here, so what it would hide until it loads (Next's dev `body{display:none}`) goes,
  // and what it shows without JS stays.
  doc.querySelectorAll("style[data-next-hide-fouc]").forEach(node => node.remove());
  doc.querySelectorAll("noscript").forEach(node => node.replaceWith(...node.childNodes));
  doc.querySelectorAll("script,base,iframe,object,embed,meta[http-equiv],link:not([rel=stylesheet])").forEach(node => node.remove());
  const originalStyles = [...doc.querySelectorAll("style")];
  for (const link of [...doc.querySelectorAll<HTMLLinkElement>("link[rel=stylesheet]")]) {
    const path = previewPath(page, link.getAttribute("href") || "");
    const style = doc.createElement("style");
    style.textContent = path === null ? "" : await sheet(path, 0);
    link.replaceWith(style);
  }
  for (const style of originalStyles) style.textContent = await css(style.textContent || "", page);
  for (const node of [...doc.querySelectorAll<HTMLElement>("*")]) {
    for (const attribute of [...node.attributes]) {
      if (/^on/i.test(attribute.name) || ["srcset", "ping", "action", "formaction", "background"].includes(attribute.name)) node.removeAttribute(attribute.name);
    }
    if (node.hasAttribute("style")) node.setAttribute("style", await css(node.getAttribute("style")!, page));
    if (node.hasAttribute("src")) {
      if (node.tagName === "IMG") node.setAttribute("src", await asset(node.getAttribute("src")!, page));
      else node.removeAttribute("src");
    }
    if (node.tagName === "A" && node.hasAttribute("href")) {
      const href = node.getAttribute("href")!;
      const path = previewPath(page, href);
      if (!href.startsWith("#") && path !== null) node.setAttribute("href", path);
      else if (path === null) node.removeAttribute("href");
    }
  }
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const policy = doc.createElement("meta");
  policy.httpEquiv = "Content-Security-Policy";
  policy.content = `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'`;
  const script = doc.createElement("script");
  script.setAttribute("nonce", nonce);
  script.textContent = bridge;
  doc.head.prepend(policy, script);
  return { html: "<!doctype html>" + doc.documentElement.outerHTML, problems };
}
