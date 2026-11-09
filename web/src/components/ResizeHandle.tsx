import { useEffect, useRef, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";

interface ResizeHandleProps {
  label: string;
  width: number;
  bounds: { min: number; max: number };
  // +1 when dragging right widens the panel (a panel on the left), -1 when it narrows it.
  direction: 1 | -1;
  onResize: (width: number) => void;
  className?: string;
  style?: CSSProperties;
}

const stopResizing = () => document.documentElement.removeAttribute("data-resizing");

// The edge of a side panel: drag it to change the width, or nudge it with the arrow keys.
export function ResizeHandle({ label, width, bounds, direction, onResize, className, style }: ResizeHandleProps) {
  const dragging = useRef(false);
  // A drag cut short by the handle going away (a canvas opening) must not leave the page in drag mode.
  useEffect(() => () => {
    if (dragging.current) stopResizing();
  }, []);
  const start = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const from = event.clientX;
    const move = (moved: PointerEvent) => onResize(width + direction * (moved.clientX - from));
    const end = () => {
      dragging.current = false;
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("lostpointercapture", end);
      stopResizing();
    };
    dragging.current = true;
    document.documentElement.setAttribute("data-resizing", "");
    handle.addEventListener("pointermove", move);
    // Fires on pointerup and pointercancel too, once the capture ends.
    handle.addEventListener("lostpointercapture", end);
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={bounds.min}
      aria-valuemax={bounds.max}
      tabIndex={0}
      className={`resize-handle ${className ?? ""}`}
      style={style}
      onPointerDown={start}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          onResize(width + direction * (event.key === "ArrowRight" ? 16 : -16));
        }
      }}
    />
  );
}
