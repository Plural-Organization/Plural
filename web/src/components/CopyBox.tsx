import { Button } from "@heroui/react";
import { Check, Copy } from "@phosphor-icons/react";
import { useState } from "react";
import { copyText } from "../lib/clipboard";

export function CopyBox({ text, label, multiline = false }: { text: string; label: string; multiline?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-start gap-2 rounded-2xl border border-border bg-background py-1.5 pr-1.5 pl-4">
      {multiline ? (
        <pre className="max-h-44 min-w-0 flex-1 overflow-auto bg-transparent py-1.5 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap">{text}</pre>
      ) : (
        <code className="min-w-0 flex-1 truncate bg-transparent p-0 py-2 font-mono text-[13px]">{text}</code>
      )}
      <Button
        size="sm"
        variant="secondary"
        aria-label={label}
        onPress={() =>
          void copyText(text).then((ok) => {
            setCopied(ok);
            setTimeout(() => setCopied(false), 1600);
          })
        }
      >
        {copied ? <Check size={15} /> : <Copy size={15} />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}
