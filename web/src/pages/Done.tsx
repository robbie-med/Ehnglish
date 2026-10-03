import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { releaseRecorder } from '../audio/recorder';
import { pendingForSession, subscribe } from '../upload/queue';

export default function Done() {
  const { t } = useTranslation();
  const { sessionId = '' } = useParams();
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    releaseRecorder();
    const refresh = () => void pendingForSession(sessionId).then(setPending);
    refresh();
    return subscribe(refresh);
  }, [sessionId]);

  return (
    <div className="card stack">
      <h2>{t('done.title')}</h2>
      <p>{t('done.body')}</p>
      <p data-testid="upload-state" className={pending ? 'status-warn' : 'status-ok'}>
        {pending === null ? t('common.loading') : pending > 0 ? t('done.uploads_pending', { n: pending }) : t('done.uploads_done')}
      </p>
      <p className="muted">{t('done.session')}: <code data-testid="session-id">{sessionId}</code></p>
      <div className="row">
        <Link to="/dashboard"><button className="primary">{t('nav.dashboard')}</button></Link>
        <Link to="/"><button>{t('done.home')}</button></Link>
      </div>
    </div>
  );
}
