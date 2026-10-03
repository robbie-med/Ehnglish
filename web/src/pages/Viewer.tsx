import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { SessionOut } from '../types';

interface ViewerData {
  take_id: string; task_id: string; item_id: string; duration_s: number | null; audio_url: string;
  words: { text: string; start: number | null; end: number | null; uncertain: boolean }[];
  pauses: [number, number][]; nuclei: number[];
  mismatches: { word: string; accuracy: number | null; error_type: string | null; start: number | null; end: number | null; phonemes: { phoneme: string; accuracy: number | null }[] }[];
  phonemes: { confusions?: { expected: string; produced: string; n: number }[]; contrast_errors?: Record<string, number>; extra_vowels?: number; per?: number };
  quality: Record<string, unknown> | null;
}

/** List of a session's audio takes, each linking to the viewer. */
export function SessionTakes() {
  const { t } = useTranslation();
  const { sessionId = '' } = useParams();
  const [s, setS] = useState<SessionOut | null>(null);
  useEffect(() => { api.getSession(sessionId).then(setS).catch(() => undefined); }, [sessionId]);
  if (!s) return <div className="card muted">{t('common.loading')}</div>;
  const audio = s.takes.filter((tk) => tk.kind === 'audio' && tk.status !== 'rejected');
  return (
    <div className="card stack">
      <h3>{t('viewer.recordings')} · {s.form_id}</h3>
      {audio.map((tk) => (
        <div key={tk.id} className="row" style={{ justifyContent: 'space-between' }}>
          <span>{tk.task_id}/{tk.item_id} · {tk.duration_s?.toFixed(1)} s · <span className="muted">{tk.status}</span></span>
          <Link to={`/viewer/${tk.id}`}><button>{t('viewer.open')}</button></Link>
        </div>
      ))}
      <Link to="/dashboard"><button>{t('viewer.back')}</button></Link>
    </div>
  );
}

export default function Viewer() {
  const { t } = useTranslation();
  const { takeId = '' } = useParams();
  const [d, setD] = useState<ViewerData | null>(null);
  const [pos, setPos] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => { api.takeViewer(takeId).then(setD).catch(() => undefined); }, [takeId]);
  if (!d) return <div className="card muted">{t('common.loading')}</div>;

  const seek = (s: number | null) => { if (s !== null && audioRef.current) { audioRef.current.currentTime = s; void audioRef.current.play(); } };
  const bad = new Set(d.mismatches.map((m) => m.word.toLowerCase()));
  const dur = d.duration_s ?? 1;

  return (
    <div className="stack" data-testid="viewer">
      <div className="card stack">
        <h3>{d.task_id}/{d.item_id} · {d.duration_s?.toFixed(1)} s</h3>
        <audio ref={audioRef} controls src={d.audio_url} style={{ width: '100%' }} onTimeUpdate={(e) => setPos((e.target as HTMLAudioElement).currentTime)} />
        {/* timeline: pauses as grey blocks, syllable nuclei as ticks, playhead */}
        <svg width="100%" height={28} viewBox={`0 0 1000 28`} preserveAspectRatio="none" aria-hidden="true">
          <rect x={0} y={10} width={1000} height={8} fill="var(--border)" />
          {d.pauses.map(([a, b], i) => <rect key={i} x={(a / dur) * 1000} y={6} width={Math.max(2, ((b - a) / dur) * 1000)} height={16} fill="var(--warn)" opacity={0.6} />)}
          {d.nuclei.map((n, i) => <rect key={`n${i}`} x={(n / dur) * 1000} y={10} width={1.5} height={8} fill="var(--accent)" />)}
          <rect x={(pos / dur) * 1000} y={2} width={2} height={24} fill="var(--bad)" />
        </svg>
        <p style={{ lineHeight: 2.2, fontSize: '1.1rem' }}>
          {d.words.map((w, i) => {
            const active = w.start !== null && w.end !== null && pos >= w.start && pos < w.end;
            const gapBefore = i > 0 && w.start !== null && d.words[i - 1].end !== null && w.start - (d.words[i - 1].end as number) >= 0.25;
            return (
              <span key={i}>
                {gapBefore && <span className="muted" title={t('viewer.pause')} style={{ margin: '0 6px' }}>··</span>}
                <span onClick={() => seek(w.start)} style={{ cursor: w.start !== null ? 'pointer' : 'default', padding: '2px 4px', borderRadius: 4, background: active ? 'var(--accent)' : 'transparent', color: active ? 'var(--accent-fg)' : undefined, textDecoration: bad.has(w.text.toLowerCase()) ? 'underline wavy var(--bad)' : w.uncertain ? 'underline dotted' : 'none', opacity: w.uncertain ? 0.6 : 1 }}>
                  {w.text}
                </span>{' '}
              </span>
            );
          })}
        </p>
        <div className="muted" style={{ fontSize: '0.8rem' }}>{t('viewer.legend')}</div>
      </div>
      {d.mismatches.length > 0 && (
        <div className="card">
          <h4>{t('viewer.mismatches')}</h4>
          <table className="stats"><tbody>
            {d.mismatches.map((m, i) => (
              <tr key={i}><td><span onClick={() => seek(m.start)} style={{ cursor: 'pointer' }}>{m.word}</span></td><td>{m.error_type ?? ''}</td><td>{m.accuracy ?? '—'}</td><td className="muted">{m.phonemes.map((p) => `${p.phoneme} (${p.accuracy ?? '—'})`).join(' ')}</td></tr>
            ))}
          </tbody></table>
        </div>
      )}
      {d.phonemes?.confusions && d.phonemes.confusions.length > 0 && (
        <div className="card">
          <h4>{t('viewer.phonemes')} · PER {d.phonemes.per ?? '—'} · {t('viewer.extra_vowels')} {d.phonemes.extra_vowels ?? 0}</h4>
          <div className="muted">{Object.entries(d.phonemes.contrast_errors ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—'}</div>
          <div className="muted" style={{ fontSize: '0.85rem' }}>{d.phonemes.confusions.slice(0, 12).map((c) => `${c.expected || '∅'}→${c.produced || '∅'} ×${c.n}`).join(' · ')}</div>
        </div>
      )}
      <Link to="/dashboard"><button>{t('viewer.back')}</button></Link>
    </div>
  );
}
