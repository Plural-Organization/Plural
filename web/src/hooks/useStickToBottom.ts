import { useEffect, useRef, useState, type UIEvent } from "react";

const THRESHOLD = 80;

export function useStickToBottom(feed: unknown, status: string | undefined) {
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [behind, setBehind] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (element && pinned.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [feed, status]);

  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < THRESHOLD;
    pinned.current = atBottom;
    setBehind(!atBottom);
  };

  const pin = () => {
    pinned.current = true;
  };

  const jump = () => {
    pinned.current = true;
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  };

  return { ref, onScroll, behind, pin, jump };
}
