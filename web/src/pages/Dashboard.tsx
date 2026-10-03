import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useLang } from '../useLang';
import { DOMAIN_ORDER, fmt, QUALITY, type DashboardData, type Point } from './dash';

const small = { fontSize: '0.75rem' } as const;

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
  const [subject, setSubject] = useState<'learner' | 'me'>('learner');
  const [loaded, setLoaded] = useState<{ subject: string; data: DashboardData } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);

  useEffect(() => {
    api.dashboard(subject).then((data) => setLoaded({ subject, data })).catch((e) => setError(String(e.message)));
  }, [subject]);
  const data = loaded?.subject === subject ? loaded.data : null;
  const newestFirst = useMemo(() => (data ? [...data.per_session].reverse() : []), [data]);

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
  const latest = newestFirst[0]?.session;

  return (
    <div className="stack" data-testid="dashboard">
      <div className="card row" style={{ justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ margin: 0 }}>{t('dash.title')}</h2>
          <div className="muted">{t('dash.subject')}: {data.subject.email} · {t('dash.sessions_n', { n: data.sessions.length })}</div>
          {latest && (
            <div className="muted" data-testid="latest-sitting">
              {t('dash.latest')}: {new Date(latest.started_at).toLocaleString()} · {latest.form_id} · {t(`dash.status.${latest.status}`)} · {t('dash.items_done', { done: latest.items_done, total: latest.items_total ?? '?' })}
            </div>
          )}
        </div>
        <div className="row">
          {data.viewer.role === 'anchor' && (
            <>
              <button className={subject === 'learner' ? 'primary' : ''} onClick={() => setSubject('learner')}>{t('dash.learner')}</button>
              <button className={subject === 'me' ? 'primary' : ''} onClick={() => setSubject('me')}>{t('dash.me')}</button>
            </>
          )}
          <Link to="/"><button className="primary" data-testid="dash-start">{t('dash.start_sitting')}</button></Link>
        </div>
      </div>

      <div className="card">
        <h3>{t('dash.estimates')} <span className="muted" style={{ fontWeight: 400 }}>· {t('dash.estimate_note')}</span></h3>
        <div className="row" style={{ gap: 16 }}>
          {data.estimates.map((e) => (
            <div key={e.skill} className="card" style={{ flex: '1 1 140px', margin: 0 }} data-testid={`estimate-${e.skill}`}>
              <div className="muted">{t(`dash.skill.${e.skill}`)}</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700 }}>{e.cefr ?? '—'}</div>
              <div className="muted">TOEFL {e.toefl ? `${e.toefl[0]}–${e.toefl[1]}` : '—'} · IELTS {e.ielts ? `${e.ielts[0]}–${e.ielts[1]}` : '—'}</div>
              {e.based_on.length > 0 && (
                <div className="muted" style={small}>
                  {t('dash.based_on', { n: e.based_on.length })}{e.spread ? ` · ${t('dash.spread', { n: e.spread })}` : ''}{e.form_id ? ` · ${e.form_id}` : ''}
                </div>
              )}
            </div>
          ))}
          {data.estimates.length === 0 && <span className="muted">{t('dash.no_data')}</span>}
        </div>
      </div>

      {DOMAIN_ORDER.filter((d) => data.domains[d]?.length).map((d) => (
        <div className="card" key={d} data-testid={`domain-${d}`}>
          <h3>{t(`dash.domain.${d}`)}</h3>
          <table className="stats" style={{ width: '100%' }}>
            <thead><tr><th>{t('dash.metric')}</th><th>{t('dash.value')}</th><th>{t('dash.anchor')}</th><th>{t('dash.scale')}</th><th>{t('dash.trend')}</th></tr></thead>
            <tbody>
              {data.domains[d].map((m) => (
                <tr key={m.id} data-testid={`metric-${m.id}`}>
                  <td style={{ maxWidth: 320 }}>
                    <div>{m.definition[lang]}</div>
                    <div className="muted" style={small}>{m.id}{m.direction !== 'none' ? ` · ${m.direction === 'higher' ? t('dash.higher_better') : t('dash.lower_better')}` : ''}</div>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <strong>{fmt(m.latest.value, m.unit)}</strong>
                    {m.latest.ci95 && <div className="muted" style={small}>95% CI {fmt(m.latest.ci95[0])}–{fmt(m.latest.ci95[1])} · n={m.latest.n}</div>}
                    <div className="muted" style={small}>{new Date(m.latest.started_at).toLocaleDateString()} · {m.latest.form_id}</div>
                  </td>
                  <td>{fmt(m.latest.anchor)}{m.latest.pct_of_anchor !== null && <div className="muted" style={small}>{m.latest.pct_of_anchor}%</div>}</td>
                  <td style={{ minWidth: 90 }}>
                    {m.latest.scale !== null ? <div className="meter" title={`${m.latest.scale}/100`}><div style={{ width: `${m.latest.scale}%` }} /></div> : <span className="muted">—</span>}
                  </td>
                  <td>
                    {m.trend && <Sparkline points={m.trend.points} />}
                    {m.trend?.change !== null && m.trend?.change !== undefined && (
                      <div className="muted" style={small}>
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

      {newestFirst.length > 0 && (
        <div className="card" data-testid="domain-quality">
          <h3>{t('dash.domain.quality')} <span className="muted" style={{ fontWeight: 400 }}>· {t('dash.quality_note')}</span></h3>
          <table className="stats" style={{ width: '100%' }}>
            <thead><tr><th>{t('dash.sitting')}</th>{QUALITY.map((q) => <th key={q}>{t(`dash.q.${q}`)}</th>)}<th>{t('dash.q.covariates')}</th></tr></thead>
            <tbody>
              {newestFirst.map(({ session: s, metrics: m }) => (
                <tr key={s.id} data-testid={`quality-${s.id}`}>
                  <td>{new Date(s.started_at).toLocaleDateString()} · {s.form_id}<div className="muted" style={small}>{t(`dash.status.${s.status}`)}{s.mic ? ` · ${s.mic}` : ''}</div></td>
                  {QUALITY.map((q) => <td key={q}>{fmt(m[q]?.value, unitOf(q))}{q === 'headphone_leak_db' && s.headphone_override ? ' ⚠' : ''}</td>)}
                  <td className="muted">{t('dash.q.sleep')} {m.sleep_h?.value ?? '—'} · {t('dash.q.stress')} {m.stress?.value ?? '—'} · {t('dash.q.mood')} {m.mood?.value ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.costs && (
        <div className="card" data-testid="costs">
          <h3>{t('dash.costs')} <span className="muted" style={{ fontWeight: 400 }}>· {t('dash.costs_note')}</span></h3>
          <p>{t('dash.all_time')}: <strong>${data.costs.all_time.total_usd.toFixed(2)}</strong> <span className="muted">({Object.entries(data.costs.all_time.by_engine).map(([e, c]) => `${e} $${c.toFixed(2)}`).join(' · ')})</span></p>
          <table className="stats" style={{ width: '100%' }}>
            <thead><tr><th>{t('dash.sitting')}</th><th>{t('dash.cost')}</th><th>{t('dash.by_engine')}</th></tr></thead>
            <tbody>
              {newestFirst.map(({ session: s }) => {
                const c = data.costs!.sessions[s.id];
                return (
                  <tr key={s.id}>
                    <td>{new Date(s.started_at).toLocaleDateString()} · {s.form_id}</td>
                    <td>${c ? c.total_usd.toFixed(2) : '0.00'}</td>
                    <td className="muted" style={{ fontSize: '0.85rem' }}>{c ? Object.entries(c.by_engine).map(([e, v]) => `${e} $${v.cost_usd.toFixed(2)} (${v.calls})`).join(' · ') : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h3>{t('dash.sessions')}</h3>
        {newestFirst.length === 0 && <p className="muted">{t('dash.no_data')}</p>}
        {newestFirst.map(({ session: s }) => (
          <div key={s.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--rule)' }}>
            <div>
              {new Date(s.started_at).toLocaleString()} · <strong>{s.form_id}</strong> <span className="muted">({s.form_kind})</span>
              <div className="muted" style={{ fontSize: '0.8rem' }}>{t(`dash.status.${s.status}`)} · {t('dash.items_done', { done: s.items_done, total: s.items_total ?? '?' })} · {t('dash.processed_n', { n: s.processed, total: s.takes })}</div>
            </div>
            <div className="row">
              <Link to={`/sitting/${s.id}`}><button data-testid={`sitting-${s.id}`}>{t('dash.details')}</button></Link>
              <Link to={`/session-takes/${s.id}`}><button>{t('dash.recordings')}</button></Link>
              <button onClick={() => exportSession(s.id)} disabled={exporting === s.id} data-testid={`export-${s.id}`}>{t('dash.export')}</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function unitOf(q: (typeof QUALITY)[number]): string {
  return q.endsWith('_dbfs') ? 'dBFS' : q.endsWith('_db') ? 'dB' : q.endsWith('_pct') || q === 'transcript_agreement' ? '%' : '';
}
