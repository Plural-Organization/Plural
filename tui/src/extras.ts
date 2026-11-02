import type { Preset } from "./presets";

/**
 * The model SDKs the host ships as optional extras (`plural-agent[anthropic]`, `[openai]`). The host
 * says which are installed and installs one on request, so the client keeps no list of its own; a host
 * that does not report any, or a room the client only joined, simply has nothing to offer.
 */
export interface ExtraStatus {
  id: string;
  label: string;
  installed: boolean;
}

let known: ExtraStatus[] = [];

export function setExtras(list: readonly ExtraStatus[]): void {
  known = [...list];
}

export function extras(): readonly ExtraStatus[] {
  return known;
}

export function missingExtras(): ExtraStatus[] {
  return known.filter((extra) => !extra.installed);
}

/** The SDK a preset still needs, or null when it needs none or it is already installed. */
export function missingFor(preset: Preset): ExtraStatus | null {
  if (!preset.extra) {
    return null;
  }
  return known.find((extra) => extra.id === preset.extra && !extra.installed) ?? null;
}
