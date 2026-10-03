import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { evaluateLeak } from '../audio/headphones';
import { analyzeTake } from '../audio/quality';
import { getRecorder, listMics, type PcmRecorder } from '../audio/recorder';
import { useTimer } from '../runner/useTimer';
import { clientInfo, loadSetup, saveSetup, setupComplete, type SetupData } from '../setup/store';

const NOISE_SECONDS = 10;
const TONE_SECONDS = 1.2;

/**
 * C0: pick the microphone, then one button runs both checks in order (10 s of silence for the
 * noise floor, then a tone through the headphones that the microphone must not hear), then the
 * sleep / stress / mood sliders. Results persist in sessionStorage until the sitting starts.
 */
export default function Setup() {
  const { t } = useTranslation();
  const { formId = '' } = useParams();
  const [params] = useSearchParams();
  const quick = params.get('quick') === '1'; // test/dev shortcut: 1 s of silence instead of 10 s
  const nav = useNavigate();
  const [setup, setSetup] = useState<SetupData>(() => loadSetup());
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [rec, setRec] = useState<PcmRecorder | null>(null);
  const [level, setLevel] = useState(-120);
  const [step, setStep] = useState<'noise' | 'tone' | 'start' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const noiseSeconds = quick ? 1 : NOISE_SECONDS;
  const timer = useTimer(step === 'noise' ? noiseSeconds : TONE_SECONDS, step === 'noise' || step === 'tone');

  const update = (patch: Partial<SetupData>) => setSetup((s) => { const n = { ...s, ...patch }; saveSetup(n); return n; });
  const showError = (e: unknown) => setError(String((e as Error).message ?? e));

  async function enableMic(deviceId?: string) {
    setError(null);
    try {
      const r = await getRecorder(deviceId);
      r.onLevel = (db) => setLevel(db);
      setRec(r);
      setMics(await listMics());
      // A different microphone invalidates earlier checks.
      update({ deviceId: r.info.deviceId, deviceLabel: r.info.label, sampleRate: r.info.sampleRate, noise_floor: null, headphones: null });
    } catch (e) {
      showError(e);
    }
  }

  useEffect(() => () => { if (rec) rec.onLevel = null; }, [rec]);

  async function runChecks() {
    if (!rec) return;
    setError(null);
    try {
      setStep('noise');
      const silence = await rec.recordFor(noiseSeconds * 1000);
      setStep('tone');
      const withTone = await rec.recordWithTone(TONE_SECONDS * 1000);
      update({
        noise_floor: analyzeTake(silence, rec.info.sampleRate),
        headphones: evaluateLeak(withTone, silence, rec.info.sampleRate),
      });
    } catch (e) {
      showError(e);
    } finally {
      setStep(null);
    }
  }

  async function start() {
    setStep('start');
    setError(null);
    try {
      const s = await api.createSession(formId, { ...setup, noise_seconds: noiseSeconds }, clientInfo());
      nav(`/session/${s.id}`);
    } catch (e) {
      showError(e);
      setStep(null);
    }
  }

  const hp = setup.headphones;
  const levelPct = Math.max(0, Math.min(100, ((level + 60) / 60) * 100));

  return (
    <div className="stack">
      <div className="card">
        <h2>{t('setup.title')}</h2>
        <p>{t('setup.intro')} <strong>{t('setup.headphones_required')}</strong></p>
        {error && <p className="status-bad">{error}</p>}
      </div>

      <div className="card stack">
        <h3>{t('setup.mic')}</h3>
        {!rec && <button className="primary" onClick={() => enableMic()} data-testid="enable-mic">{t('setup.enable_mic')}</button>}
        {rec && (
          <>
            <select value={setup.deviceId} onChange={(e) => enableMic(e.target.value)} data-testid="mic-select">
              {mics.map((m) => <option key={m.deviceId} value={m.deviceId}>{m.label || m.deviceId}</option>)}
            </select>
            <div className="muted">{t('setup.level')} · {setup.sampleRate} Hz</div>
            <div className="meter"><div style={{ width: `${levelPct}%` }} /></div>
          </>
        )}
      </div>

      <div className="card stack">
        <h3>{t('setup.checks_title')}</h3>
        <p>{t('setup.checks_help', { n: noiseSeconds })}</p>
        {step === 'noise' || step === 'tone' ? (
          <div className="stack" style={{ gap: 6 }}>
            <div className="meter"><div style={{ width: `${timer.pct}%`, transition: 'width 100ms linear' }} /></div>
            <div className="muted" data-testid="check-step">
              {step === 'noise' ? t('setup.step_noise') : t('setup.step_tone')} · {t('setup.seconds_left', { s: timer.left.toFixed(1) })}
            </div>
          </div>
        ) : (
          <button onClick={runChecks} disabled={!rec || step !== null} data-testid="run-checks">
            {setup.noise_floor ? t('setup.run_checks_again') : t('setup.run_checks')}
          </button>
        )}
        {setup.noise_floor && <div data-testid="noise-result">{t('setup.noise_result', { dbfs: setup.noise_floor.rms_dbfs ?? '—' })}</div>}
        {hp && (
          <div className="row">
            <span data-testid="headphone-result" className={hp.ok ? 'status-ok' : 'status-bad'}>
              {hp.ok ? t('setup.headphone_ok', { dbfs: hp.tone_dbfs }) : t('setup.headphone_leak', { dbfs: hp.tone_dbfs, db: hp.leak_db })}
              {hp.override && ` · ${t('setup.override_noted')}`}
            </span>
            {!hp.ok && <button onClick={() => update({ headphones: { ...hp, ok: true, override: true } })} data-testid="headphone-override">{t('setup.continue_anyway')}</button>}
          </div>
        )}
      </div>

      <div className="card stack">
        <h3>{t('setup.covariates')}</h3>
        <label className="field">
          <span>{t('setup.sleep')}: <strong>{setup.sleep_h}</strong></span>
          <input type="range" min={0} max={12} step={0.5} value={setup.sleep_h} onChange={(e) => update({ sleep_h: Number(e.target.value) })} data-testid="sleep" />
        </label>
        <label className="field">
          <span>{t('setup.stress')}: <strong>{setup.stress}</strong></span>
          <input type="range" min={0} max={10} step={1} value={setup.stress} onChange={(e) => update({ stress: Number(e.target.value) })} data-testid="stress" />
        </label>
        <label className="field">
          <span>{t('setup.mood')}: <strong>{setup.mood}</strong></span>
          <input type="range" min={0} max={10} step={1} value={setup.mood} onChange={(e) => update({ mood: Number(e.target.value) })} data-testid="mood" />
        </label>
      </div>

      <div className="card">
        {!setupComplete(setup) && <p className="muted">{t('setup.need_all')}</p>}
        <button className="primary" disabled={!setupComplete(setup) || step !== null} onClick={start} data-testid="start-session">{t('setup.continue')}</button>
      </div>
    </div>
  );
}
