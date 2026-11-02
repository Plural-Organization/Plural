import { useKeyboard } from "@opentui/react";
import { useReducer, useRef } from "react";
import type { AgentControl } from "../control";
import { extras, setExtras, type ExtraStatus } from "../extras";
import { friendlyError } from "../settingsModel";
import { theme } from "../theme";
import { DIALOG_WIDTH } from "./SettingsDialog";

interface Local {
  index: number;
  chosen: ReadonlySet<string>;
  busy: boolean;
  status: { tone: "ok" | "error" | "info"; text: string } | null;
}

export interface ExtrasDialogProps {
  width: number;
  height: number;
  control: AgentControl;
  /** The SDK the user just tried to use, already ticked. */
  preselect: string | null;
  /** Why the dialog opened, shown above the list when it was not the first-run offer. */
  reason: string | null;
  /** `installed` is true when at least one SDK was added. */
  onClose: (installed: boolean) => void;
}

const TONE = { ok: theme.ok, error: theme.danger, info: theme.dim } as const;

/** Rows are the SDKs, then Install and Skip; `index` counts them in that order. */
export function ExtrasDialog(props: ExtrasDialogProps) {
  const [, redraw] = useReducer((value: number) => value + 1, 0);
  const local = useRef<Local>({
    index: 0,
    chosen: new Set(props.preselect === null ? [] : [props.preselect]),
    busy: false,
    status: null,
  });
  const live = useRef(props);
  live.current = props;

  const set = (patch: Partial<Local>): void => {
    local.current = { ...local.current, ...patch };
    redraw();
  };
  const list = (): readonly ExtraStatus[] => extras();
  const installRow = (): number => list().length;
  const skipRow = (): number => list().length + 1;

  const toggle = (extra: ExtraStatus): void => {
    if (extra.installed || local.current.busy) {
      return;
    }
    const chosen = new Set(local.current.chosen);
    if (chosen.has(extra.id)) {
      chosen.delete(extra.id);
    } else {
      chosen.add(extra.id);
    }
    set({ chosen, status: null });
  };

  const install = async (): Promise<void> => {
    const wanted = list().filter((extra) => !extra.installed && local.current.chosen.has(extra.id));
    if (local.current.busy) {
      return;
    }
    if (wanted.length === 0) {
      set({ status: { tone: "info", text: "tick what to install with space, or choose Skip" } });
      return;
    }
    set({ busy: true });
    for (const extra of wanted) {
      set({ status: { tone: "info", text: `installing ${extra.label}… this can take a minute on a slow network` } });
      const result = await live.current.control.install(extra.id);
      if (!result.ok) {
        set({ busy: false, status: { tone: "error", text: friendlyError(result.error ?? "the install did not work") } });
        setExtras(await live.current.control.extras());
        return;
      }
    }
    setExtras(await live.current.control.extras());
    set({ busy: false, status: { tone: "ok", text: "✓ installed" } });
    live.current.onClose(true);
  };

  const activate = (): void => {
    const { index } = local.current;
    if (index === installRow()) {
      void install();
    } else if (index === skipRow()) {
      live.current.onClose(false);
    } else {
      const extra = list()[index];
      if (extra) {
        toggle(extra);
      }
    }
  };

  useKeyboard((key) => {
    key.preventDefault();
    if (local.current.busy) {
      return;
    }
    const rows = list().length + 2;
    const { index } = local.current;
    if (key.name === "escape") {
      live.current.onClose(false);
    } else if (key.name === "up") {
      set({ index: (index + rows - 1) % rows });
    } else if (key.name === "down" || key.name === "tab") {
      set({ index: (index + 1) % rows });
    } else if (key.name === "return" || key.name === "space") {
      activate();
    }
  });

  const boxWidth = Math.min(DIALOG_WIDTH, Math.max(34, props.width - 4));
  const { index, chosen, busy, status } = local.current;

  return (
    <box
      position="absolute"
      top={0}
      left={0}
      width={props.width}
      height={props.height}
      zIndex={30}
      alignItems="center"
      justifyContent="center"
    >
      <box
        width={boxWidth}
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={theme.accent}
        backgroundColor={theme.panel}
        paddingX={2}
      >
        <text>
          <span fg={theme.accent}>
            <b>◆ model SDKs</b>
          </span>
        </text>
        <text fg={theme.dim}>{props.reason ?? "Plural installs without them to stay small."}</text>
        <text fg={theme.dim}>Claude Code and Codex CLI work without any. Install the ones you will use:</text>
        <text>{" "}</text>
        {list().map((extra, position) => {
          const on = position === index;
          const box = extra.installed ? "[✓]" : chosen.has(extra.id) ? "[x]" : "[ ]";
          return (
            <box key={extra.id} flexDirection="row" justifyContent="space-between">
              <text fg={extra.installed ? theme.dim : on ? theme.accent : theme.text}>
                {on ? "› " : "  "}
                {box} {extra.label}
              </text>
              <text fg={theme.dim}>{extra.installed ? "installed" : ""}</text>
            </box>
          );
        })}
        <text>{" "}</text>
        <text fg={index === installRow() ? theme.accent : theme.text}>
          {index === installRow() ? "› " : "  "}[ Install selected ]
        </text>
        <text fg={index === skipRow() ? theme.accent : theme.text}>
          {index === skipRow() ? "› " : "  "}[ Skip for now ]
        </text>
        <text>{" "}</text>
        {status ? <text fg={TONE[status.tone]}>{status.text}</text> : <text fg={theme.dim}>Skipped SDKs can be added later: pick the provider in settings (F2).</text>}
        <text fg={theme.dim}>{busy ? "installing, please wait" : "↑↓ select · space tick · enter confirm · esc skip"}</text>
      </box>
    </box>
  );
}
