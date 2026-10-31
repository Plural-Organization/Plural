import { expect, test } from "vitest";
import type { FeedItem } from "@plural/client";
import { canvasDocs } from "./canvas";
import { componentPrompt } from "./quote";
import { buildSite, localTarget, packageUrl, rewriteImports, siteEntries, siteFiles } from "./site";

let counter = 0;
function tool(name: string, args: Record<string, unknown>, status: "ok" | "failed" | "running" = "ok"): FeedItem {
  counter += 1;
  return {
    kind: "tool",
    id: `t${counter}`,
    call: { id: `c${counter}`, name, args, subject: String(args.path ?? ""), risk: "write" },
    status,
    output: "",
    diff: null,
    live: "",
  } as FeedItem;
}

const decode = (url: string) => new TextDecoder().decode(Uint8Array.from(atob(url.split(",")[1]!), (char) => char.charCodeAt(0)));
const importMap = (html: string) => JSON.parse(/<script type="importmap">([\s\S]*?)<\/script>/.exec(html)![1]!).imports as Record<string, string>;

test("the files are what the agent's writes and edits that went through left", () => {
  const site = siteFiles([
    tool("write", { path: "./site/index.html", content: "<h1>Hi</h1>" }),
    tool("edit", { path: "site/index.html", old: "Hi", new: "Hello" }),
    tool("edit", { path: "site/index.html", old: "Hello", new: "Nope" }, "failed"),
    tool("write", { path: "site/app.js", content: "a a" }, "running"),
    tool("multi_edit", { path: "site/index.html", edits: [{ old: "h1", new: "h2", replace_all: true }, { old: "Hello", new: "Hey" }] }),
  ]);
  expect([...site.files]).toEqual([["site/index.html", "<h2>Hey</h2>"]]);
  expect(site.version).toBe(3);
});

test("an edit that no longer matches leaves the file as it was", () => {
  const site = siteFiles([tool("write", { path: "a.html", content: "one" }), tool("edit", { path: "a.html", old: "two", new: "three" })]);
  expect(site.files.get("a.html")).toBe("one");
  expect(site.version).toBe(1);
});

test("a page is each index.html, or an HTML file in a folder without one", () => {
  const files = new Map([["web/index.html", ""], ["web/about.html", ""], ["demo.html", ""], ["web/app.js", ""]]);
  expect(siteEntries(files)).toEqual(["web/index.html", "demo.html"]);
});

test("links inside the site resolve from the page that has them", () => {
  expect(localTarget("web/index.html", "about.html#team")).toBe("web/about.html");
  expect(localTarget("web/blog/index.html", "../index.html")).toBe("web/index.html");
  expect(localTarget("web/index.html", "https://example.com")).toBeNull();
  expect(localTarget("web/index.html", "#top")).toBeNull();
});

test("imports and re-exports have their module names rewritten, other strings stay", () => {
  const code = `import React, { useState } from "react";\nimport "./a.css";\nexport { b } from './b';\nconst c = await import("./c");\nconst s = "from './no'";`;
  expect(rewriteImports(code, (specifier) => `<${specifier}>`)).toBe(
    `import React, { useState } from "<react>";\nimport "<./a.css>";\nexport { b } from '<./b>';\nconst c = await import("<./c>");\nconst s = "from './no'";`,
  );
});

test("packages come from esm.sh at the project's versions and leave React to the page", () => {
  const versions = { react: "^19.1.0", "react-dom": "^19.1.0", "framer-motion": "11.0.0" };
  expect(packageUrl("react/jsx-runtime", versions, true)).toBe("https://esm.sh/react@^19.1.0/jsx-runtime");
  expect(packageUrl("react-dom/client", versions, true)).toBe("https://esm.sh/react-dom@^19.1.0/client?external=react");
  expect(packageUrl("framer-motion", versions, true)).toBe("https://esm.sh/framer-motion@11.0.0?external=react,react-dom");
  expect(packageUrl("@scope/pkg/sub", {}, false)).toBe("https://esm.sh/@scope/pkg/sub");
});

test("a static page gets its stylesheet, script and pictures inline and the bridge first", async () => {
  const files = new Map([
    ["site/index.html", `<!doctype html><html><head><link rel="stylesheet" href="style.css"><link rel="stylesheet" href="https://cdn.example/x.css"></head><body><img src="logo.svg"><script src="app.js"></script></body></html>`],
    ["site/style.css", "h1 { color: red }"],
    ["site/app.js", "console.log('</script>')"],
    ["site/logo.svg", "<svg/>"],
  ]);
  const { html, problems } = await buildSite(files, "site/index.html", "BRIDGE");
  expect(problems).toEqual([]);
  expect(html).toContain("<head><script>BRIDGE</script><style");
  expect(html).toContain(`<style data-from="site/style.css">h1 { color: red }</style>`);
  expect(html).toContain(`href="https://cdn.example/x.css"`);
  expect(html).toContain(`<img src="data:image/svg+xml;base64,`);
  expect(html).toContain("<script>console.log('<\\/script>')</script>");
  expect(html).not.toContain("importmap");
});

