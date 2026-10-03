import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useLang } from '../useLang';

interface Latest { value: number | null; n: number; ci95: [number, number] | null; anchor: number | null; pct_of_anchor: number | null; scale: number | null; session_id: string; form_id: string; started_at: string }
interface Point { session_id: string; form_id: string; started_at: string; value: number; ci95: [number, number] | null; scale: number | null }
interface Metric { id: string; unit: string; direction: 'higher' | 'lower' | 'none'; definition: { en: string; ko: string }; latest: Latest; trend: { points: Point[]; change: number | null; detectable: boolean | null } | null }
interface Estimate { skill: string; cefr: string | null; toefl: [number, number] | null; ielts: [number, number] | null; based_on: { metric: string; value: number; level: string }[]; spread?: number; label: string }
interface SessionRow { id: string; form_id: string; form_kind: string; started_at: string; finished_at: string | null }
export interface DashboardData {
  subject: { email: string; role: string };
  viewer: { email: string; role: string };
  sessions: SessionRow[];
  domains: Record<string, Metric[]>;
  estimates: Estimate[];
  anchors_available: Record<string, boolean>;
}

const DOMAIN_ORDER = ['speaking', 'listening', 'reading', 'writing', 'vocabulary', 'self', 'quality'];

function fmt(v: number | null | undefined, unit = ''): string {
  if (v === null || v === undefined) return '—';
  const s = Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
  return unit ? `${s} ${unit}` : s;
}

/** Tiny inline trend chart with a CI band. */
export function Sparkline({ points, width = 160, height = 40 }: { points: Point[]; width?: number; height?: number }) {
  if (points.length === 0) return null;
  const vals = points.flatMap((p) => [p.value, ...(p.ci95 ?? [])]);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const x = (i: number) => (points.length === 1 ? width / 2 : 6 + (i * (width - 12)) / (points.length - 1));
  const y = (v: number) => height - 4 - ((v - lo) / span) * (height - 8);
  const line = points.map((p, i) => `${x(i)},${y(p.value)}`).join(' ');
  const band = points.every((p) => p.ci95)
    ? [...points.map((p, i) => `${x(i)},${y(p.ci95![1])}`), ...points.map((p, i) => `${x(i)},${y(p.ci95![0])}`).reverse()].join(' ')
    : null;
  return (
    <svg width={width} height={height} aria-hidden="true">
      {band && <polygon points={band} fill="var(--accent)" opacity={0.15} />}
      <polyline points={line} fill="none" stroke="var(--accent)" strokeWidth={2} />
      {points.map((p, i) => <circle key={p.session_id} cx={x(i)} cy={y(p.value)} r={2.5} fill="var(--accent)" />)}
    </svg>
  );
}

