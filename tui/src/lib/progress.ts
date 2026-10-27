const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export interface Progress {
  step: (text: string) => void;
  done: () => void;
}

// A one-line spinner on stderr for the work done before the TUI takes over the screen.
export function startProgress(stream: NodeJS.WriteStream = process.stderr): Progress {
  if (!stream.isTTY) {
    return { step: () => {}, done: () => {} };
  }
  let text = "";
  let frame = 0;
  let started = 0;
  let timer: ReturnType<typeof setInterval> | null = null;
  const draw = (): void => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    const elapsed = seconds >= 2 ? ` \x1b[2m${seconds}s\x1b[22m` : "";
    stream.write(`\r\x1b[2K\x1b[36m${FRAMES[frame]}\x1b[39m ${text}${elapsed}`);
    frame = (frame + 1) % FRAMES.length;
  };
  return {
    step: (next) => {
      text = next;
      if (timer === null) {
        started = Date.now();
        stream.write("\x1b[?25l");
        timer = setInterval(draw, 90);
      }
      draw();
    },
    done: () => {
      if (timer === null) {
        return;
      }
      clearInterval(timer);
      timer = null;
      stream.write("\r\x1b[2K\x1b[?25h");
    },
  };
}
