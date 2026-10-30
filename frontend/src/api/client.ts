import type { CascadeRequest, CascadeResult, CaseStudy, CaseStudySummary, CatalogMeta, CatalogObject, Conjunction, ConjunctionDetail, NegotiationEvent } from './types';
export const isMockMode = import.meta.env.VITE_USE_MOCKS !== 'false';
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
export const apiUrl = (path: string) => `${baseUrl}${path}`;
export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'ApiError'; }
}
async function checkedFetch(path: string, options?: RequestInit): Promise<Response> {
  const response = await fetch(apiUrl(path), options);
  if (!response.ok) {
    let message = `Request failed (${response.status}). Please try again.`;
    try { const body = await response.json() as { message?: string; detail?: string }; message = body.message ?? body.detail ?? message; } catch { /* Keep a useful fallback for non-JSON gateways. */ }
    throw new ApiError(message, response.status);
  }
  return response;
}
async function json<T>(path: string, options?: RequestInit): Promise<T> {
  return (await checkedFetch(path, options)).json() as Promise<T>;
}
const post = (body: unknown, signal?: AbortSignal): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
/** Incremental SSE parser supports chunk splits, CRLF, comments and multi-line data events. */
export function createSseParser(onData: (data: string) => void) {
  let buffer = '';
  return {
    push(chunk: string) {
      buffer += chunk;
      if (buffer.length > 1048576) throw new Error('Stream event exceeds the supported size.');
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const event = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const data = event.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).replace(/^ /, '')).join('\n');
        if (data) onData(data);
      }
    },
    finish() { if (buffer.trim()) this.push('\n\n'); },
  };
}
async function stream(path: string, options: RequestInit, onData: (data: string) => void): Promise<void> {
  const response = await checkedFetch(path, options);
  if (!response.body) throw new Error('The server returned an empty stream. Please retry.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let doneEvent = false;
  const parser = createSseParser((data) => { if (data === '[DONE]') doneEvent = true; else onData(data); });
  try {
    while (!doneEvent) {
      const { value, done } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    parser.push(decoder.decode());
    parser.finish();
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}
export const api = {
  catalog: (signal?: AbortSignal) => json<CatalogObject[]>('/api/catalog', { signal }),
  catalogMeta: (signal?: AbortSignal) => json<CatalogMeta>('/api/catalog/meta', { signal }),
  conjunctions: (signal?: AbortSignal) => json<Conjunction[]>('/api/conjunctions?days=7&minPc=1e-6', { signal }),
  conjunction: (id: string, signal?: AbortSignal) => json<ConjunctionDetail>(`/api/conjunctions/${encodeURIComponent(id)}`, { signal }),
  startNegotiation: (conjunctionId: string, signal?: AbortSignal) => json<{ negotiationId: string }>('/api/negotiations', post({ conjunctionId }, signal)),
  streamNegotiation: (id: string, onEvent: (event: NegotiationEvent) => void, signal?: AbortSignal) => stream(`/api/negotiations/${encodeURIComponent(id)}/stream`, { signal, headers: { Accept: 'text/event-stream' } }, (data) => {
    const event = JSON.parse(data) as NegotiationEvent;
    if (!event || typeof event.type !== 'string') throw new Error('Received an invalid negotiation event.');
    onEvent(event);
  }),
  cascade: (request: CascadeRequest, signal?: AbortSignal) => json<CascadeResult>('/api/cascade', post(request, signal)),
  caseStudies: (signal?: AbortSignal) => json<CaseStudySummary[]>('/api/case-studies', { signal }),
  caseStudy: (id: string, signal?: AbortSignal) => json<CaseStudy>(`/api/case-studies/${encodeURIComponent(id)}`, { signal }),
  ask: (question: string, onToken: (token: string) => void, signal?: AbortSignal) => stream('/api/ask', { ...post({ question }, signal), headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' } }, (data) => {
    try {
      const token = JSON.parse(data) as string | { type?: string; text?: string; token?: string; message?: string };
      if (typeof token === 'string') onToken(token);
      else if (token.type === 'error') throw new ApiError(token.message ?? 'Sentinel could not answer this question.', 502);
      else if (token.text ?? token.token) onToken(token.text ?? token.token ?? '');
    } catch (error) { if (error instanceof SyntaxError) onToken(data); else throw error; }
  }),
};
