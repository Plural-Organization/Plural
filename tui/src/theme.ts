export type ThemeName = "plural" | "tokyo" | "light" | "gruvbox" | "mono";

export interface Palette {
  bg: string;
  panel: string;
  bubble: string;
  you: string;
  line: string;
  text: string;
  /** Secondary text: quieter than text, still easy to read. */
  muted: string;
  dim: string;
  accent: string;
  ok: string;
  warn: string;
  danger: string;
  info: string;
  code: string;
  diffBg: string;
  addBg: string;
  removeBg: string;
  addMark: string;
  removeMark: string;
  people: string[];
}

export const THEMES: Record<ThemeName, { label: string; colors: Palette }> = {
  // The web client's colours (web/src/styles/tokens.css); the line is lighter there because a terminal border is one cell thick.
  plural: {
    label: "Plural",
    colors: {
      bg: "#0e0f11",
      panel: "#16171a",
      bubble: "#1d1e22",
      you: "#23233a",
      line: "#2e3037",
      text: "#ecebe7",
      muted: "#9a9ca2",
      dim: "#63656c",
      accent: "#b9b4ff",
      ok: "#8fdca6",
      warn: "#ecc47e",
      danger: "#ff9a9a",
      info: "#9fd8ff",
      code: "#d6a8ff",
      diffBg: "#131417",
      addBg: "#1e2823",
      removeBg: "#2b2021",
      addMark: "#354d3e",
      removeMark: "#56393a",
      people: ["#9fd8ff", "#ffc48a", "#a6e3b4", "#ff9fc4", "#e3d27a", "#c7b5ff", "#8fe0d6", "#ffb3a1"],
    },
  },
  tokyo: {
    label: "Tokyo Night",
    colors: {
      bg: "#16161e",
      panel: "#1a1b26",
      bubble: "#202335",
      you: "#1e2d4d",
      line: "#2a2e42",
      text: "#c0caf5",
      muted: "#9aa5ce",
      dim: "#565f89",
      accent: "#7aa2f7",
      ok: "#9ece6a",
      warn: "#e0af68",
      danger: "#f7768e",
      info: "#7dcfff",
      code: "#bb9af7",
      diffBg: "#1c1e2b",
      addBg: "#1f3a2a",
      removeBg: "#3d1f2b",
      addMark: "#2f6b45",
      removeMark: "#7a2f45",
      people: ["#7dcfff", "#bb9af7", "#e0af68", "#9ece6a", "#f7768e", "#73daca", "#ff9e64", "#7aa2f7"],
    },
  },
  light: {
    label: "Daylight",
    colors: {
      bg: "#fafafc",
      panel: "#eeeff4",
      bubble: "#e8e9f1",
      you: "#d9e4ff",
      line: "#d3d5e0",
      text: "#2a2b3d",
      muted: "#5b5e75",
      dim: "#82859b",
      accent: "#2f5bea",
      ok: "#2e8b3d",
      warn: "#a86a00",
      danger: "#cf2552",
      info: "#0b8aa6",
      code: "#8239e0",
      diffBg: "#f1f2f6",
      addBg: "#d9f2de",
      removeBg: "#f9dde4",
      addMark: "#a8e0b4",
      removeMark: "#f0aebf",
      people: ["#0b8aa6", "#8239e0", "#a86a00", "#2e8b3d", "#cf2552", "#00877a", "#c4540a", "#2f5bea"],
    },
  },
  gruvbox: {
    label: "Gruvbox",
    colors: {
      bg: "#1d2021",
      panel: "#282828",
      bubble: "#32302f",
      you: "#2b3a3a",
      line: "#3c3836",
      text: "#ebdbb2",
      muted: "#bdae93",
      dim: "#928374",
      accent: "#83a598",
      ok: "#b8bb26",
      warn: "#fabd2f",
      danger: "#fb4934",
      info: "#8ec07c",
      code: "#d3869b",
      diffBg: "#242424",
      addBg: "#32361a",
      removeBg: "#3c1f1e",
      addMark: "#5a6326",
      removeMark: "#7a3330",
      people: ["#83a598", "#d3869b", "#fabd2f", "#b8bb26", "#fb4934", "#8ec07c", "#fe8019", "#458588"],
    },
  },
  mono: {
    label: "High contrast",
    colors: {
      bg: "#000000",
      panel: "#111111",
      bubble: "#1c1c1c",
      you: "#1f1f4a",
      line: "#4a4a4a",
      text: "#ffffff",
      muted: "#d0d0d0",
      dim: "#a0a0a0",
      accent: "#ffffff",
      ok: "#00ff87",
      warn: "#ffd700",
      danger: "#ff5f5f",
      info: "#5fd7ff",
      code: "#d7afff",
      diffBg: "#161616",
      addBg: "#003d1f",
      removeBg: "#4a0016",
      addMark: "#00703a",
      removeMark: "#8a0030",
      people: ["#5fd7ff", "#d7afff", "#ffd700", "#00ff87", "#ff5f5f", "#87ffd7", "#ffaf5f", "#afd7ff"],
    },
  },
};

export const THEME_NAMES = Object.keys(THEMES) as ThemeName[];

export const theme: Palette = { ...THEMES.plural.colors };

export function setTheme(name: ThemeName): void {
  Object.assign(theme, THEMES[name].colors);
}

export function colorFor(participantId: string): string {
  let hash = 0;
  for (const char of participantId) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return theme.people[hash % theme.people.length] as string;
}
