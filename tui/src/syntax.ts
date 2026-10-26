import { RGBA, SyntaxStyle, type CliRenderer } from "@opentui/core";
import { theme } from "./theme";

export function createSyntaxStyle(renderer: CliRenderer): SyntaxStyle {
  const color = (hex: string) => RGBA.fromHex(hex);
  return SyntaxStyle.fromStyles(
    {
      default: { fg: color(theme.text) },
      keyword: { fg: color(theme.code), bold: true },
      string: { fg: color(theme.ok) },
      comment: { fg: color(theme.dim), italic: true },
      number: { fg: color(theme.warn) },
      function: { fg: color(theme.accent) },
      "markup.heading": { fg: color(theme.accent), bold: true },
      "markup.strong": { bold: true },
      "markup.italic": { italic: true },
      "markup.raw": { fg: color(theme.code) },
      "markup.link": { fg: color(theme.accent), underline: true },
    },
    renderer.nativeScene!,
  );
}
