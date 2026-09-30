/**
 * Resumable upload queue backed by IndexedDB. A finished take is stored locally first, then
 * pushed chunk by chunk; the server's upload-status endpoint tells us what to resume. Survives
 * reloads and offline stretches. The API is injected so the queue is unit-testable.
 */
import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
import type { UploadApi } from '../api/client';

export const CHUNK_BYTES = 1024 * 1024;

export interface PendingUpload {
  takeId: string;
  sessionId: string;
  createdAt: number;
  chunks: ArrayBuffer[];
  chunkCount: number;
  sha256: string;
  quality: unknown;
  attempts: number;
  lastError?: string;
}

interface Schema extends DBSchema {
  pending: { key: string; value: PendingUpload; indexes: { bySession: string } };
}

let dbp: Promise<IDBPDatabase<Schema>> | null = null;
function db(): Promise<IDBPDatabase<Schema>> {
  if (!dbp) {
    dbp = openDB<Schema>('ehnglish-uploads', 1, {
      upgrade(d) {
        const s = d.createObjectStore('pending', { keyPath: 'takeId' });
        s.createIndex('bySession', 'sessionId');
      },
    });
  }
  return dbp;
}

export function splitChunks(buf: ArrayBuffer, size = CHUNK_BYTES): ArrayBuffer[] {
  const out: ArrayBuffer[] = [];
  for (let off = 0; off < buf.byteLength; off += size) out.push(buf.slice(off, Math.min(off + size, buf.byteLength)));
  return out;
}

type Listener = (pending: number) => void;
const listeners = new Set<Listener>();
export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  void pendingCount().then(fn);
  return () => listeners.delete(fn);
}
async function notify(): Promise<void> {
  const n = await pendingCount();
  for (const fn of listeners) fn(n);
}

export async function pendingCount(): Promise<number> {
  return (await db()).count('pending');
}

export async function pendingForSession(sessionId: string): Promise<number> {
  return (await db()).countFromIndex('pending', 'bySession', sessionId);
}

export async function enqueueUpload(takeId: string, sessionId: string, wav: ArrayBuffer, sha256: string, quality: unknown): Promise<void> {
  const chunks = splitChunks(wav);
  await (await db()).put('pending', { takeId, sessionId, createdAt: Date.now(), chunks, chunkCount: chunks.length, sha256, quality, attempts: 0 });
  await notify();
}

let running: Promise<void> | null = null;

/** Push everything pending, sequentially. Safe to call often; concurrent calls coalesce. */
export function processQueue(api: UploadApi): Promise<void> {
  if (running) return running;
  running = (async () => {
    try {
      const d = await db();
      const items = (await d.getAll('pending')).sort((a, b) => a.createdAt - b.createdAt);
      for (const item of items) {
        try {
          await uploadOne(api, item);
          await d.delete('pending', item.takeId);
        } catch (e) {
          item.attempts += 1;
          item.lastError = e instanceof Error ? e.message : String(e);
          await d.put('pending', item);
        }
        await notify();
      }
    } finally {
      running = null;
    }
  })();
  return running;
}

async function uploadOne(api: UploadApi, item: PendingUpload): Promise<void> {
  const status = await api.uploadStatus(item.takeId);
  if (status.status !== 'uploading') return; // already finalized (or rejected/failed): nothing to do
  const have = new Set(status.received);
  for (let i = 0; i < item.chunkCount; i++) {
    if (have.has(i)) continue;
    await api.putChunk(item.takeId, i, item.chunks[i]);
  }
  await api.finalize(item.takeId, item.sha256, item.chunkCount, item.quality);
}

/** Retry loop: on a timer and whenever the browser comes back online. */
export function startUploader(api: UploadApi, intervalMs = 5000): () => void {
  const tick = () => void processQueue(api);
  const timer = setInterval(tick, intervalMs);
  window.addEventListener('online', tick);
  tick();
  return () => {
    clearInterval(timer);
    window.removeEventListener('online', tick);
  };
}
