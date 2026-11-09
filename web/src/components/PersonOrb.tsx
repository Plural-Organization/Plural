import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from "react";
import type { OrbName } from "../lib/orbs";

// Each orb, and the runtime they share, loads only when someone first shows it.
const LOADERS: Record<OrbName, () => Promise<import("../vendor/orbkit/core").OrbVariant>> = {
  "shdr-11": () => import("../vendor/orbkit/shdr-11").then((m) => m.shdr11Orb),
  "shdr-12": () => import("../vendor/orbkit/shdr-12").then((m) => m.shdr12Orb),
  "shdr-13": () => import("../vendor/orbkit/shdr-13").then((m) => m.shdr13Orb),
  "shdr-14": () => import("../vendor/orbkit/shdr-14").then((m) => m.shdr14Orb),
  "shdr-16": () => import("../vendor/orbkit/shdr-16").then((m) => m.shdr16Orb),
  "shdr-17": () => import("../vendor/orbkit/shdr-17").then((m) => m.shdr17Orb),
  "shdr-21": () => import("../vendor/orbkit/shdr-21").then((m) => m.shdr21Orb),
  "shdr-23": () => import("../vendor/orbkit/shdr-23").then((m) => m.shdr23Orb),
  "shdr-24": () => import("../vendor/orbkit/shdr-24").then((m) => m.shdr24Orb),
  "shdr-27": () => import("../vendor/orbkit/shdr-27").then((m) => m.shdr27Orb),
  "shdr-29": () => import("../vendor/orbkit/shdr-29").then((m) => m.shdr29Orb),
  "shdr-30": () => import("../vendor/orbkit/shdr-30").then((m) => m.shdr30Orb),
  "shdr-32": () => import("../vendor/orbkit/shdr-32").then((m) => m.shdr32Orb),
  "shdr-33": () => import("../vendor/orbkit/shdr-33").then((m) => m.shdr33Orb),
};

interface OrbProps {
  state: "idle" | "thinking" | "speaking";
  paused: boolean;
  size: number;
  className?: string;
}

const loaded = new Map<OrbName, LazyExoticComponent<ComponentType<OrbProps>>>();

function component(name: OrbName) {
  let orb = loaded.get(name);
  if (orb === undefined) {
    orb = lazy(async () => {
      const [{ ShaderOrb }, variant] = await Promise.all([import("../vendor/orbkit/core"), LOADERS[name]()]);
      return { default: (props: OrbProps) => <ShaderOrb variant={variant} {...props} /> };
    });
    loaded.set(name, orb);
  }
  return orb;
}

// One of the orbs, running; whatever is behind it shows until its first frame lands.
export function PersonOrb({ orb, ...props }: OrbProps & { orb: OrbName }) {
  const Orb = component(orb);
  return (
    <Suspense fallback={null}>
      <Orb {...props} />
    </Suspense>
  );
}
