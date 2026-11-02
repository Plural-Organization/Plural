import type { Preset } from "./presets";

export interface ToolStatus {
  id: string;
  label: string;
  installed: boolean;
  command: string;
  canInstall: boolean;
  login: string;
}

let known: ToolStatus[] = [];

export function setTools(list: readonly ToolStatus[]): void {
  known = [...list];
}

export function tools(): readonly ToolStatus[] {
  return known;
}

export function toolFor(preset: Preset): ToolStatus | null {
  if (!preset.tool) {
    return null;
  }
  return known.find((tool) => tool.id === preset.tool) ?? null;
}

export function missingTool(preset: Preset): ToolStatus | null {
  const tool = toolFor(preset);
  return tool !== null && !tool.installed ? tool : null;
}
