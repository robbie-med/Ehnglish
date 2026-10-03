import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { analyzeTake, type QualityReport } from '../audio/quality';
import { getRecorder, type PcmRecorder } from '../audio/recorder';
import { encodeWav } from '../audio/wav';
import { loadSetup } from '../setup/store';
import type { EventIn, Form, SessionOut, TakeOut } from '../types';
import { enqueueUpload, processQueue } from '../upload/queue';
import { sha256Hex } from '../upload/sha256';
import { useLang } from '../useLang';
import { countItems, effectiveTiming, hasReview, initialState, itemsBefore, loadProgress, reduce, resumeState, saveProgress, taskKind, type RunnerState } from './machine';
import TypedItem, { type TypedAnswer } from './TypedItem';
import { useTimer } from './useTimer';

interface Props { form: Form; session: SessionOut; onFinished: () => void }

interface LastTake { takeId: string; pcm: Int16Array; quality: QualityReport }

const TONE_MS = 150;
const MIN_TAKE_MS = 1000; // "I'm done" is ignored in the first second
const EARLY_STOP_FROM_S = 15; // and only offered on the longer windows

const audioUrl = (formId: string, path: string) => `/api/forms/${encodeURIComponent(formId)}/audio/${path}`;

/**
 * Runs one sitting: the machine in ./machine.ts decides the phase, this component performs it
 * (plays prompts, records, uploads, submits typed answers) and logs the client timeline.
 */
