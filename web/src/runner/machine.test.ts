import { describe, expect, it } from 'vitest';
import type { Form } from '../types';
import { countItems, effectiveTiming, hasReview, initialState, reduce, taskKind, type RunnerState } from './machine';

const form: Form = {
  id: 'f', version: 1, kind: 'dummy', title: { en: 'F', ko: 'F' },
  tasks: [
    { id: 'A', type: 'read_aloud', title: { en: 'a', ko: 'a' }, instructions: { en: '', ko: '' }, timing: { prep_s: 2, respond_s: 4, max_s: 6 }, allow_rerecord: true,
      items: [{ id: 'A1', text: 'x', target: {} }, { id: 'A2', text: 'y', target: {} }] },
    { id: 'R', type: 'sentence_repeat', title: { en: 'r', ko: 'r' }, instructions: { en: '', ko: '' }, timing: { prep_s: 0, respond_s: 8, max_s: 10 }, allow_rerecord: false, tone_hz: 880,
      items: [{ id: 'R1', text: 's', audio: 'audio/x/R1.wav', target: {} }] },
    { id: 'D', type: 'describe_opinion', title: { en: 'd', ko: 'd' }, instructions: { en: '', ko: '' }, timing: { prep_s: 10, respond_s: 90, max_s: 95 }, allow_rerecord: false,
      items: [{ id: 'D1', prompt: { en: 'p', ko: 'p' }, target: {} }, { id: 'D2', prompt: { en: 'q', ko: 'q' }, timing: { prep_s: 30, respond_s: 90, max_s: 95 }, target: {} }] },
    { id: 'B', type: 'typed_response', title: { en: 'b', ko: 'b' }, instructions: { en: '', ko: '' }, timing: { prep_s: 0, respond_s: 60, max_s: 60 }, allow_rerecord: false,
      items: [{ id: 'B1', prompt: { en: 'p', ko: 'p' }, target: {} }] },
  ],
};

const run = (s: RunnerState, ...types: Parameters<typeof reduce>[2]['type'][]) => types.reduce((st, type) => reduce(form, st, { type }), s);

describe('runner machine', () => {
  it('walks the whole form', () => {
    let s = run(initialState, 'BEGIN');
    expect(s.phase).toBe('task_intro');
    s = run(s, 'START_TASK');
    expect(s.phase).toBe('prep');
    s = run(s, 'PREP_DONE', 'RESPONSE_DONE');
    expect(s.phase).toBe('review');
    s = run(s, 'ACCEPT');
    expect(s).toMatchObject({ phase: 'prep', taskIdx: 0, itemIdx: 1, attempt: 1 });
    s = run(s, 'PREP_DONE', 'RESPONSE_DONE', 'ACCEPT');
    expect(s).toMatchObject({ phase: 'task_intro', taskIdx: 1, itemIdx: 0 });
    // sentence repeat: no prep, audio prompt, no review
    s = run(s, 'START_TASK');
    expect(s.phase).toBe('prompt');
    s = run(s, 'PROMPT_DONE');
    expect(s.phase).toBe('respond');
    s = run(s, 'RESPONSE_DONE');
    expect(s).toMatchObject({ phase: 'task_intro', taskIdx: 2 });
    // describe/opinion: prep then respond, no review, per-item timing
    s = run(s, 'START_TASK');
    expect(s.phase).toBe('prep');
    s = run(s, 'PREP_DONE', 'RESPONSE_DONE');
    expect(s).toMatchObject({ phase: 'prep', taskIdx: 2, itemIdx: 1 });
    expect(effectiveTiming(form.tasks[2], form.tasks[2].items[1]).prep_s).toBe(30);
    expect(effectiveTiming(form.tasks[2], form.tasks[2].items[0]).prep_s).toBe(10);
    s = run(s, 'PREP_DONE', 'RESPONSE_DONE');
    expect(s).toMatchObject({ phase: 'task_intro', taskIdx: 3 });
    s = run(s, 'START_TASK');
    expect(s.phase).toBe('respond'); // typed: straight in
    s = run(s, 'RESPONSE_DONE');
    expect(s.phase).toBe('done');
  });

  it('re-record bumps the attempt and repeats the same item', () => {
    let s = run(initialState, 'BEGIN', 'START_TASK', 'PREP_DONE', 'RESPONSE_DONE');
    s = run(s, 'RERECORD');
    expect(s).toMatchObject({ phase: 'prep', itemIdx: 0, attempt: 2 });
    s = run(s, 'PREP_DONE', 'RESPONSE_DONE', 'ACCEPT');
    expect(s).toMatchObject({ itemIdx: 1, attempt: 1 });
  });

  it('ignores out-of-phase actions', () => {
    const s = run(initialState, 'ACCEPT', 'PREP_DONE', 'PROMPT_DONE', 'RESPONSE_DONE');
    expect(s).toEqual(initialState);
  });

  it('kinds and review', () => {
    expect(taskKind(form.tasks[1])).toBe('audio');
    expect(taskKind(form.tasks[3])).toBe('typed');
    expect(hasReview(form.tasks[0])).toBe(true);
    expect(hasReview(form.tasks[1])).toBe(false);
    expect(countItems(form)).toBe(6);
  });
});
