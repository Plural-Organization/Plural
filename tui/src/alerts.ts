import type { Tone } from "./feed";

export type AlertListener = (tone: Tone, text: string) => void;

export class Alerts {
  private readonly listeners = new Set<AlertListener>();
  private waiting: [Tone, string][] = [];

  emit(tone: Tone, text: string): void {
    if (this.listeners.size === 0) {
      this.waiting.push([tone, text]);
      return;
    }
    this.listeners.forEach((listener) => listener(tone, text));
  }

  subscribe(listener: AlertListener): () => void {
    this.listeners.add(listener);
    const pending = this.waiting;
    this.waiting = [];
    pending.forEach(([tone, text]) => listener(tone, text));
    return () => this.listeners.delete(listener);
  }
}
