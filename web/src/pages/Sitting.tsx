import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { useLang } from '../useLang';
import { DOMAIN_ORDER, fmt, type Estimate, type SessionRow } from './dash';

/** One sitting's export (assessment_result.v1): the same record the Trainer reads. */
interface ExportData {
  session: SessionRow;
  metrics: Record<string, { value: number | null; n: number; ci95: [number, number] | null; anchor: number | null; unit: string; domain: string; definition: { en: string; ko: string } }>;
  estimates: Estimate[];
}

/** Every metric of one sitting, grouped by domain, straight from its export. */
export default function Sitting() {
  const { t } = useTranslation();
  const lang = useLang();
  const { sessionId = '' } = useParams();
  const [data, setData] = useState<ExportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.exportSession(sessionId).then((d) => setData(d as unknown as ExportData)).catch((e) => setError(String(e.message))); }, [sessionId]);
  if (error) return <div className="card status-bad">{error}</div>;
  if (!data) return <div className="card muted">{t('common.loading')}</div>;

  const s = data.session;
  const byDomain = new Map<string, string[]>();
  for (const [id, m] of Object.entries(data.metrics)) byDomain.set(m.domain, [...(byDomain.get(m.domain) ?? []), id]);
  const domains = [...DOMAIN_ORDER, 'quality'].filter((d) => byDomain.has(d));

  return (
    <div className="stack" data-testid="sitting">
      <div className="card">
        <h2>{new Date(s.started_at).toLocaleString()} · {s.form_id}</h2>
        <div className="muted">
          {t(`dash.status.${s.status}`)} · {t('dash.items_done', { done: s.items_done, total: s.items_total ?? '?' })} · {t('dash.processed_n', { n: s.processed, total: s.takes })}{s.mic ? ` · ${s.mic}` : ''}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {data.estimates.filter((e) => e.cefr).map((e) => <span key={e.skill} className="muted">{t(`dash.skill.${e.skill}`)}: <strong>{e.cefr}</strong></span>)}
        </div>
      </div>
      {domains.map((dom) => (
        <div className="card" key={dom}>
          <h3>{t(`dash.domain.${dom}`)}</h3>
          <table className="stats" style={{ width: '100%' }}><tbody>
            {byDomain.get(dom)!.map((id) => {
              const m = data.metrics[id];
              return (
                <tr key={id}>
                  <td style={{ maxWidth: 340 }}>{m.definition[lang]}<div className="muted" style={{ fontSize: '0.75rem' }}>{id}</div></td>
                  <td style={{ whiteSpace: 'nowrap' }}><strong>{fmt(m.value, m.unit)}</strong>{m.ci95 && <div className="muted" style={{ fontSize: '0.75rem' }}>95% CI {fmt(m.ci95[0])}–{fmt(m.ci95[1])} · n={m.n}</div>}</td>
                  <td className="muted">{m.anchor !== null ? `${t('dash.anchor')} ${fmt(m.anchor)}` : ''}</td>
                </tr>
              );
            })}
          </tbody></table>
        </div>
      ))}
      <div className="row">
        <Link to={`/session-takes/${s.id}`}><button>{t('dash.recordings')}</button></Link>
        <Link to="/dashboard"><button>{t('viewer.back')}</button></Link>
      </div>
    </div>
  );
}
