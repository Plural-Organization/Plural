import { Button, InputGroup } from "@heroui/react";
import { Check, Copy } from "@phosphor-icons/react";
import { useState } from "react";
import { copyText } from "../lib/clipboard";

// A line of text to copy: read-only, with the copy button inside the field.
export function CopyBox({ text, label, multiline = false }: { text: string; label: string; multiline?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    void copyText(text).then((ok) => {
      setCopied(ok);
      setTimeout(() => setCopied(false), 1600);
    });
  const button = (
    <Button size="sm" variant="secondary" aria-label={label} onPress={copy}>
      {copied ? <Check size={15} /> : <Copy size={15} />}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
  return (
    <InputGroup fullWidth>
      {multiline ? (
        <>
          <InputGroup.TextArea readOnly rows={5} value={text} aria-label={label} className="font-mono text-[12.5px]" />
          <InputGroup.Suffix className="self-start pt-1.5">{button}</InputGroup.Suffix>
        </>
      ) : (
        <>
          <InputGroup.Input readOnly value={text} aria-label={label} className="font-mono text-[13px]" />
          <InputGroup.Suffix>{button}</InputGroup.Suffix>
        </>
      )}
    </InputGroup>
  );
}
