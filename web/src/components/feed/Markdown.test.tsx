import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { Markdown } from "./Markdown";

const render = (text: string) => renderToStaticMarkup(<Markdown text={text} />);

test("renders code, emphasis and lists", () => {
  const html = render("**bold** and `code`\n\n- one\n- two\n\n```py\nprint(1)\n```");
  expect(html).toContain("<strong>bold</strong>");
  expect(html).toContain("<code>code</code>");
  expect(html).toContain("<li>one</li>");
  expect(html).toContain('data-lang="py"');
});

test("never renders raw html from the model", () => {
  const html = render('<img src=x onerror="alert(1)"> <script>alert(1)</script>');
  expect(html).not.toContain("<img");
  expect(html).not.toContain("<script");
  expect(html).toContain("&lt;script&gt;");
});

test("links only to http and https", () => {
  expect(render("[docs](https://example.com)")).toContain('href="https://example.com"');
  expect(render("[bad](javascript:alert(1))")).not.toContain("href");
});

test("keeps underscores inside words", () => {
  expect(render("call foo_bar_baz now")).toContain("foo_bar_baz");
});
