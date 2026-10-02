/** Pure state machine for the timed task runner. Driven entirely by the form definition. */
import type { Form, Item, Task, Timing } from '../types';

export type Phase = 'intro' | 'task_intro' | 'prep' | 'prompt' | 'respond' | 'review' | 'done';

export interface RunnerState {
  phase: Phase;
  taskIdx: number;
  itemIdx: number;
  attempt: number;
}

export type Action =
  | { type: 'BEGIN' }
  | { type: 'START_TASK' }
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

export function currentTask(form: Form, s: RunnerState): Task | undefined {
  return form.tasks[s.taskIdx];
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
    case 'BEGIN':
      if (s.phase !== 'intro') return s;
      return form.tasks.length ? { ...s, phase: 'task_intro' } : { ...s, phase: 'done' };
    case 'START_TASK':
      if (s.phase !== 'task_intro') return s;
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
