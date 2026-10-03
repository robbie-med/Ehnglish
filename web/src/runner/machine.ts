/** Pure state machine for the timed task runner. Driven entirely by the form definition. */
import type { Form, Item, Task, Timing } from '../types';

export type Phase = 'intro' | 'task_intro' | 'stimulus' | 'prep' | 'prompt' | 'respond' | 'review' | 'done';

export interface RunnerState {
  phase: Phase;
  taskIdx: number;
  itemIdx: number;
  attempt: number;
}

export type Action =
  | { type: 'BEGIN' }
  | { type: 'RESUME'; state: RunnerState }
  | { type: 'START_TASK' }
  | { type: 'STIMULUS_DONE' }
  | { type: 'PREP_DONE' }
  | { type: 'PROMPT_DONE' }
  | { type: 'RESPONSE_DONE' }
  | { type: 'ACCEPT' }
  | { type: 'RERECORD' };

export const AUDIO_TASKS = new Set(['silence', 'read_aloud', 'sentence_repeat', 'quick_answer', 'phone_call', 'describe_opinion']);

export const initialState: RunnerState = { phase: 'intro', taskIdx: 0, itemIdx: 0, attempt: 1 };

export function taskKind(task: Task): 'audio' | 'typed' {
  return AUDIO_TASKS.has(task.type) ? 'audio' : 'typed';
}

export function effectiveTiming(task: Task, item: Item): Timing {
  return item.timing ?? task.timing;
}

/** Review (accept / re-record) exists only for audio tasks that allow re-recording. */
export function hasReview(task: Task): boolean {
  return taskKind(task) === 'audio' && task.allow_rerecord;
}

function enterItem(task: Task, s: RunnerState): RunnerState {
  const item = task.items[s.itemIdx];
  const t = effectiveTiming(task, item);
  if (t.prep_s > 0) return { ...s, phase: 'prep' };
  return { ...s, phase: item.audio ? 'prompt' : 'respond' };
}

function nextItem(form: Form, s: RunnerState): RunnerState {
  const task = form.tasks[s.taskIdx];
  if (s.itemIdx + 1 < task.items.length) {
    return enterItem(task, { ...s, itemIdx: s.itemIdx + 1, attempt: 1 });
  }
  if (s.taskIdx + 1 < form.tasks.length) {
    return { phase: 'task_intro', taskIdx: s.taskIdx + 1, itemIdx: 0, attempt: 1 };
  }
  return { ...s, phase: 'done' };
}

export function reduce(form: Form, s: RunnerState, a: Action): RunnerState {
  const task = form.tasks[s.taskIdx];
  const item = task?.items[s.itemIdx];
  switch (a.type) {
    case 'RESUME':
      if (s.phase !== 'intro') return s;
      return a.state;
    case 'BEGIN':
      if (s.phase !== 'intro') return s;
      return form.tasks.length ? { ...s, phase: 'task_intro' } : { ...s, phase: 'done' };
    case 'START_TASK':
      if (s.phase !== 'task_intro') return s;
      // A task-level stimulus (clip) plays once before the first item.
      return task.audio ? { ...s, phase: 'stimulus' } : enterItem(task, s);
    case 'STIMULUS_DONE':
      if (s.phase !== 'stimulus') return s;
      return enterItem(task, s);
    case 'PREP_DONE':
      if (s.phase !== 'prep') return s;
      return { ...s, phase: item?.audio ? 'prompt' : 'respond' };
    case 'PROMPT_DONE':
      if (s.phase !== 'prompt') return s;
      return { ...s, phase: 'respond' };
    case 'RESPONSE_DONE':
      if (s.phase !== 'respond') return s;
      return hasReview(task) ? { ...s, phase: 'review' } : nextItem(form, s);
    case 'ACCEPT':
      if (s.phase !== 'review') return s;
      return nextItem(form, s);
    case 'RERECORD':
      if (s.phase !== 'review' || !task.allow_rerecord) return s;
      return enterItem(task, { ...s, attempt: s.attempt + 1 });
    default:
      return s;
  }
}

