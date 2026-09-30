import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import TaskRunner from '../runner/TaskRunner';
import type { Form, SessionOut } from '../types';

export default function Session() {
  const { t } = useTranslation();
  const { sessionId = '' } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<SessionOut | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSession(sessionId)
      .then(async (s) => { setSession(s); setForm(await api.getForm(s.form_id)); })
      .catch((e) => setError(String(e.message)));
  }, [sessionId]);

  if (error) return <div className="card status-bad">{error}</div>;
  if (!session || !form) return <div className="card muted">{t('common.loading')}</div>;
  return <TaskRunner form={form} session={session} onFinished={() => nav(`/done/${session.id}`)} />;
}