export default function TaskRunner({ form, session, onFinished }: Props) {
  const { t } = useTranslation();
  const lang = useLang();
  const [state, dispatch] = useReducer((s: RunnerState, a: Parameters<typeof reduce>[2]) => reduce(form, s, a), initialState);
  const [rec, setRec] = useState<PcmRecorder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<LastTake | null>(null);
  const [busy, setBusy] = useState(false);
  const takeRef = useRef<Promise<TakeOut> | null>(null); // the take row of the current attempt
  const eventsRef = useRef<EventIn[]>([]);
  const stopEarlyRef = useRef<(() => void) | null>(null);
  const setup = useMemo(() => loadSetup(), []);
  const saved = useMemo(() => loadProgress(session.id), [session.id]);

  const task = form.tasks[state.taskIdx];
  const item = task?.items[state.itemIdx];
  const timing = task && item ? effectiveTiming(task, item) : null;
  const kind = task ? taskKind(task) : 'audio';
  const active = state.phase === 'prep' || state.phase === 'prompt' || state.phase === 'respond';

  const mark = useCallback((name: string, meta?: Record<string, unknown>) => {
    eventsRef.current.push({ name, t_client_ms: performance.now(), meta });
  }, []);
  const fail = useCallback((e: unknown) => {
    const msg = String((e as Error).message ?? e);
    setError(/not allowed|denied|NotAllowedError/i.test(msg) ? `${msg} — ${t('runner.mic_denied')}` : msg);
  }, [t]);

  // Remember where we are so a reload (or a new build) resumes at this item.
  useEffect(() => {
    if (state.phase === 'done') saveProgress(session.id, null);
    else if (state.phase !== 'intro') saveProgress(session.id, state);
  }, [state, session.id]);

  // One take row per attempt, created when the item becomes active. The timeline is reset here,
  // synchronously, because the prompt effect below (same render) marks its first event.
  useEffect(() => {
    if (!task || !item || !active || takeRef.current) return;
    eventsRef.current = [];
    mark('item_shown', { phase: state.phase });
    const body = { task_id: task.id, item_id: item.id, attempt: state.attempt, kind };
    takeRef.current = api.createTake(session.id, kind === 'audio' ? { ...body, sample_rate: rec?.info.sampleRate ?? setup.sampleRate, channels: 1 } : body);
    takeRef.current.catch(fail);
  }, [state.phase, state.taskIdx, state.itemIdx, state.attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  /** The current take's id; the row was requested when the item started. */
  const takeId = async () => {
    if (!takeRef.current) throw new Error('no take for this item');
    return (await takeRef.current).id;
  };

  async function begin() {
    try {
      setRec(await getRecorder(setup.deviceId || undefined));
      dispatch(saved ? { type: 'RESUME', state: resumeState(form, saved) } : { type: 'BEGIN' });
    } catch (e) {
      fail(e);
    }
  }

  // --- task-level stimulus (conversation / lecture / sermon clip): plays once ---------------
  useEffect(() => {
    if (state.phase !== 'stimulus' || !task?.audio) return;
    let cancelled = false;
    const el = new Audio(audioUrl(form.id, task.audio));
    el.onended = () => { if (!cancelled) { mark('stimulus_end'); dispatch({ type: 'STIMULUS_DONE' }); } };
    el.onerror = () => fail(new Error(`stimulus audio failed: ${task.audio}`));
    el.play().catch(fail);
    return () => { cancelled = true; el.pause(); };
  }, [state.phase, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- prompt: play the item audio, then (for repeat / quick-answer) a beep ------------------
  useEffect(() => {
    if (state.phase !== 'prompt' || !item?.audio) return;
    if (kind === 'audio' && !rec) return;
    let cancelled = false;
    const el = new Audio(audioUrl(form.id, item.audio));
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
    return () => { cancelled = true; el.pause(); };
  }, [state.phase, state.itemIdx, state.taskIdx, state.attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- recording ------------------------------------------------------------------------------
  useEffect(() => {
    if (state.phase !== 'respond' || kind !== 'audio' || !rec || !timing) return;
    let cancelled = false;
    (async () => {
      if (!item?.audio) mark('prompt_end'); // no audio prompt: the response window opens now
      mark('record_start');
      await rec.start();
      const t0 = performance.now();
      let early = false;
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, timing.respond_s * 1000);
        stopEarlyRef.current = () => {
          if (performance.now() - t0 < MIN_TAKE_MS) return;
          clearTimeout(timer);
          early = true;
          resolve();
        };
      });
      stopEarlyRef.current = null;
      if (cancelled) return;
      const pcm = await rec.stop();
      mark('record_stop', { early, recorded_ms: Math.round(performance.now() - t0) });
      const take = { takeId: await takeId(), pcm, quality: analyzeTake(pcm, rec.info.sampleRate, setup.noise_floor?.rms_dbfs ?? null) };
      if (hasReview(task)) setLast(take);
      else commitTake(take);
      dispatch({ type: 'RESPONSE_DONE' });
    })().catch(fail);
    return () => { cancelled = true; stopEarlyRef.current = null; };
  }, [state.phase, state.attempt, state.itemIdx, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Queue the WAV for upload and move on. Encoding, hashing and the IndexedDB write of a
   *  multi-megabyte take took seconds on Safari, and none of it has to finish before the next
   *  item, so the work runs in the background and only reports failures. */
  function commitTake(take: LastTake) {
    if (!rec) return;
    mark('accepted');
    const events = eventsRef.current;
    const sampleRate = rec.info.sampleRate;
    takeRef.current = null;
    void (async () => {
      const wav = encodeWav(take.pcm, sampleRate, 1);
      await enqueueUpload(take.takeId, session.id, wav, await sha256Hex(wav), take.quality);
      await api.postEvents(take.takeId, events).catch(() => undefined);
      void processQueue(api);
    })().catch(fail);
  }

  function accept() {
    if (!last) return;
    commitTake(last);
    setLast(null);
    dispatch({ type: 'ACCEPT' });
  }

  function rerecord() {
    if (!last) return;
    mark('rerecord');
    void api.postEvents(last.takeId, eventsRef.current).catch(() => undefined);
    takeRef.current = null;
    setLast(null);
    dispatch({ type: 'RERECORD' });
  }

  // --- typed answers ---------------------------------------------------------------------------
  const submitting = useRef(false);
  const submitTyped = useCallback(async (a: TypedAnswer) => {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    try {
      const id = await takeId();
      mark(a.event, a.event === 'answer' || a.value ? { value: a.value } : undefined);
      await api.submitTyped(id, a.value, a.keystrokes ?? []);
      await api.postEvents(id, eventsRef.current).catch(() => undefined);
      takeRef.current = null;
      dispatch({ type: 'RESPONSE_DONE' });
    } catch (e) {
      fail(e);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }, [fail, mark]);

  useEffect(() => {
    if (state.phase === 'respond' && kind === 'typed' && !item?.audio) mark('prompt_end'); // audio prompts marked it at playback end
  }, [state.phase, state.itemIdx, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- finish ----------------------------------------------------------------------------------
  useEffect(() => {
    if (state.phase === 'done') api.patchSession(session.id, { status: 'done' }).catch(() => undefined).finally(onFinished);
  }, [state.phase]); // eslint-disable-line react-hooks/exhaustive-deps

  const prep = useTimer(timing?.prep_s ?? 0, state.phase === 'prep', () => dispatch({ type: 'PREP_DONE' }));
  const recording = useTimer(timing?.respond_s ?? 0, state.phase === 'respond' && kind === 'audio');

  if (error) return <div className="card status-bad">{t('common.error')}: {error}</div>;

  if (state.phase === 'intro') {
    return (
      <div className="card stack">
        <h2>{form.title[lang]}</h2>
        <p>{t('runner.intro_body', { tasks: form.tasks.length })}</p>
        {saved && <p className="status-ok" data-testid="resume-note">{t('runner.resume_note', { task: saved.taskIdx + 1, item: saved.itemIdx + 1 })}</p>}
        <button className="primary" onClick={begin} data-testid="begin">{saved ? t('runner.resume') : t('runner.begin')}</button>
      </div>
    );
  }
  if (state.phase === 'done' || !task || !item || !timing) return <div className="card">{t('common.loading')}</div>;

  const scenario = task.type === 'phone_call' ? (task.target?.scenario as string | undefined) : undefined;
  const recordingLabel = task.type === 'silence' ? t('runner.recording') : task.type === 'phone_call' ? t('runner.your_turn') : t('runner.speak_now');

  return (
    <div className="stack">
      <div className="progress"><div style={{ width: `${(itemsBefore(form, state) / countItems(form)) * 100}%` }} /></div>
      <div className="muted">
        {t('runner.task_of', { n: state.taskIdx + 1, total: form.tasks.length })} · {t('runner.item_of', { n: state.itemIdx + 1, total: task.items.length })}
        {state.attempt > 1 && <> · {t('runner.attempt', { n: state.attempt })}</>}
      </div>

      {state.phase === 'task_intro' && (
        <div className="card stack">
          <h2>{task.title[lang]}</h2>
          <p>{task.instructions[lang]}</p>
          <button className="primary" onClick={() => dispatch({ type: 'START_TASK' })} data-testid="start-task">{t('runner.start_task')}</button>
        </div>
      )}

      {state.phase === 'stimulus' && (
        <div className="card stack"><div className="countdown" data-testid="stimulus">🎧 {t('runner.listen')}</div><p className="muted">{t('runner.listen_once')}</p></div>
      )}

      {kind === 'audio' && active && (
        <div className="card stack">
          {scenario && <div className="muted" data-testid="scenario">{t('runner.scenario')}: {scenario}</div>}
          {task.type === 'read_aloud' && <><div className="muted">{t('runner.read_this')}</div><p className="big" data-testid="item-text">{item.text}</p></>}
          {(task.type === 'describe_opinion' || task.type === 'phone_call') && <p className="big" data-testid="item-prompt">{item.prompt?.[lang]}</p>}
          {item.image && <img src={audioUrl(form.id, item.image)} alt="" style={{ maxWidth: '100%' }} />}
          {task.type === 'silence' && <p className="big">{t('runner.stay_silent')}</p>}
          {state.phase === 'prep' && <div className="countdown" data-testid="prep">{task.type === 'describe_opinion' ? t('runner.think') : t('runner.get_ready')} · {Math.ceil(prep.left)}</div>}
          {state.phase === 'prompt' && <div className="countdown" data-testid="listening">🎧 {t('runner.listen')}</div>}
          {state.phase === 'respond' && (
            <>
              <div className="countdown status-bad" data-testid="recording"><span className="rec-dot" />{recordingLabel} · {Math.ceil(recording.left)}</div>
              <div className="meter"><div style={{ width: `${recording.pct}%`, transition: 'width 100ms linear' }} /></div>
              {timing.respond_s >= EARLY_STOP_FROM_S && (
                <div className="row" style={{ justifyContent: 'center', marginTop: 8 }}>
                  <button className="primary choice" onClick={() => stopEarlyRef.current?.()} data-testid="stop-early">{t('runner.done_speaking')}</button>
                </div>
              )}
            </>
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
            <button className="primary" onClick={accept} data-testid="accept">{t('runner.accept')}</button>
            {task.allow_rerecord && <button onClick={rerecord} data-testid="rerecord">{t('runner.rerecord')}</button>}
          </div>
        </div>
      )}

      {kind === 'typed' && state.phase === 'prompt' && (
        <div className="card stack"><div className="countdown" data-testid="listening">🎧 {t('runner.listen')}</div></div>
      )}

      {kind === 'typed' && state.phase === 'respond' && (
        <TypedItem key={`${task.id}:${item.id}:${state.attempt}`} task={task} item={item} timing={timing} lang={lang} sessionId={session.id} busy={busy} onSubmit={submitTyped} />
      )}
    </div>
  );
}
