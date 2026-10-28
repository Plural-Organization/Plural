let context: AudioContext | null = null;
let restoreTitle: (() => void) | null = null;

export function beep(): void {
  try {
    context ??= new AudioContext();
    const sound = context;
    void sound.resume();
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

export function alertMention(who: string, direct: boolean): void {
  beep();
  flagTitle(direct ? `${who} wrote to you` : `${who} mentioned you`);
}
