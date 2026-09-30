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
import { countItems, initialState, reduce, type RunnerState } from './machine';
import { useCountdown } from './useCountdown';

interface Props { form: Form; session: SessionOut; onFinished: () => void }

interface LastTake { takeId: string; pcm: Int16Array; quality: QualityReport }

export default function TaskRunner({ form, session, onFinished }: Props) {
  const { t } = useTranslation();
  const lang = useLang();
  const [state, dispatch] = useReducer((s: RunnerState, a: Parameters<typeof reduce>[2]) => reduce(form, s, a), initialState);
  const [rec, setRec] = useState<PcmRecorder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<LastTake | null>(null);
  const [busy, setBusy] = useState(false);
  const takeIdRef = useRef<string | null>(null);
  const eventsRef = useRef<EventIn[]>([]);
  const keysRef = useRef(new KeystrokeLogger());
  const textRef = useRef<HTMLTextAreaElement | null>(null);
  const setup = useMemo(() => loadSetup(), []);

  const task = form.tasks[state.taskIdx];
  const item = task?.items[state.itemIdx];
  const total = countItems(form);
  const doneItems = form.tasks.slice(0, state.taskIdx).reduce((n, tk) => n + tk.items.length, 0) + state.itemIdx;

  const mark = useCallback((name: string, meta?: Record<string, unknown>) => {
    eventsRef.current.push({ name, t_client_ms: performance.now(), meta });
  }, []);

  const fail = (e: unknown) => setError(String((e as Error).message ?? e));

  // Create the take row when an item starts (prep or respond phase, attempt-specific).
  useEffect(() => {
    if (!task || !item) return;
    if (state.phase !== 'prep' && state.phase !== 'respond') return;
    if (takeIdRef.current) return; // already created for this attempt
    const kind = task.type === 'read_aloud' ? ('audio' as const) : ('typed' as const);
    const body = kind === 'audio'
      ? { task_id: task.id, item_id: item.id, attempt: state.attempt, kind, sample_rate: rec?.info.sampleRate ?? setup.sampleRate, channels: 1 }
      : { task_id: task.id, item_id: item.id, attempt: state.attempt, kind };
    api.createTake(session.id, body).then((tk) => {
      takeIdRef.current = tk.id;
      eventsRef.current = [];
      mark('item_shown', { phase: state.phase });
    }).catch(fail);
  }, [state.phase, state.taskIdx, state.itemIdx, state.attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  async function begin() {
    try {
      const r = await getRecorder(setup.deviceId || undefined);
      setRec(r);
      dispatch({ type: 'BEGIN' });
    } catch (e) {
      fail(e);
    }
  }

  // --- audio item -------------------------------------------------------
  const onPrepDone = useCallback(() => {
    mark('prompt_end');
    dispatch({ type: 'PREP_DONE' });
  }, [mark]);

  useEffect(() => {
    if (state.phase !== 'respond' || task?.type !== 'read_aloud' || !rec) return;
    let cancelled = false;
    (async () => {
      mark('record_start');
      await rec.start();
      await new Promise((r) => setTimeout(r, task.timing.respond_s * 1000));
      if (cancelled) return;
      const pcm = await rec.stop();
      mark('record_stop');
      const quality = analyzeTake(pcm, rec.info.sampleRate, setup.noise_floor?.rms_dbfs ?? null);
      // Wait for the take row if the network was slow.
      for (let i = 0; i < 50 && !takeIdRef.current; i++) await new Promise((r) => setTimeout(r, 100));
      const takeId = takeIdRef.current;
      if (!takeId) { fail(new Error('take was not created')); return; }
      setLast({ takeId, pcm, quality });
      dispatch({ type: 'RESPONSE_DONE' });
    })().catch(fail);
    return () => { cancelled = true; };
  }, [state.phase, state.attempt, state.itemIdx, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  async function accept() {
    if (!last || !rec) return;
    setBusy(true);
    try {
      mark('accepted');
      const wav = encodeWav(last.pcm, rec.info.sampleRate, 1);
      const sha = await sha256Hex(wav);
      await enqueueUpload(last.takeId, session.id, wav, sha, last.quality);
      await api.postEvents(last.takeId, eventsRef.current).catch(() => undefined);
      void processQueue(api);
      takeIdRef.current = null;
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

  // --- typed item -------------------------------------------------------
  useEffect(() => {
    if (state.phase === 'respond' && task?.type === 'typed_response' && textRef.current) {
      keysRef.current.attach(textRef.current);
      textRef.current.focus();
      mark('prompt_end');
    }
    return () => keysRef.current.detach();
  }, [state.phase, state.itemIdx, state.taskIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submitTyped() {
    const el = textRef.current;
    const takeId = takeIdRef.current;
    if (!el || !takeId) return;
    setBusy(true);
    try {
      mark('submit');
      await api.submitTyped(takeId, el.value, keysRef.current.events);
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

  // --- finish -----------------------------------------------------------
  useEffect(() => {
    if (state.phase === 'done') {
      api.patchSession(session.id, { status: 'done' }).catch(() => undefined).finally(onFinished);
    }
  }, [state.phase]); // eslint-disable-line react-hooks/exhaustive-deps

  const prepLeft = useCountdown(task?.timing.prep_s ?? 0, state.phase === 'prep', onPrepDone);
  const respondLeft = useCountdown(task?.timing.respond_s ?? 0, state.phase === 'respond' && task?.type === 'read_aloud', () => undefined);
  const typedLeft = useCountdown(task?.timing.respond_s ?? 0, state.phase === 'respond' && task?.type === 'typed_response', typedDeadline);

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
  if (state.phase === 'done') return <div className="card">{t('common.loading')}</div>;

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

      {task.type === 'read_aloud' && (state.phase === 'prep' || state.phase === 'respond') && (
        <div className="card stack">
          <div className="muted">{t('runner.read_this')}</div>
          <p className="big" data-testid="item-text">{item.text}</p>
          {state.phase === 'prep' && <div className="countdown" data-testid="prep">{t('runner.get_ready')} · {prepLeft}</div>}
          {state.phase === 'respond' && <div className="countdown status-bad" data-testid="recording"><span className="rec-dot" />{t('runner.recording')} · {respondLeft}</div>}
        </div>
      )}

      {task.type === 'read_aloud' && state.phase === 'review' && last && (
        <div className="card stack" data-testid="review">
          <h3>{t('runner.review_title')}</h3>
          <div>{t('runner.duration', { s: last.quality.duration_s })}</div>
          <div className={last.quality.ok ? 'status-ok' : 'status-warn'}>{last.quality.ok ? t('runner.quality_ok') : t('runner.quality_issue')}</div>
          {last.quality.flags.length > 0 && <ul className="flags">{last.quality.flags.map((f) => <li key={f}>{t(`quality.${f}`)}</li>)}</ul>}
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

      {task.type === 'typed_response' && state.phase === 'respond' && (
        <div className="card stack">
          <p className="big" data-testid="item-prompt">{item.prompt?.[lang]}</p>
          <div className="muted">{t('common.seconds', { n: typedLeft })}</div>
          <textarea ref={textRef} placeholder={t('runner.type_here')} data-testid="typed-input" spellCheck={false} autoCorrect="off" />
          <button className="primary" onClick={submitTyped} disabled={busy} data-testid="done-typing">{t('runner.done_typing')}</button>
        </div>
      )}
    </div>
  );
}
