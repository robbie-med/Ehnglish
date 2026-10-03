import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import './i18n';
import './index.css';
import App from './App';
import { registerSW } from 'virtual:pwa-register';

// Take new builds immediately (Safari/iPad otherwise keeps the old worker until every tab is closed),
// and poll for a new worker every 30 minutes while the app is open.
// Never swap builds mid-sitting: apply when the learner is not on a /session/ page.
let pendingUpdate = false;
const inSitting = () => location.pathname.startsWith('/session/');
const updateSW = registerSW({
  immediate: true,
  onNeedRefresh() {
    if (inSitting()) { pendingUpdate = true; return; }
    void updateSW(true);
  },
  onRegisteredSW(_url, reg) {
    if (!reg) return;
    setInterval(() => void reg.update(), 30 * 60 * 1000);
    setInterval(() => { if (pendingUpdate && !inSitting()) { pendingUpdate = false; void updateSW(true); } }, 5000);
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
