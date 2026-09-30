import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UploadApi } from '../api/client';
import type { TakeOut, UploadStatus } from '../types';
import { enqueueUpload, pendingCount, processQueue, splitChunks } from './queue';

function fakeApi(opts: { failPutOnce?: boolean; alreadyFinal?: boolean } = {}) {
  const received = new Map<string, Set<number>>();
  let failed = false;
  const finalized: string[] = [];
  const api: UploadApi = {
    uploadStatus: vi.fn(async (takeId: string): Promise<UploadStatus> => ({
      take_id: takeId,
      status: opts.alreadyFinal ? 'finalized' : 'uploading',
      received: Array.from(received.get(takeId) ?? []),
    })),
    putChunk: vi.fn(async (takeId: string, index: number) => {
      if (opts.failPutOnce && !failed) { failed = true; throw new Error('network'); }
      if (!received.has(takeId)) received.set(takeId, new Set());
      received.get(takeId)!.add(index);
    }),
    finalize: vi.fn(async (takeId: string) => { finalized.push(takeId); return { id: takeId, status: 'finalized' } as TakeOut; }),
  };
  return { api, received, finalized };
}

describe('upload queue', () => {
  beforeEach(async () => {
    // fresh DB per test
    indexedDB.deleteDatabase('ehnglish-uploads');
  });

  it('splits into chunks', () => {
    const parts = splitChunks(new ArrayBuffer(2_500_000), 1_000_000);
    expect(parts.map((p) => p.byteLength)).toEqual([1_000_000, 1_000_000, 500_000]);
  });

  it('uploads all chunks and finalizes', async () => {
    const { api, finalized } = fakeApi();
    const id = 'take-' + Math.random();
    await enqueueUpload(id, 'sess', new ArrayBuffer(2_500_000), 'a'.repeat(64), { ok: true });
    expect(await pendingCount()).toBeGreaterThan(0);
    await processQueue(api);
    expect(api.putChunk).toHaveBeenCalledTimes(3);
    expect(finalized).toContain(id);
    expect(await pendingCount()).toBe(0);
  });

  it('keeps the item and resumes after a failure', async () => {
    const { api, finalized } = fakeApi({ failPutOnce: true });
    const id = 'take-' + Math.random();
    await enqueueUpload(id, 'sess', new ArrayBuffer(2_500_000), 'b'.repeat(64), null);
    await processQueue(api);
    expect(finalized).not.toContain(id);
    expect(await pendingCount()).toBe(1);
    await processQueue(api); // retry: only the missing chunks are re-sent
    expect(finalized).toContain(id);
    expect(api.putChunk).toHaveBeenCalledTimes(1 + 3);
    expect(await pendingCount()).toBe(0);
  });

  it('drops items the server already finalized', async () => {
    const { api } = fakeApi({ alreadyFinal: true });
    await enqueueUpload('take-' + Math.random(), 'sess', new ArrayBuffer(10), 'c'.repeat(64), null);
    await processQueue(api);
    expect(api.putChunk).not.toHaveBeenCalled();
    expect(await pendingCount()).toBe(0);
  });
});
