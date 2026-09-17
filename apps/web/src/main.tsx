/*
 * Entry point. The font faces and the token layer are imported here, once, so
 * every component below inherits them and no component imports styling of its
 * own beyond its CSS module.
 *
 * Fonts are self-hosted through @fontsource (UX-DR2) — nothing is fetched from
 * a third-party font CDN, which also keeps AD-6 honest: this app talks to
 * apps/api and to nothing else.
 */
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/plus-jakarta-sans/800.css';
import '@fontsource/jetbrains-mono/500.css';
import './styles/tokens.css';
import './styles/global.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';

const container = document.getElementById('root');

if (!container) {
  throw new Error('Root element #root is missing from index.html.');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
