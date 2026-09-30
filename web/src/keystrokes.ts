import type { Keystroke } from './types';

/** Records key down/up and input events with performance.now() timestamps. */
export class KeystrokeLogger {
  events: Keystroke[] = [];
  private el: HTMLTextAreaElement | null = null;
  private onDown = (e: KeyboardEvent) => this.events.push({ t: performance.now(), type: 'down', key: this.safeKey(e.key), code: e.code });
  private onUp = (e: KeyboardEvent) => this.events.push({ t: performance.now(), type: 'up', key: this.safeKey(e.key), code: e.code });
  private onInput = (e: Event) => this.events.push({ t: performance.now(), type: 'input', len: (e.target as HTMLTextAreaElement).value.length });

  /** Printable characters are logged as-is (the final text is stored anyway); modifiers by name. */
  private safeKey(k: string): string {
    return k.length === 1 ? k : k.slice(0, 16);
  }

  attach(el: HTMLTextAreaElement): void {
    this.detach();
    this.el = el;
    el.addEventListener('keydown', this.onDown);
    el.addEventListener('keyup', this.onUp);
    el.addEventListener('input', this.onInput);
  }

  detach(): void {
    if (!this.el) return;
    this.el.removeEventListener('keydown', this.onDown);
    this.el.removeEventListener('keyup', this.onUp);
    this.el.removeEventListener('input', this.onInput);
    this.el = null;
  }
}