export default function Dashboard() {
  const { t } = useTranslation();
  const lang = useLang();
  const [data, setData] = useState<DashboardData | null>(null);
  const [subject, setSubject] = useState<'learner' | 'me'>('learner');
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api.dashboard(subject).then(setData).catch((e) => setError(String(e.message)));
  }, [subject]);

  const sessionsNewestFirst = useMemo(() => (data ? [...data.sessions].reverse() : []), [data]);

  async function exportSession(id: string) {
    setExporting(id);
    try {
      const json = await api.exportSession(id);
      const blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `assessment_result.v1.${id}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setExporting(null);
    }
  }

  if (error) return <div className="card status-bad">{error}</div>;
  if (!data) return <div className="card muted">{t('common.loading')}</div>;

  return (
    <div className="stack" data-testid="dashboard">
      <div className="card row" style={{ justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ margin: 0 }}>{t('dash.title')}</h2>
          <div className="muted">{t('dash.subject')}: {data.subject.email} · {t('dash.sessions_n', { n: data.sessions.length })}</div>
        </div>
        {data.viewer.role === 'anchor' && (
          <div className="row">
            <button className={subject === 'learner' ? 'primary' : ''} onClick={() => setSubject('learner')}>{t('dash.learner')}</button>
            <button className={subject === 'me' ? 'primary' : ''} onClick={() => setSubject('me')}>{t('dash.me')}</button>
          </div>
        )}
      </div>

      <div className="card">
        <h3>{t('dash.estimates')} <span className="muted" style={{ fontWeight: 400 }}>· {t('dash.estimate_note')}</span></h3>
        <div className="row" style={{ gap: 16 }}>
          {data.estimates.map((e) => (
            <div key={e.skill} className="card" style={{ flex: '1 1 140px', margin: 0 }} data-testid={`estimate-${e.skill}`}>
              <div className="muted">{t(`dash.skill.${e.skill}`)}</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700 }}>{e.cefr ?? '—'}</div>
              <div className="muted">TOEFL {e.toefl ? `${e.toefl[0]}–${e.toefl[1]}` : '—'} · IELTS {e.ielts ? `${e.ielts[0]}–${e.ielts[1]}` : '—'}</div>
              {e.based_on.length > 0 && <div className="muted" style={{ fontSize: '0.75rem' }}>{t('dash.based_on', { n: e.based_on.length })}{e.spread ? ` · ${t('dash.spread', { n: e.spread })}` : ''}</div>}
            </div>
          ))}
          {data.estimates.length === 0 && <span className="muted">{t('dash.no_data')}</span>}
        </div>
      </div>

      {DOMAIN_ORDER.filter((d) => data.domains[d]?.length).map((d) => (
        <div className="card" key={d} data-testid={`domain-${d}`}>
          <h3>{t(`dash.domain.${d}`)}</h3>
          <table className="stats" style={{ width: '100%' }}>
            <thead><tr className="muted"><th style={{ textAlign: 'left' }}>{t('dash.metric')}</th><th>{t('dash.value')}</th><th>{t('dash.anchor')}</th><th>{t('dash.scale')}</th><th>{t('dash.trend')}</th></tr></thead>
            <tbody>
              {data.domains[d].map((m) => (
                <tr key={m.id} data-testid={`metric-${m.id}`}>
                  <td style={{ maxWidth: 320 }}>
                    <div>{m.definition[lang]}</div>
                    <div className="muted" style={{ fontSize: '0.75rem' }}>{m.id}{m.direction !== 'none' ? ` · ${m.direction === 'higher' ? t('dash.higher_better') : t('dash.lower_better')}` : ''}</div>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <strong>{fmt(m.latest.value, m.unit)}</strong>
                    {m.latest.ci95 && <div className="muted" style={{ fontSize: '0.75rem' }}>95% CI {fmt(m.latest.ci95[0])}–{fmt(m.latest.ci95[1])} · n={m.latest.n}</div>}
                  </td>
                  <td>{fmt(m.latest.anchor)}{m.latest.pct_of_anchor !== null && <div className="muted" style={{ fontSize: '0.75rem' }}>{m.latest.pct_of_anchor}%</div>}</td>
                  <td style={{ minWidth: 90 }}>
                    {m.latest.scale !== null ? (
                      <div className="meter" title={`${m.latest.scale}/100`}><div style={{ width: `${m.latest.scale}%` }} /></div>
                    ) : <span className="muted">—</span>}
                  </td>
                  <td>
                    {m.trend && <Sparkline points={m.trend.points} />}
                    {m.trend?.change !== null && m.trend?.change !== undefined && (
                      <div className="muted" style={{ fontSize: '0.75rem' }}>
                        {m.trend.change > 0 ? '+' : ''}{fmt(m.trend.change)} · {m.trend.detectable === true ? t('dash.detectable') : m.trend.detectable === false ? t('dash.not_detectable') : t('dash.uncertain_change')}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      <div className="card">
        <h3>{t('dash.sessions')}</h3>
        {sessionsNewestFirst.length === 0 && <p className="muted">{t('dash.no_data')}</p>}
        {sessionsNewestFirst.map((s) => (
          <div key={s.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
            <div>{new Date(s.started_at).toLocaleString()} · <strong>{s.form_id}</strong> <span className="muted">({s.form_kind})</span></div>
            <div className="row">
              <Link to={`/session-takes/${s.id}`}><button>{t('dash.recordings')}</button></Link>
              <button onClick={() => exportSession(s.id)} disabled={exporting === s.id} data-testid={`export-${s.id}`}>{t('dash.export')}</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
