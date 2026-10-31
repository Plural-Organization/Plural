export function briefAgent(label: string): string {
  const [provider = "", ...rest] = label.split(" · ");
  const model = rest.join(" · ");
  if (!model.startsWith("claude-")) {
    return label;
  }
  const short = model
    .slice("claude-".length)
    .replace(/-\d{8}$/, "")
    .replace(/(\d)-(\d)/g, "$1.$2")
    .replace(/-/g, " ");
  return `${provider} · ${short}`;
}
