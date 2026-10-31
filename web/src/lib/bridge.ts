// The preview runs the agent's page in a sandboxed frame with no access to this app; this script, put
// first in the page, is its only way out. It reports the pointer, scrolling, errors, links and the
// component someone picks, and it draws the others' pointers and the pick outline inside the page.

export interface PickedComponent {
  selector: string;
  tag: string;
  html: string;
  text: string;
  // Where it is in the frame's viewport, in CSS pixels.
  rect: { left: number; top: number; right: number; bottom: number };
}

export type FromFrame =
  | { type: "cursor"; x: number; y: number }
  | { type: "cursor"; x: null }
  | { type: "scroll"; y: number }
  | { type: "picked"; component: PickedComponent }
  | { type: "pick-cancel" }
  | { type: "navigate"; href: string }
  | { type: "external"; href: string }
  | { type: "error"; message: string };

export interface FramePointer {
  id: string;
  name: string;
  color: string;
  x: number;
  y: number;
}

export type ToFrame = { type: "cursors"; list: FramePointer[] } | { type: "pick"; on: boolean } | { type: "unmark" };

export const FROM_FRAME = "plural-preview";
export const TO_FRAME = "plural-host";

const clamp = (value: unknown, low: number, high: number): number | null =>
  typeof value === "number" && Number.isFinite(value) ? Math.min(high, Math.max(low, value)) : null;
const text = (value: unknown, limit: number): string => (typeof value === "string" ? value.slice(0, limit) : "");

// What the frame sent, checked: the page is the agent's code and may post anything.
export function readFrame(data: unknown): FromFrame | null {
  if (typeof data !== "object" || data === null || (data as { from?: unknown }).from !== FROM_FRAME) {
    return null;
  }
  const message = data as Record<string, unknown>;
  switch (message.type) {
    case "cursor": {
      if (message.x === null) {
        return { type: "cursor", x: null };
      }
      const x = clamp(message.x, 0, 1);
      const y = clamp(message.y, 0, 20);
      return x === null || y === null ? null : { type: "cursor", x, y };
    }
    case "scroll": {
      const y = clamp(message.y, 0, 1e7);
      return y === null ? null : { type: "scroll", y };
    }
    case "picked": {
      const component = message.component as Record<string, unknown> | undefined;
      const rect = component?.rect as Record<string, unknown> | undefined;
      const sides = ["left", "top", "right", "bottom"].map((side) => clamp(rect?.[side], -1e5, 1e5));
      if (!component || sides.some((side) => side === null)) {
        return null;
      }
      const [left, top, right, bottom] = sides as number[];
      return {
        type: "picked",
        component: { selector: text(component.selector, 300), tag: text(component.tag, 40), html: text(component.html, 2000), text: text(component.text, 300), rect: { left: left!, top: top!, right: right!, bottom: bottom! } },
      };
    }
    case "pick-cancel":
      return { type: "pick-cancel" };
    case "navigate":
    case "external":
      return typeof message.href === "string" ? { type: message.type, href: message.href.slice(0, 2000) } : null;
    case "error":
      return { type: "error", message: text(message.message, 500) };
    default:
      return null;
  }
}