test("a React page is compiled into modules joined by an import map", async () => {
  const files = new Map([
    ["app/package.json", JSON.stringify({ dependencies: { react: "^19.1.0", "react-dom": "^19.1.0" } })],
    ["app/index.html", `<html><head></head><body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body></html>`],
    ["app/src/main.tsx", `import { createRoot } from "react-dom/client";\nimport App from "./App";\nimport "./index.css";\ncreateRoot(document.getElementById("root")!).render(<App />);`],
    ["app/src/App.tsx", `import data from "../data.json";\nexport default function App(): JSX.Element { return <h1>{data.title}</h1>; }`],
    ["app/src/index.css", "body { margin: 0 }"],
    ["app/data.json", `{ "title": "Hi" }`],
  ]);
  const { html, problems } = await buildSite(files, "app/index.html");
  expect(problems).toEqual([]);
  expect(html).toContain(`<script type="module">import "@site/app/src/main.tsx";</script>`);
  const map = importMap(html);
  expect(Object.keys(map).sort()).toEqual(["@site/app/data.json", "@site/app/src/App.tsx", "@site/app/src/index.css", "@site/app/src/main.tsx", "react", "react-dom", "react-dom/client", "react/jsx-runtime"]);
  expect(map["react/jsx-runtime"]).toBe("https://esm.sh/react@^19.1.0/jsx-runtime");
  const main = decode(map["@site/app/src/main.tsx"]!);
  expect(main).toContain(`from "@site/app/src/App.tsx"`);
  expect(main).toContain(`import "@site/app/src/index.css"`);
  expect(main).not.toContain("!)");
  expect(decode(map["@site/app/src/App.tsx"]!)).toContain(`from "@site/app/data.json"`);
});

test("a module the agent did not write is named, and the page still builds", async () => {
  const files = new Map([
    ["index.html", `<script type="module">import { x } from "./missing.js"; console.log(x);</script><script src="gone.js"></script>`],
  ]);
  const { html, problems } = await buildSite(files, "index.html");
  expect(problems).toEqual([
    "missing.js is not in the preview: the agent did not write it with write or edit",
    "gone.js is not in the preview: the agent did not write it with write or edit",
  ]);
  expect(html).toContain(`from "data:text/javascript;base64,`);
});

test("code that does not compile is reported", async () => {
  const files = new Map([["index.html", `<script type="module" src="a.tsx"></script>`], ["a.tsx", "const = ;"]]);
  const { problems } = await buildSite(files, "index.html");
  expect(problems[0]).toMatch(/^a\.tsx does not compile/);
});

test("a site opens in the canvas after the write that made its page", () => {
  const items = [tool("write", { path: "site/style.css", content: "" }), tool("write", { path: "site/index.html", content: "<p>x</p>" }), tool("edit", { path: "site/index.html", old: "x", new: "y" })];
  const sites = canvasDocs(items).filter((doc) => doc.kind === "site");
  expect(sites).toEqual([{ id: "site:site/index.html", title: "preview · site/index.html", kind: "site", lang: "html", text: "site/index.html", live: false, auto: true, path: "site/index.html" }]);
});

test("a picked component is quoted in the prompt with where it is", () => {
  const prompt = componentPrompt("site/index.html", { selector: "main > a.cta", tag: "a", html: `<a class="cta">Go</a>` }, "  make it bigger ");
  expect(prompt).toBe("> component `main > a.cta` on site/index.html\n> <a class=\"cta\">Go</a>\n\nmake it bigger");
});

test("a page in a subfolder resolves paths from / at the site's root, and sprite links stay", async () => {
  const files = new Map([
    ["site/index.html", ""],
    ["site/blog/post.html", `<link rel="stylesheet" href="/style.css"><svg><use href="../icons.svg#star"></use></svg><img src="../icons.svg">`],
    ["site/style.css", "p { margin: 0 }"],
    ["site/icons.svg", "<svg/>"],
  ]);
  const { html, problems } = await buildSite(files, "site/blog/post.html", "", "site");
  expect(problems).toEqual([]);
  expect(html).toContain(`<style data-from="site/style.css">`);
  expect(html).toContain(`<use href="../icons.svg#star">`);
  expect(html).toContain(`<img src="data:image/svg+xml;base64,`);
});
