import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { analyzeTake, type QualityReport } from '../audio/quality';
import { getRecorder, type PcmRecorder } from '../audio/recorder';
import { encodeWav } from '../audio/wav';
import { KeystrokeLogger } from '../keystrokes';
import { loadSetup } from '../setup/store';
import type { EventIn, Form, SessionOut } from '../types';
import { enqueueUpload, processQueue } from '../upload/queue';
import { sha256Hex } from '../upload/sha256';
import { useLang } from '../useLang';
import { countItems, ctestSegments, effectiveTiming, hasReview, initialState, reduce, shuffledOrder, taskKind, type RunnerState } from './machine';
import { useCountdown } from './useCountdown';

interface Props { form: Form; session: SessionOut; onFinished: () => void }

interface LastTake { takeId: string; pcm: Int16Array; quality: QualityReport }

const TONE_MS = 150;

export default function TaskRunner({ form, session, onFinished }: Props) {
  const { t } = useTranslation();
  const lang = useLang();
  const [state, dispatch] = useReducer((s: RunnerState, a: Parameters<typeof reduce>[2]) => reduce(form, s, a), initialState);
  const [rec, setRec] = useState<PcmRecorder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<LastTake | null>(null);
  const [busy, setBusy] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [blanks, setBlanks] = useState<string[]>([]);
  const takeIdRef = useRef<string | null>(null);
  const eventsRef = useRef<EventIn[]>([]);
  const keysRef = useRef(new KeystrokeLogger());
  const textRef = useRef<HTMLTextAreaElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const setup = useMemo(() => loadSetup(), []);

  const task = form.tasks[state.taskIdx];
  const item = task?.items[state.itemIdx];
  const timing = task && item ? effectiveTiming(task, item) : null;
  const kind = task ? taskKind(task) : 'audio';
  const total = countItems(form);
  const doneItems = form.tasks.slice(0, state.taskIdx).reduce((n, tk) => n + tk.items.length, 0) + state.itemIdx;

  const mark = useCallback((name: string, meta?: Record<string, unknown>) => {
    eventsRef.current.push({ name, t_client_ms: performance.now(), meta });
  }, []);
  const fail = (e: unknown) => setError(String((e as Error).message ?? e));

  // Create the take row when an item starts (first active phase of each attempt).
  useEffect(() => {
    if (!task || !item) return;
    if (!['prep', 'prompt', 'respond'].includes(state.phase)) return;
    if (takeIdRef.current) return;
    // Reset the timeline synchronously: later effects in this same render (prompt playback) mark events.
    eventsRef.current = [];
    mark('item_shown', { phase: state.phase });
    const body = kind === 'audio'
      ? { task_id: task.id, item_id: item.id, attempt: state.attempt, kind: 'audio' as const, sample_rate: rec?.info.sampleRate ?? setup.sampleRate, channels: 1 }
      : { task_id: task.id, item_id: item.id, attempt: state.attempt, kind: 'typed' as const };
    api.createTake(session.id, body).then((tk) => { takeIdRef.current = tk.id; }).catch(fail);
  }, [state.phase, state.taskIdx, state.itemIdx, state.attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  async function waitForTakeId(): Promise<string> {
    for (let i = 0; i < 100 && !takeIdRef.current; i++) await new Promise((r) => setTimeout(r, 100));
    if (!takeIdRef.current) throw new Error('take was not created');
    return takeIdRef.current;
  }

  async function begin() {
    try {
      const r = await getRecorder(setup.deviceId || undefined);
      setRec(r);
      dispatch({ type: 'BEGIN' });
    } catch (e) {
      fail(e);
    }
  }

  // --- audio prompt phase: play the item audio, then a beep, then open the mic ------------
  useEffect(() => {
    if (state.phase !== 'prompt' || !item?.audio) return;
    if (kind === 'audio' && !rec) return;
    let cancelled = false;
    const el = new Audio(`/api/forms/${encodeURIComponent(form.id)}/audio/${item.audio}`);
    audioRef.current = el;
    el.onended = async () => {
      if (cancelled) return;
      mark('prompt_end');
      if (task.tone_hz && rec) {
        const osc = rec.ctx.createOscillator();
        const g = rec.ctx.createGain();
        osc.frequency.value = task.tone_hz;
        g.gain.value = 0.2;
        osc.connect(g).connect(rec.ctx.destination);
        osc.start();
        await new Promise((r) => setTimeout(r, TONE_MS));
        osc.stop();
        osc.disconnect();
        mark('tone_end');
      }
      if (!cancelled) dispatch({ type: 'PROMPT_DONE' });
    };
    el.onerror = () => fail(new Error(`prompt audio failed: ${item.audio}`));
    mark('prompt_start');
    el.play().catch(fail);
    return () => { cancelled = true; el.pause(); audioRef.current = null; };
  }, [state.phase, state.itemIdx, state.taskIdx, state.attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- recording phase ------------------------------------------------------------------
  const commitTake = useCallback(async (take: LastTake) => {
    if (!rec) return;
    mark('accepted');
    const wav = encodeWav(take.pcm, rec.info.sampleRate, 1);
    const sha = await sha256Hex(wav);
    await enqueueUpload(take.takeId, session.id, wav, sha, take.quality);
    await api.postEvents(take.takeId, eventsRef.current).catch(() => undefined);
    void processQueue(api);
    takeIdRef.current = null;
  }, [rec, session.id, mark]);

  useEffect(() => {
    if (state.phase !== 'respond' || kind !== 'audio' || !rec || !timing) return;
    let cancelled = false;
    (async () => {
      if (!item?.audio) mark('prompt_end'); // no audio prompt: the response window opens now
      mark('record_start');
      await rec.start();
      await new Promise((r) => setTimeout(r, timing.respond_s * 1000));
      if (cancelled) return;
      const pcm = await rec.stop();
      mark('record_stop');
      const quality = analyzeTake(pcm, rec.info.sampleRate, setup.noise_floor?.rms_dbfs ?? null);
      const takeId = await waitForTakeId();
      const takeRec = { takeId, pcm, quality };
      if (hasReview(task)) {
        setLast(takeRec);
        dispatch({ type: 'RESPONSE_DONE' });
      } else {
        await commitTake(takeRec);
        dispatch({ type: 'RESPONSE_DONE' });
      }
    })().catch(fail);
    return () => { cancelled = true; };
  }, [state.phase, state.attempt, state.itemIdx, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  async function accept() {
    if (!last) return;
    setBusy(true);
    try {
      await commitTake(last);
      setLast(null);
      dispatch({ type: 'ACCEPT' });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function rerecord() {
    if (!last) return;
    mark('rerecord');
    await api.postEvents(last.takeId, eventsRef.current).catch(() => undefined);
    takeIdRef.current = null;
    setLast(null);
    dispatch({ type: 'RERECORD' });
  }

  // --- typed item -----------------------------------------------------------------------
  useEffect(() => {
    if (state.phase === 'respond' && kind === 'typed') {
      if (textRef.current) {
        keysRef.current.attach(textRef.current);
        textRef.current.focus();
      }
      if (!item?.audio) mark('prompt_end'); // audio prompts already marked it when playback ended
      setRating(item?.scale ? Math.round((item.scale.min + item.scale.max) / 2) : null);
      setBlanks(item?.text && task?.type === 'c_test' ? ctestSegments(item.text).filter((x) => x.blank).map(() => '') : []);
    }
    return () => keysRef.current.detach();
  }, [state.phase, state.itemIdx, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submitChoice(value: string, eventName = 'answer') {
    if (busy) return;
    setBusy(true);
    try {
      const takeId = await waitForTakeId();
      mark(eventName, { value });
      await api.submitTyped(takeId, value, []);
      await api.postEvents(takeId, eventsRef.current).catch(() => undefined);
      takeIdRef.current = null;
      dispatch({ type: 'RESPONSE_DONE' });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  const order = useMemo(
    () => (item?.options ? shuffledOrder(item.options.length, `${session.id}:${item.id}`) : []),
    [item?.id, item?.options, session.id],
  );

  useEffect(() => {
    if (state.phase !== 'respond' || !task) return;
    const onKey = (e: KeyboardEvent) => {
      if (task.type === 'multiple_choice' && /^[1-9]$/.test(e.key)) {
        const pos = Number(e.key) - 1;
        if (pos < order.length) void submitChoice(String(order[pos]), 'submit');
      }
      if (task.type === 'axb') {
        if (e.key === 'f' || e.key === 'F' || e.key === 'a' || e.key === 'A' || e.key === 'ArrowLeft') void submitChoice('A');
        if (e.key === 'j' || e.key === 'J' || e.key === 'b' || e.key === 'B' || e.key === 'ArrowRight') void submitChoice('B');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state.phase, state.itemIdx, busy, order]); // eslint-disable-line react-hooks/exhaustive-deps

  // Task-level stimulus (conversation / lecture / sermon clip): play once, then the items.
  useEffect(() => {
    if (state.phase !== 'stimulus' || !task?.audio) return;
    let cancelled = false;
    const el = new Audio(`/api/forms/${encodeURIComponent(form.id)}/audio/${task.audio}`);
    el.onended = () => { if (!cancelled) { mark('stimulus_end'); dispatch({ type: 'STIMULUS_DONE' }); } };
    el.onerror = () => fail(new Error(`stimulus audio failed: ${task.audio}`));
    el.play().catch(fail);
    return () => { cancelled = true; el.pause(); };
  }, [state.phase, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  async function answerLexical(answer: 'yes' | 'no') {
    if (busy) return;
    setBusy(true);
    try {
      const takeId = await waitForTakeId();
      mark('answer', { answer });
      await api.submitTyped(takeId, answer, []);
      await api.postEvents(takeId, eventsRef.current).catch(() => undefined);
      takeIdRef.current = null;
      dispatch({ type: 'RESPONSE_DONE' });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (state.phase !== 'respond' || task?.type !== 'lexical_decision') return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'f' || e.key === 'F' || e.key === 'ArrowLeft') void answerLexical('no');
      if (e.key === 'j' || e.key === 'J' || e.key === 'ArrowRight') void answerLexical('yes');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [state.phase, state.itemIdx, busy]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submitTyped() {
    const el = textRef.current;
    const value = task?.type === 'c_test' ? blanks.join('\u241f') : el ? el.value : rating !== null ? String(rating) : null;
    if (value === null) return;
    setBusy(true);
    try {
      const takeId = await waitForTakeId();
      mark('submit');
      await api.submitTyped(takeId, value, keysRef.current.events);
      await api.postEvents(takeId, eventsRef.current).catch(() => undefined);
      keysRef.current = new KeystrokeLogger();
      takeIdRef.current = null;
      dispatch({ type: 'RESPONSE_DONE' });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  const typedDeadline = useCallback(() => { void submitTyped(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // --- finish ---------------------------------------------------------------------------
  useEffect(() => {
    if (state.phase === 'done') {
      api.patchSession(session.id, { status: 'done' }).catch(() => undefined).finally(onFinished);
    }
  }, [state.phase]); // eslint-disable-line react-hooks/exhaustive-deps

  const prepLeft = useCountdown(timing?.prep_s ?? 0, state.phase === 'prep', () => dispatch({ type: 'PREP_DONE' }));
  const respondLeft = useCountdown(timing?.respond_s ?? 0, state.phase === 'respond' && kind === 'audio', () => undefined);
  const typedLeft = useCountdown(timing?.respond_s ?? 0, state.phase === 'respond' && kind === 'typed', typedDeadline);

  if (error) return <div className="card status-bad">{t('common.error')}: {error}</div>;

  if (state.phase === 'intro') {
    return (
      <div className="card stack">
        <h2>{form.title[lang]}</h2>
        <p>{t('runner.intro_body', { tasks: form.tasks.length })}</p>
        <button className="primary" onClick={begin} data-testid="begin">{t('runner.begin')}</button>
      </div>
    );
  }
  if (state.phase === 'done' || !task || !item || !timing) return <div className="card">{t('common.loading')}</div>;

  const showText = task.type === 'read_aloud';
  const showPrompt = task.type === 'describe_opinion' || task.type === 'phone_call';
  const scenario = task.type === 'phone_call' ? (task.target?.scenario as string | undefined) : undefined;
  const active = state.phase === 'prep' || state.phase === 'prompt' || state.phase === 'respond';

  return (
    <div className="stack">
      <div className="progress"><div style={{ width: `${(doneItems / total) * 100}%` }} /></div>
      <div className="muted">{t('runner.task_of', { n: state.taskIdx + 1, total: form.tasks.length })} · {t('runner.item_of', { n: state.itemIdx + 1, total: task.items.length })}{state.attempt > 1 && <> · {t('runner.attempt', { n: state.attempt })}</>}</div>

      {state.phase === 'task_intro' && (
        <div className="card stack">
          <h2>{task.title[lang]}</h2>
          <p>{task.instructions[lang]}</p>
          <button className="primary" onClick={() => dispatch({ type: 'START_TASK' })} data-testid="start-task">{t('runner.start_task')}</button>
        </div>
      )}

      {kind === 'audio' && active && (
        <div className="card stack">
          {scenario && <div className="muted" data-testid="scenario">{t('runner.scenario')}: {scenario}</div>}
          {showText && <><div className="muted">{t('runner.read_this')}</div><p className="big" data-testid="item-text">{item.text}</p></>}
          {showPrompt && <p className="big" data-testid="item-prompt">{item.prompt?.[lang]}</p>}
          {item.image && <img src={`/api/forms/${encodeURIComponent(form.id)}/audio/${item.image}`} alt="" style={{ maxWidth: '100%' }} />}
          {task.type === 'silence' && <p className="big">{t('runner.stay_silent')}</p>}
          {state.phase === 'prep' && (
            <div className="countdown" data-testid="prep">{task.type === 'describe_opinion' ? t('runner.think') : t('runner.get_ready')} · {prepLeft}</div>
          )}
          {state.phase === 'prompt' && <div className="countdown" data-testid="listening">🎧 {t('runner.listen')}</div>}
          {state.phase === 'respond' && (
            <div className="countdown status-bad" data-testid="recording"><span className="rec-dot" />{task.type === 'silence' ? t('runner.recording') : task.type === 'phone_call' ? t('runner.your_turn') : t('runner.speak_now')} · {respondLeft}</div>
          )}
        </div>
      )}

      {kind === 'audio' && state.phase === 'review' && last && (
        <div className="card stack" data-testid="review">
          <h3>{t('runner.review_title')}</h3>
          <div>{t('runner.duration', { s: last.quality.duration_s })}</div>
          <div className={last.quality.ok ? 'status-ok' : 'status-warn'}>{last.quality.ok ? t('runner.quality_ok') : t('runner.quality_issue')}</div>
          {last.quality.flags.length > 0 && task.type !== 'silence' && <ul className="flags">{last.quality.flags.map((f) => <li key={f}>{t(`quality.${f}`)}</li>)}</ul>}
          <table className="stats"><tbody>
            <tr><td>{t('quality.peak')}</td><td>{last.quality.peak_dbfs ?? '—'} dBFS</td></tr>
            <tr><td>{t('quality.rms')}</td><td>{last.quality.rms_dbfs ?? '—'} dBFS</td></tr>
            <tr><td>{t('quality.noise')}</td><td>{last.quality.noise_floor_dbfs ?? '—'} dBFS</td></tr>
            <tr><td>{t('quality.snr')}</td><td>{last.quality.snr_db ?? '—'} dB</td></tr>
          </tbody></table>
          <div className="row">
            <button className="primary" onClick={accept} disabled={busy} data-testid="accept">{t('runner.accept')}</button>
            {task.allow_rerecord && <button onClick={rerecord} disabled={busy} data-testid="rerecord">{t('runner.rerecord')}</button>}
          </div>
        </div>
      )}

      {state.phase === 'stimulus' && (
        <div className="card stack"><div className="countdown" data-testid="stimulus">🎧 {t('runner.listen')}</div><p className="muted">{t('runner.listen_once')}</p></div>
      )}

      {kind === 'typed' && state.phase === 'prompt' && (
        <div className="card stack"><div className="countdown" data-testid="listening">🎧 {t('runner.listen')}</div></div>
      )}

      {kind === 'typed' && state.phase === 'respond' && task.type === 'multiple_choice' && item.options && (
        <div className="card stack">
          {task.text && <p data-testid="task-text" style={{ whiteSpace: 'pre-wrap' }}>{task.text}</p>}
          <p className="big" data-testid="item-text" dangerouslySetInnerHTML={{ __html: item.text ?? '' }} />
          <div className="muted">{t('runner.choose')}</div>
          <div className="stack">
            {order.map((orig, pos) => (
              <button key={orig} onClick={() => submitChoice(String(orig), 'submit')} disabled={busy} data-testid={`option-${orig}`} style={{ textAlign: 'left' }}>
                <strong>{pos + 1}.</strong> {item.options![orig]}
              </button>
            ))}
          </div>
        </div>
      )}

      {kind === 'typed' && state.phase === 'respond' && task.type === 'reading_passage' && (
        <div className="card stack">
          <p data-testid="passage" style={{ whiteSpace: 'pre-wrap', fontSize: '1.1rem', lineHeight: 1.7 }}>{item.text}</p>
          <button className="primary" onClick={() => submitChoice('', 'submit')} disabled={busy} data-testid="done-reading">{t('runner.done_reading')}</button>
        </div>
      )}

      {kind === 'typed' && state.phase === 'respond' && task.type === 'c_test' && (
        <div className="card stack">
          <div className="muted">{t('runner.fill_blanks')} · {t('common.seconds', { n: typedLeft })}</div>
          <p data-testid="ctest" style={{ fontSize: '1.15rem', lineHeight: 2.2 }}>
            {(() => { let bi = -1; return ctestSegments(item.text ?? '').map((seg, i) => seg.blank
              ? (() => { const idx = ++bi; return <input key={i} type="text" value={blanks[idx] ?? ''} size={Math.max(2, seg.len ?? 3)} autoComplete="off" spellCheck={false} data-testid={`blank-${idx}`} style={{ font: 'inherit', padding: '2px 4px', margin: '0 2px', borderBottom: '2px solid var(--accent)', borderTop: 'none', borderLeft: 'none', borderRight: 'none', background: 'transparent', color: 'inherit' }} onChange={(e) => setBlanks((b) => { const n = [...b]; n[idx] = e.target.value; return n; })} />; })()
              : <span key={i}>{seg.text}</span>); })()}
          </p>
          <button className="primary" onClick={submitTyped} disabled={busy} data-testid="done-typing">{t('runner.done_typing')}</button>
        </div>
      )}

      {kind === 'typed' && state.phase === 'respond' && task.type === 'axb' && (
        <div className="card stack" style={{ textAlign: 'center' }}>
          <p className="big" data-testid="axb-question">{t('runner.axb_question')}</p>
          <div className="row" style={{ justifyContent: 'center', gap: 32 }}>
            <button onClick={() => submitChoice('A')} disabled={busy} data-testid="axb-a" style={{ minWidth: 140, fontSize: '1.4rem' }}>{t('runner.a')} <span className="muted">(F)</span></button>
            <button onClick={() => submitChoice('B')} disabled={busy} data-testid="axb-b" style={{ minWidth: 140, fontSize: '1.4rem' }}>{t('runner.b')} <span className="muted">(J)</span></button>
          </div>
        </div>
      )}

      {kind === 'typed' && state.phase === 'respond' && task.type === 'rating' && item.scale && (
        <div className="card stack">
          <p className="big" data-testid="item-prompt">{item.prompt?.[lang]}</p>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="muted">{item.scale.labels[String(item.scale.min)]?.[lang] ?? item.scale.min}</span>
            <strong data-testid="rating-value">{rating}</strong>
            <span className="muted">{item.scale.labels[String(item.scale.max)]?.[lang] ?? item.scale.max}</span>
          </div>
          <input type="range" min={item.scale.min} max={item.scale.max} step={1} value={rating ?? item.scale.min} onChange={(e) => setRating(Number(e.target.value))} data-testid="rating-input" />
          <button className="primary" onClick={submitTyped} disabled={busy} data-testid="done-typing">{t('runner.next')}</button>
        </div>
      )}

      {kind === 'typed' && state.phase === 'respond' && task.type === 'lexical_decision' && (
        <div className="card stack" style={{ textAlign: 'center' }}>
          <div className="muted">{t('runner.is_word')}{item.target?.practice ? ` · ${t('runner.practice')}` : ''}</div>
          <p className="countdown" data-testid="lexical-item" style={{ fontSize: '2.6rem', letterSpacing: '0.04em' }}>{item.text}</p>
          <div className="row" style={{ justifyContent: 'center', gap: 32 }}>
            <button onClick={() => answerLexical('no')} disabled={busy} data-testid="lexical-no" style={{ minWidth: 140, fontSize: '1.3rem' }}>{t('runner.no')} <span className="muted">(F)</span></button>
            <button className="primary" onClick={() => answerLexical('yes')} disabled={busy} data-testid="lexical-yes" style={{ minWidth: 140, fontSize: '1.3rem' }}>{t('runner.yes')} <span style={{ opacity: 0.7 }}>(J)</span></button>
          </div>
        </div>
      )}

      {kind === 'typed' && state.phase === 'respond' && !['rating', 'lexical_decision', 'multiple_choice', 'reading_passage', 'c_test', 'axb'].includes(task.type) && (
        <div className="card stack">
          {task.type === 'copy_typing' && <><div className="muted">{t('runner.copy_this')}</div><p className="big" data-testid="copy-text" style={{ userSelect: 'none' }}>{item.text}</p></>}
          {item.prompt && <p className="big" data-testid="item-prompt">{item.prompt[lang]}</p>}
          {task.type === 'dictation' && <p className="big" data-testid="item-prompt">{t('runner.type_what_you_heard')}</p>}
          <div className="muted">{t('common.seconds', { n: typedLeft })}</div>
          <textarea ref={textRef} placeholder={t('runner.type_here')} data-testid="typed-input" spellCheck={false} autoCorrect="off" autoComplete="off" lang={item.target?.language === 'ko' ? 'ko' : 'en'} onPaste={(e) => e.preventDefault()} />
          <button className="primary" onClick={submitTyped} disabled={busy} data-testid="done-typing">{t('runner.done_typing')}</button>
        </div>
      )}
    </div>
  );
}
