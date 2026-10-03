import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { FormSummary, SessionOut } from '../types';
import { subscribe } from '../upload/queue';
import { useLang } from '../useLang';

/** Start or resume a sitting. Results and past sittings live on the dashboard. */
export default function Home() {
  const { t } = useTranslation();
  const lang = useLang();
  const [forms, setForms] = useState<FormSummary[] | null>(null);
  const [open, setOpen] = useState<SessionOut[]>([]);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [env, setEnv] = useState('prod');

  useEffect(() => {
    api.me().then((m) => setEnv(m.env)).catch(() => undefined);
    api.listForms().then(setForms).catch((e) => setError(String(e.message)));
    api.listSessions().then((all) => setOpen(all.filter((s) => s.status === 'open'))).catch(() => undefined);
    return subscribe(setPending);
  }, []);

  return (
    <div className="stack">
      {pending > 0 && <p className="status-warn" data-testid="pending">{t('home.pending', { n: pending })}</p>}

      {open.length > 0 && (
        <div className="card">
          <h2>{t('home.open_sessions')}</h2>
          {open.map((s) => (
            <div key={s.id} className="row" style={{ justifyContent: 'space-between', padding: '6px 0' }}>
              <span>{new Date(s.started_at).toLocaleString()} · <strong>{s.form_id}</strong> · {t('home.takes_n', { n: s.takes.filter((tk) => tk.status !== 'rejected').length })}</span>
              <Link to={`/session/${s.id}`}><button className="primary" data-testid={`resume-${s.id}`}>{t('home.resume')}</button></Link>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h2>{t('home.forms')}</h2>
        {error && <p className="status-bad">{error}</p>}
        {!forms && !error && <p className="muted">{t('common.loading')}</p>}
        {forms?.filter((f) => f.kind !== 'dummy' || env !== 'prod').map((f) => (
          <div className="row" key={f.id} style={{ justifyContent: 'space-between', padding: '8px 0' }}>
            <div>
              <strong>{f.title[lang]}</strong>
              <div className="muted">{f.id} · {t('home.tasks', { tasks: f.task_count, items: f.item_count })}</div>
            </div>
            <Link to={`/setup/${f.id}`}><button className="primary" data-testid={`start-${f.id}`}>{t('home.start')}</button></Link>
          </div>
        ))}
      </div>
    </div>
  );
}
