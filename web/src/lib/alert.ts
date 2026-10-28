let context: AudioContext | null = null;
let restoreTitle: (() => void) | null = null;

function audio(): AudioContext {
  if (context === null || context.state === "closed") {
    context = new AudioContext();
  }
  return context;
}

/** Called synchronously from the join gesture so browsers allow later audio. */
export function unlockAudio(): void {
  try {
    void audio().resume().catch(() => undefined);
  } catch {
    return;
  }
}

export function beep(): void {
  try {
    const sound = audio();
    if (sound.state !== "running") {
      void sound.resume().then(() => {
        if (sound.state === "running") play(sound);
      }).catch(() => undefined);
      return;
    }
    play(sound);
  } catch {
    return;
  }
}

function play(sound: AudioContext): void {
  try {
    const oscillator = sound.createOscillator();
    const gain = sound.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, sound.currentTime);
    oscillator.frequency.setValueAtTime(1175, sound.currentTime + 0.09);
    gain.gain.setValueAtTime(0.0001, sound.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.18, sound.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, sound.currentTime + 0.22);
    oscillator.connect(gain).connect(sound.destination);
    oscillator.start();
    oscillator.stop(sound.currentTime + 0.24);
  } catch {
    return;
  }
}

export function flagTitle(text: string): void {
  if (!document.hidden) {
    return;
  }
  restoreTitle?.();
  const original = document.title;
  document.title = `✉ ${text}`;
  const restore = (): void => {
    document.title = original;
    window.removeEventListener("focus", restore);
    document.removeEventListener("visibilitychange", onVisible);
    restoreTitle = null;
  };
  const onVisible = (): void => {
    if (!document.hidden) {
      restore();
    }
  };
  window.addEventListener("focus", restore);
  document.addEventListener("visibilitychange", onVisible);
  restoreTitle = restore;
}

export function alertNotice(text: string): void {
  beep();
  flagTitle(text);
}

export function alertMention(who: string, direct: boolean): void {
  alertNotice(direct ? `${who} wrote to you` : `${who} mentioned you`);
}
