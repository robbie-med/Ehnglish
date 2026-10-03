import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, Route, Routes } from 'react-router-dom';
import { api } from './api/client';
import { setLang, type Lang } from './i18n';
import { startUploader } from './upload/queue';
import Home from './pages/Home';
import Setup from './pages/Setup';
import Session from './pages/Session';
import Done from './pages/Done';
import Dashboard from './pages/Dashboard';
import Viewer, { SessionTakes } from './pages/Viewer';

export default function App() {
  const { t, i18n } = useTranslation();
  const [email, setEmail] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    api.me().then((m) => setEmail(m.email)).catch((e) => setAuthError(String(e.message ?? e)));
    return startUploader(api);
  }, []);

  const other: Lang = i18n.language.startsWith('ko') ? 'en' : 'ko';
  return (
    <>
      <header className="top">
        <Link to="/"><h1>{t('app.title')} <span className="muted">· {t('app.subtitle')}</span></h1></Link>
        <div className="row">
          <Link to="/"><button className="link" data-testid="nav-home">{t('nav.tests')}</button></Link>
          <Link to="/dashboard"><button className="link" data-testid="nav-dashboard">{t('nav.dashboard')}</button></Link>
          {email && <span className="who" data-testid="who">{email}</span>}
          <button className="link" onClick={() => setLang(other)} aria-label="language">{t('nav.language')}</button>
        </div>
      </header>
      {authError && <div className="card status-bad">{t('common.error')}: {authError}</div>}
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/setup/:formId" element={<Setup />} />
        <Route path="/session/:sessionId" element={<Session />} />
        <Route path="/done/:sessionId" element={<Done />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/session-takes/:sessionId" element={<SessionTakes />} />
        <Route path="/viewer/:takeId" element={<Viewer />} />
      </Routes>
    </>
  );
}
