import type { EventIn, Form, FormSummary, Keystroke, SessionOut, TakeOut, UploadStatus } from '../types';

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

const BASE = '/api';

async function req<T>(method: string, path: string, body?: unknown, raw?: BodyInit): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined = raw;
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  } else if (raw !== undefined) {
    headers['Content-Type'] = 'application/octet-stream';
  }
  const res = await fetch(BASE + path, { method, headers, body: payload, credentials: 'same-origin' });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON */
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail ?? data;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export interface UploadApi {
  uploadStatus(takeId: string): Promise<UploadStatus>;
  putChunk(takeId: string, index: number, chunk: ArrayBuffer): Promise<void>;
  finalize(takeId: string, sha256: string, chunkCount: number, quality: unknown): Promise<TakeOut>;
}

export const api = {
  me: () => req<{ email: string; env: string; role: string }>('GET', '/me'),
  listForms: () => req<FormSummary[]>('GET', '/forms'),
  getForm: (id: string) => req<Form>('GET', `/forms/${encodeURIComponent(id)}`),
  listSessions: () => req<SessionOut[]>('GET', '/sessions'),
  getSession: (id: string) => req<SessionOut>('GET', `/sessions/${id}`),
  createSession: (form_id: string, setup: Record<string, unknown>, client: Record<string, unknown>) =>
    req<SessionOut>('POST', '/sessions', { form_id, setup, client }),
  patchSession: (id: string, patch: { status?: string; setup?: Record<string, unknown> }) =>
    req<SessionOut>('PATCH', `/sessions/${id}`, patch),
  createTake: (
    sessionId: string,
    body: { task_id: string; item_id: string; attempt: number; kind: 'audio' | 'typed'; sample_rate?: number; channels?: number; total_bytes?: number },
  ) => req<TakeOut>('POST', `/sessions/${sessionId}/takes`, body),
  getTake: (id: string) => req<TakeOut>('GET', `/takes/${id}`),
  uploadStatus: (takeId: string) => req<UploadStatus>('GET', `/takes/${takeId}/upload-status`),
  putChunk: async (takeId: string, index: number, chunk: ArrayBuffer) => {
    await req<unknown>('PUT', `/takes/${takeId}/chunks/${index}`, undefined, chunk);
  },
  finalize: (takeId: string, sha256: string, chunkCount: number, quality: unknown) =>
    req<TakeOut>('POST', `/takes/${takeId}/finalize`, { sha256, chunk_count: chunkCount, quality }),
  submitTyped: (takeId: string, text: string, keystrokes: Keystroke[]) =>
    req<TakeOut>('POST', `/takes/${takeId}/typed`, { text, keystrokes }),
  postEvents: (takeId: string, events: EventIn[]) => req<void>('POST', `/takes/${takeId}/events`, events),
  dashboard: (subject: 'learner' | 'me' = 'learner') => req<import('../pages/dash').DashboardData>('GET', `/dashboard?subject=${subject}`),
  exportSession: (id: string) => req<Record<string, unknown>>('GET', `/sessions/${id}/export`),
  takeViewer: (takeId: string) => req<any>('GET', `/takes/${takeId}/viewer`), // eslint-disable-line @typescript-eslint/no-explicit-any
};
