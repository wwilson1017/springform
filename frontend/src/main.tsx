import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import Root from './core/Root.tsx';
import { syncThemeColor } from './core/theme/useTheme';

syncThemeColor();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
