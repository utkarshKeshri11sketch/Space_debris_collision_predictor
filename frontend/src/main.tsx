import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import '@fontsource/archivo/600.css';
import '@fontsource/archivo/400.css';
import '@fontsource/archivo/500.css';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-mono/400.css';
import './styles/tokens.css';
import './styles/global.css';
import App from './app/App';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 60_000, refetchOnWindowFocus: false } },
});
async function bootstrap() {
  if (import.meta.env.VITE_USE_MOCKS !== 'false') {
    const { startMocks } = await import('./api/mocks');
    await startMocks();
  }
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}
bootstrap().catch((error: unknown) => {
  document.getElementById('root')!.innerHTML =
    '<main style="padding:10vh;color:#e6eaf2;background:#05070d;font:16px sans-serif"><h1>Mission systems unavailable</h1><p>The application could not start. Reload this page to retry.</p><button onclick="location.reload()">Retry connection</button></main>';
  console.error(error);
});