/** Total number of items, for progress display. */
export function countItems(form: Form): number {
  return form.tasks.reduce((n, t) => n + t.items.length, 0);
}

/** Items before the current one, for the progress bar. */
export function itemsBefore(form: Form, s: RunnerState): number {
  return form.tasks.slice(0, s.taskIdx).reduce((n, t) => n + t.items.length, 0) + s.itemIdx;
}

/** Deterministic option order per (session, item) so the correct answer's position never leaks
 *  from the YAML and never changes on reload. Returns original indices in display order. */
export function shuffledOrder(n: number, seed: string): number[] {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  const order = Array.from({ length: n }, (_, i) => i);
  for (let i = n - 1; i > 0; i--) {
    h = (Math.imul(h, 1664525) + 1013904223) >>> 0;
    const j = h % (i + 1);
    [order[i], order[j]] = [order[j], order[i]];
  }
  return order;
}

/** Keyboard shortcuts for the one-tap answer tasks. Returns the stored value and the event name
 *  the pipeline expects (`submit` for choices, `answer` for timed yes/no and AXB), or null. */
export function keyAnswer(task: Task, key: string, order: number[]): { value: string; event: 'submit' | 'answer' } | null {
  const k = key.length === 1 ? key.toLowerCase() : key;
  switch (task.type) {
    case 'multiple_choice': {
      if (!/^[1-9]$/.test(k)) return null;
      const pos = Number(k) - 1;
      return pos < order.length ? { value: String(order[pos]), event: 'submit' } : null;
    }
    case 'axb':
      if (k === 'f' || k === 'a' || k === 'ArrowLeft') return { value: 'A', event: 'answer' };
      if (k === 'j' || k === 'b' || k === 'ArrowRight') return { value: 'B', event: 'answer' };
      return null;
    case 'lexical_decision':
      if (k === 'f' || k === 'ArrowLeft') return { value: 'no', event: 'answer' };
      if (k === 'j' || k === 'ArrowRight') return { value: 'yes', event: 'answer' };
      return null;
    default:
      return null;
  }
}

export interface CtestSegment { text: string; blank: boolean; len?: number }

/** C-test: split "wo{rry} about" into segments the UI renders as text + inputs. */
export function ctestSegments(text: string): CtestSegment[] {
  const out: CtestSegment[] = [];
  const re = /\{([^{}]+)\}/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), blank: false });
    out.push({ text: '', blank: true, len: m[1].length });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), blank: false });
  return out;
}

// --- resuming an unfinished sitting -------------------------------------------------------
// The position is kept in localStorage per session: the server only learns that an audio take is
// complete once its upload finishes, which can lag the sitting by minutes.

export interface Progress { taskIdx: number; itemIdx: number }

const progressKey = (sessionId: string) => `ehnglish.progress.${sessionId}`;

export function loadProgress(sessionId: string): Progress | null {
  try {
    const raw = localStorage.getItem(progressKey(sessionId));
    const p = raw ? (JSON.parse(raw) as Progress) : null;
    return p && (p.taskIdx > 0 || p.itemIdx > 0) ? p : null;
  } catch {
    return null;
  }
}

export function saveProgress(sessionId: string, s: RunnerState | null): void {
  try {
    if (s) localStorage.setItem(progressKey(sessionId), JSON.stringify({ taskIdx: s.taskIdx, itemIdx: s.itemIdx }));
    else localStorage.removeItem(progressKey(sessionId));
  } catch {
    /* storage unavailable: the sitting simply restarts at the top */
  }
}

/** State to start from when a sitting is resumed: the saved item itself (its take will be a new
 *  attempt), via the task intro when it is the first item of a task. */
export function resumeState(form: Form, p: Progress): RunnerState {
  const taskIdx = Math.min(p.taskIdx, form.tasks.length - 1);
  const task = form.tasks[taskIdx];
  const itemIdx = Math.min(p.itemIdx, task.items.length - 1);
  if (itemIdx === 0) return { phase: 'task_intro', taskIdx, itemIdx: 0, attempt: 1 };
  return enterItem(task, { phase: 'intro', taskIdx, itemIdx, attempt: 1 });
}
