import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { RouterProvider } from 'react-router/dom';
import { router } from './app/router';
import { Providers } from './app/providers';

import { restoreSession } from './features/auth/api';
import { registerPwa } from './features/push';
window.addEventListener('cv:session-expired', (event) => {
  void router.navigate((event as CustomEvent<string>).detail, {
    replace: true,
  });
});
registerPwa();
void restoreSession();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
