import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { evaluateLeak } from '../audio/headphones';
import { analyzeTake } from '../audio/quality';
import { getRecorder, listMics, type PcmRecorder } from '../audio/recorder';
import { clientInfo, loadSetup, saveSetup, setupComplete, type SetupData } from '../setup/store';

const NOISE_SECONDS = 10;

export default function Setup() {
  const { t } = useTranslation();
  const { formId = '' } = useParams();
  const [params] = useSearchParams();
  const quick = params.get('quick') === '1'; // test/dev shortcut: 1 s silence instead of 10 s
  const nav = useNavigate();
  const [setup, setSetup] = useState<SetupData>(() => loadSetup());
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [rec, setRec] = useState<PcmRecorder | null>(null);
  const [level, setLevel] = useState(-120);
  const [busy, setBusy] = useState<'noise' | 'tone' | 'start' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const silenceRef = useRef<Int16Array | null>(null);

  const update = (patch: Partial<SetupData>) => setSetup((s) => { const n = { ...s, ...patch }; saveSetup(n); return n; });

  async function enableMic(deviceId?: string) {
    setError(null);
    try {
      const r = await getRecorder(deviceId);
      r.onLevel = (db) => setLevel(db);
      setRec(r);
      setMics(await listMics());
      update({ deviceId: r.info.deviceId, deviceLabel: r.info.label, sampleRate: r.info.sampleRate, noise_floor: null, headphones: null });
      silenceRef.current = null;
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }

  useEffect(() => () => { if (rec) rec.onLevel = null; }, [rec]);

  async function measureNoise() {
    if (!rec) return;
    setBusy('noise');
    try {
      const pcm = await rec.recordFor((quick ? 1 : NOISE_SECONDS) * 1000);
      silenceRef.current = pcm;
      update({ noise_floor: analyzeTake(pcm, rec.info.sampleRate), headphones: null });
    } finally {
      setBusy(null);
    }
  }

  async function headphoneCheck() {
    if (!rec || !silenceRef.current) return;
    setBusy('tone');
    try {
      const withTone = await rec.recordWithTone(1200);
      update({ headphones: evaluateLeak(withTone, silenceRef.current, rec.info.sampleRate) });
    } finally {
      setBusy(null);
    }
  }

  async function start() {
    setBusy('start');
    setError(null);
    try {
      const s = await api.createSession(formId, { ...setup, noise_seconds: quick ? 1 : NOISE_SECONDS }, clientInfo());
      nav(`/session/${s.id}`);
    } catch (e) {
      setError(String((e as Error).message ?? e));
      setBusy(null);
    }
  }

  const ready = setupComplete(setup);
  const pct = Math.max(0, Math.min(100, ((level + 60) / 60) * 100));

  return (
    <div className="stack">
      <div className="card">
        <h2>{t('setup.title')}</h2>
        <p>{t('setup.intro')}</p>
        <p><strong>{t('setup.headphones_required')}</strong></p>
        {error && <p className="status-bad">{error}</p>}
      </div>

      <div className="card stack">
        <h3>{t('setup.mic')}</h3>
        {!rec && <button className="primary" onClick={() => enableMic()} data-testid="enable-mic">{t('setup.enable_mic')}</button>}
        {rec && (
          <>
            <label className="field">
              <span>{t('setup.mic')}</span>
              <select value={setup.deviceId} onChange={(e) => enableMic(e.target.value)} data-testid="mic-select">
                {mics.map((m) => <option key={m.deviceId} value={m.deviceId}>{m.label || m.deviceId}</option>)}
              </select>
            </label>
            <div className="muted">{setup.deviceLabel} · {setup.sampleRate} Hz</div>
            <div>{t('setup.level')}</div>
            <div className="meter"><div style={{ width: `${pct}%` }} /></div>
          </>
        )}
      </div>

      <div className="card stack">
        <h3>{t('setup.noise_title')}</h3>
        <p>{t('setup.noise_help', { n: quick ? 1 : NOISE_SECONDS })}</p>
        <div className="row">
          <button onClick={measureNoise} disabled={!rec || busy !== null} data-testid="measure-noise">
            {busy === 'noise' ? t('setup.measuring') : t('setup.measure_noise')}
          </button>
          {setup.noise_floor && (
            <span data-testid="noise-result">{t('setup.noise_result', { dbfs: setup.noise_floor.rms_dbfs ?? '—' })}</span>
          )}
        </div>
      </div>

      <div className="card stack">
        <h3>{t('setup.headphone_title')}</h3>
        <p>{t('setup.headphone_help')}</p>
        <div className="row">
          <button onClick={headphoneCheck} disabled={!rec || !setup.noise_floor || busy !== null} data-testid="headphone-check">
            {busy === 'tone' ? t('setup.headphone_running') : t('setup.run_headphone')}
          </button>
          {setup.headphones && (
            <span data-testid="headphone-result" className={setup.headphones.ok ? 'status-ok' : 'status-bad'}>
              {setup.headphones.ok
                ? t('setup.headphone_ok', { db: setup.headphones.leak_db })
                : t('setup.headphone_leak', { db: setup.headphones.leak_db })}
            </span>
          )}
        </div>
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
        {!ready && <p className="muted">{t('setup.need_all')}</p>}
        <button className="primary" disabled={!ready || busy !== null} onClick={start} data-testid="start-session">{t('setup.continue')}</button>
      </div>
    </div>
  );
}
