import { createContext, useContext, type ReactNode } from "react";
import { matchMention, type Mentionable } from "@plural/client";
import { colorFor } from "../../lib/colors";

export const MentionPeople = createContext<Mentionable[]>([]);

export function Mentions({ text }: { text: string }) {
  const people = useContext(MentionPeople);
  const result: ReactNode[] = [];
  let start = 0;
  for (let at = text.indexOf("@"); at !== -1; at = text.indexOf("@", at + 1)) {
    if (at > 0 && !/[\s(]/.test(text[at - 1]!)) continue;
    const person = matchMention(text.slice(at + 1), people);
    if (!person) continue;
    if (at > start) result.push(text.slice(start, at));
    const end = at + person.label.length + 1;
    result.push(<span key={at} data-mention={person.id} title={`${person.label} · ${person.role}`} style={{ color: colorFor(person.id), background: "color-mix(in srgb, currentColor 12%, transparent)", borderRadius: 4, padding: "1px 4px", fontWeight: 600 }}>{text.slice(at, end)}</span>);
    start = end;
    at = end - 1;
  }
  if (start < text.length) result.push(text.slice(start));
  return <>{result}</>;
}
