import { Button, Kbd, Popover } from "@heroui/react";
import { ArrowLeft, ArrowRight, X } from "@phosphor-icons/react";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import type { TourStep } from "../lib/onboarding";
import { LogoMark } from "./LogoMark";

interface TourProps {
  steps: TourStep[];
  // Called before a step shows, so the room can open what the step points at.
  onStep?: (step: TourStep) => void;
  onClose: (how: "done" | "skipped") => void;
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

const PAD = 6;

function find(step: TourStep): HTMLElement | null {
  if (step.target === null) {
    return null;
  }
  const element = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
  if (element === null) {
    return null;
  }
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 ? element : null;
}

function boxOf(element: HTMLElement): Box {
  const rect = element.getBoundingClientRect();
  return { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 };
}

// A phone has no room beside the panel: a card meant to sit at its side goes above (or, flipped, below) instead.
const sideways = (placement: TourStep["placement"]) => placement === "left" || placement === "right";

const same =(a: Box | null, b: Box | null) => a === b || (a !== null && b !== null && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

// A first-visit walk through the room: the page dims, the thing a step is about stays lit, and a HeroUI popover
// with an arrow points at it. A step whose element is not on screen (a guest has no agent switch) is passed over.
export function Tour({ steps, onStep, onClose }: TourProps) {
  const [index, setIndex] = useState(0);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  // Which way the reader moves, so a missing element is skipped in that direction.
  const heading = useRef<1 | -1>(1);
  const step = steps[index]!;
  const last = index === steps.length - 1;

  useLayoutEffect(() => {
    onStep?.(step);
    if (step.target === null) {
      setTarget(null);
      setBox(null);
      return;
    }
    // The panel may still be sliding in: look for the element over a few frames before passing the step over.
    let frame = 0;
    let tries = 0;
    const look = () => {
      const element = find(step);
      if (element !== null) {
        element.scrollIntoView({ block: "nearest", inline: "nearest" });
        setTarget(element);
        setBox(boxOf(element));
        return;
      }
      tries += 1;
      if (tries < 20) {
        frame = requestAnimationFrame(look);
        return;
      }
      const next = index + heading.current;
      if (next >= 0 && next < steps.length) {
        setIndex(next);
      } else {
        onClose("done");
      }
    };
    look();
    return () => cancelAnimationFrame(frame);
  }, [index]);

  // The room moves under the tour (the panel slides, the window resizes): the light follows its element.
  useEffect(() => {
    if (target === null) {
      return;
    }
    let frame = 0;
    const follow = () => {
      const next = boxOf(target);
      setBox((current) => (same(current, next) ? current : next));
      frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  const go = (delta: 1 | -1) => {
    if (delta === 1 && last) {
      onClose("done");
      return;
    }
    heading.current = delta;
    setIndex((current) => Math.min(steps.length - 1, Math.max(0, current + delta)));
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose("skipped");
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        go(1);
      } else if (event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        go(-1);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const card = <TourCard step={step} index={index} count={steps.length} onBack={index > 0 ? () => go(-1) : undefined} onNext={() => go(1)} onSkip={() => onClose("skipped")} />;
  const lit = step.target !== null && target !== null && box !== null;

  return createPortal(
    <div className="tour" data-centered={!lit}>
      {lit ? (
        <div className="tour-spot" style={{ top: box.top, left: box.left, width: box.width, height: box.height } as CSSProperties} aria-hidden="true" />
      ) : (
        <div className="tour-dim" aria-hidden="true" />
      )}
      {lit ? (
        <Popover.Content key={step.id} isOpen isNonModal triggerRef={{ current: target }} placement={sideways(step.placement) && window.innerWidth < 640 ? "top" : step.placement} offset={PAD + 12} shouldFlip className="popover tour-pop">
          <Popover.Arrow />
          <Popover.Dialog aria-label={step.title} className="outline-none">{card}</Popover.Dialog>
        </Popover.Content>
      ) : step.target === null ? (
        <div key={step.id} role="dialog" aria-modal="true" aria-label={step.title} className="tour-center">
          <div className="tour-mark" aria-hidden="true"><LogoMark size={30} /></div>
          {card}
        </div>
      ) : null}
    </div>,
    document.body,
  );
}

interface TourCardProps {
  step: TourStep;
  index: number;
  count: number;
  onBack?: () => void;
  onNext: () => void;
  onSkip: () => void;
}

export function TourCard({ step, index, count, onBack, onNext, onSkip }: TourCardProps) {
  const last = index === count - 1;
  return (
    <div className="tour-card">
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-xs text-muted" aria-label={`Step ${index + 1} of ${count}`}>
          {String(index + 1).padStart(2, "0")} / {String(count).padStart(2, "0")}
        </span>
        {last ? null : (
          <Button size="sm" variant="ghost" className="-mr-2 h-7 px-2 text-muted" onPress={onSkip}>
            Skip tour
            <X size={13} />
          </Button>
        )}
      </div>
      <h3 className="mt-2 font-display text-lg font-semibold tracking-[-0.015em]">{step.title}</h3>
      <p className="mt-1 text-sm leading-relaxed text-muted text-pretty">{step.body}</p>
      <div className="mt-4 flex items-center gap-3">
        <span className="tour-dots" aria-hidden="true">
          {Array.from({ length: count }, (_, dot) => (
            <i key={dot} data-on={dot === index} data-past={dot < index} />
          ))}
        </span>
        <span className="grow" />
        {onBack ? (
          <Button size="sm" variant="ghost" isIconOnly aria-label="Back" onPress={onBack}>
            <ArrowLeft size={15} />
          </Button>
        ) : null}
        <Button size="sm" variant="primary" autoFocus onPress={onNext}>
          {index === 0 ? "Show me" : last ? "Start working" : "Next"}
          {last ? null : <ArrowRight size={14} />}
        </Button>
      </div>
      {index === 0 ? (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-muted">
          <Kbd className="h-5 px-1 text-[11px]"><Kbd.Content>←</Kbd.Content></Kbd>
          <Kbd className="h-5 px-1 text-[11px]"><Kbd.Content>→</Kbd.Content></Kbd>
          to move,
          <Kbd className="h-5 px-1 text-[11px]"><Kbd.Content>esc</Kbd.Content></Kbd>
          to skip
        </p>
      ) : null}
    </div>
  );
}
