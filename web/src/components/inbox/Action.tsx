import { Button, Kbd } from "@heroui/react";
import type { ReactNode } from "react";

interface ActionProps {
  // The key that does the same; the room's hotkeys listen for it.
  hint?: string;
  tone?: string | undefined;
  type?: "button" | "submit";
  onPress?: () => void;
  children: ReactNode;
}

const VARIANT = { primary: "primary", danger: "danger" } as const;

export function Action({ hint, tone, type = "button", onPress, children }: ActionProps) {
  const variant = VARIANT[tone as keyof typeof VARIANT] ?? "tertiary";
  return (
    <Button size="sm" variant={variant} type={type} onPress={onPress}>
      {hint ? <Kbd className="h-5 min-w-5 bg-black/10 px-1 text-[11px] text-current"><Kbd.Content>{hint}</Kbd.Content></Kbd> : null}
      <span className="cap">{children}</span>
    </Button>
  );
}