export function bridgeScript(scrollY: number): string {
  return `(() => {
const FROM = ${JSON.stringify(FROM_FRAME)}, TO = ${JSON.stringify(TO_FRAME)}, restore = ${Math.max(0, Math.round(scrollY))};
const post = (message) => parent.postMessage({ from: FROM, ...message }, "*");
addEventListener("error", (event) => post({ type: "error", message: String(event.message || event.error || "error") }));
addEventListener("unhandledrejection", (event) => post({ type: "error", message: String((event.reason && event.reason.message) || event.reason) }));
addEventListener("load", () => { if (restore > 0) scrollTo(0, restore); });

let picking = false, others = [], host = null, layer = null, hoverBox = null, markBox = null;
const ensure = () => {
  if (layer && host.isConnected) return;
  host = document.createElement("plural-overlay");
  host.style.cssText = "position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.innerHTML = "<style>.p{position:absolute;transition:left 60ms linear,top 60ms linear}.p svg{display:block;stroke:#111;stroke-width:1.2}.p span{position:absolute;left:12px;top:14px;font:600 11px/1.5 system-ui,sans-serif;color:#111;border-radius:4px;padding:0 6px;white-space:nowrap}.b{position:absolute;border:2px solid #b9b4ff;border-radius:3px;background:rgba(185,180,255,.12);box-sizing:border-box}.b.m{border-style:solid;background:rgba(185,180,255,.2)}.b.h{border-style:dashed}</style><div></div>";
  layer = shadow.lastChild;
  document.documentElement.append(host);
};
const box = (element, kind) => {
  const rect = element.getBoundingClientRect();
  const div = document.createElement("div");
  div.className = "b " + kind;
  div.style.cssText = "left:" + (rect.left + scrollX) + "px;top:" + (rect.top + scrollY) + "px;width:" + rect.width + "px;height:" + rect.height + "px";
  return div;
};
const draw = () => {
  ensure();
  layer.replaceChildren();
  for (const who of others) {
    const div = document.createElement("div");
    div.className = "p";
    div.style.left = who.x * innerWidth + "px";
    div.style.top = who.y * innerWidth + "px";
    div.innerHTML = '<svg width="16" height="18" viewBox="0 0 16 18"><path d="M1 1 L1 15 L5 11 L8 17 L10.5 16 L7.5 10 L13 10 Z"/></svg><span></span>';
    div.firstChild.style.fill = who.color;
    div.lastChild.style.background = who.color;
    div.lastChild.textContent = who.name;
    layer.append(div);
  }
  if (markBox && markBox.isConnected) layer.append(box(markBox, "m"));
  if (picking && hoverBox && hoverBox.isConnected && hoverBox !== markBox) layer.append(box(hoverBox, "h"));
};
const pickable = (target) => target instanceof Element && target !== host && target !== document.documentElement ? target : null;
const selector = (element) => {
  const parts = [];
  for (let node = element; node && node.nodeType === 1 && node !== document.documentElement; node = node.parentElement) {
    let part = node.localName;
    if (node.id) { parts.unshift(part + "#" + CSS.escape(node.id)); break; }
    const classes = [...node.classList].filter((name) => /^[A-Za-z_][\\w-]*$/.test(name)).slice(0, 2);
    if (classes.length) part += "." + classes.join(".");
    const parent = node.parentElement;
    if (parent) {
      const same = [...parent.children].filter((child) => child.localName === node.localName);
      if (same.length > 1) part += ":nth-of-type(" + (same.indexOf(node) + 1) + ")";
    }
    parts.unshift(part);
    if (node === document.body) break;
  }
  return parts.join(" > ");
};

addEventListener("pointermove", (event) => {
  post({ type: "cursor", x: event.clientX / innerWidth, y: (event.clientY + scrollY) / innerWidth });
  if (picking) { const target = pickable(event.target); if (target !== hoverBox) { hoverBox = target; draw(); } }
}, { passive: true, capture: true });
document.addEventListener("pointerleave", () => post({ type: "cursor", x: null }));
addEventListener("blur", () => post({ type: "cursor", x: null }));
addEventListener("scroll", () => post({ type: "scroll", y: scrollY }), { passive: true });
addEventListener("resize", draw);

const stop = (event) => { event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation(); };
for (const name of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
  addEventListener(name, (event) => { if (picking) stop(event); }, true);
}
addEventListener("click", (event) => {
  if (picking) {
    stop(event);
    const target = pickable(event.target);
    if (!target) return;
    markBox = target;
    hoverBox = null;
    const rect = target.getBoundingClientRect();
    post({ type: "picked", component: {
      selector: selector(target),
      tag: target.localName,
      html: target.outerHTML.replace(/\\s+/g, " ").slice(0, 2000),
      text: (target.innerText || target.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 300),
      rect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
    } });
    draw();
    return;
  }
  const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (!link) return;
  const href = link.getAttribute("href");
  if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
  event.preventDefault();
  post({ type: /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("//") ? "external" : "navigate", href });
}, true);
addEventListener("submit", (event) => event.preventDefault(), true);
addEventListener("keydown", (event) => { if (event.key === "Escape" && picking) { stop(event); post({ type: "pick-cancel" }); } }, true);

addEventListener("message", (event) => {
  const data = event.data;
  if (event.source !== parent || !data || data.from !== TO) return;
  if (data.type === "cursors") others = Array.isArray(data.list) ? data.list : [];
  else if (data.type === "pick") { picking = !!data.on; hoverBox = null; document.documentElement.style.cursor = picking ? "crosshair" : ""; }
  else if (data.type === "unmark") markBox = null;
  draw();
});
})();`;
}
