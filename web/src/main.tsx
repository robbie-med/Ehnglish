import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import './i18n';
import './index.css';
import App from './App';
import { registerSW } from 'virtual:pwa-register';

// Take new builds immediately (Safari/iPad otherwise keeps the old worker until every tab is closed),
// and poll for a new worker every 30 minutes while the app is open.
const updateSW = registerSW({
  immediate: true,
  onNeedRefresh() { void updateSW(true); },
  onRegisteredSW(_url, reg) {
    if (!reg) return;
    setInterval(() => void reg.update(), 30 * 60 * 1000);
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
