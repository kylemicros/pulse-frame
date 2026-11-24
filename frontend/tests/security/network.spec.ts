import { expect, test } from '@playwright/test';
import { MockBackend, STREAM_URL } from '../support/mock-backend';
import { advanceRun, advanceRunUntil, guidedPage, pushAndConfirm, startRun } from '../support/guided-page';
import { monitorPage, startMonitoring, waitForMoreFrames } from '../support/monitor-page';

const PAGE_ORIGIN = 'http://127.0.0.1:5173';

test.describe('data stays on this machine', () => {
  test('sends frames and readings only to the local backend socket', async ({ page }) => {
    const requests: string[] = [];
    const strayStreams: string[] = [];
    const realSockets: string[] = [];
    page.on('request', (request) => requests.push(request.url()));
    page.on('websocket', (socket) => realSockets.push(socket.url()));
    await page.routeWebSocket(
      (url) => url.href !== STREAM_URL && url.host !== '127.0.0.1:5173',
      (ws) => {
        strayStreams.push(ws.url());
        void ws.close({ code: 1008 });
      },
    );
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await startMonitoring(page, backend);
    backend.pushReading({ bpm: 73.3, quality_db: 9.4, state: 'ok' });
    await expect(monitor.bpmValue).toHaveText(/^(73\.3|73)$/);
    await waitForMoreFrames(backend, 5);
    await monitor.stop.click();
    await expect(monitor.start).toBeVisible();

    expect(backend.connections.length).toBeGreaterThan(0);
    expect(backend.connections.every((connection) => connection.closedAt !== null)).toBe(true);
    expect(strayStreams).toEqual([]);
    expect(realSockets.filter((url) => new URL(url).host !== '127.0.0.1:5173')).toEqual([]);
    expect(
      requests.filter((url) => !url.startsWith(`${PAGE_ORIGIN}/`) && !url.startsWith('data:') && !url.startsWith('blob:')),
    ).toEqual([]);
  });

  test('keeps nothing in browser storage after a session', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await startMonitoring(page, backend);
    backend.pushReading({ bpm: 73.3, quality_db: 9.4, state: 'ok' });
    await expect(monitor.bpmValue).toHaveText(/^(73\.3|73)$/);
    await monitor.stop.click();
    await expect(monitor.start).toBeVisible();

    const stored = await page.evaluate(async () => ({
      local: localStorage.length,
      session: sessionStorage.length,
      databases: (await indexedDB.databases()).length,
    }));
    expect(stored).toEqual({ local: 0, session: 0, databases: 0 });
  });

  test('keeps guided run readings in page memory: no storage writes and nothing sent but frames', async ({ page }) => {
    const requests: string[] = [];
    const sameOriginSends: string[] = [];
    page.on('request', (request) => {
      requests.push(request.url());
      if (request.url().startsWith(`${PAGE_ORIGIN}/`) && request.method() !== 'GET') {
        sameOriginSends.push(`${request.method()} ${request.url()}`);
      }
    });
    await page.addInitScript(() => {
      const writes: string[] = [];
      Object.defineProperty(globalThis, 'storageWrites', { value: writes });
      const setItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function recordSetItem(this: Storage, key: string, value: string) {
        writes.push(`storage:${key}`);
        setItem.call(this, key, value);
      };
      const open = IDBFactory.prototype.open;
      IDBFactory.prototype.open = function recordOpen(this: IDBFactory, name: string, version?: number) {
        writes.push(`indexedDB:${name}`);
        return open.call(this, name, version);
      };
      const cookie = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
      Object.defineProperty(Document.prototype, 'cookie', {
        configurable: true,
        get(this: Document) {
          return cookie?.get?.call(this) ?? '';
        },
        set(this: Document, value: string) {
          writes.push('cookie');
          cookie?.set?.call(this, value);
        },
      });
      const cacheOpen = CacheStorage.prototype.open;
      CacheStorage.prototype.open = function recordCacheOpen(this: CacheStorage, name: string) {
        writes.push(`cache:${name}`);
        return cacheOpen.call(this, name);
      };
    });
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

    await pushAndConfirm(page, backend, { bpm: 69.1, quality_db: 9.3, state: 'ok' });
    await advanceRun(page, backend, 100000);
    await pushAndConfirm(page, backend, { bpm: 68.9, quality_db: 9.3, state: 'ok' });
    await advanceRunUntil(page, backend, guided.startAgain);
    await expect(guided.milestones).toHaveText(/^Done\. Heart rate 69 beats per minute\b/);

    const writes = await page.evaluate(() => [...(globalThis as unknown as { storageWrites: string[] }).storageWrites]);
    const stored = await page.evaluate(async () => ({
      local: localStorage.length,
      session: sessionStorage.length,
      databases: (await indexedDB.databases()).length,
      cookies: document.cookie,
    }));
    expect(writes).toEqual([]);
    expect(stored).toEqual({ local: 0, session: 0, databases: 0, cookies: '' });
    expect(backend.textMessages).toEqual([]);
    expect(sameOriginSends).toEqual([]);
    expect(
      requests.filter((url) => !url.startsWith(`${PAGE_ORIGIN}/`) && !url.startsWith('data:') && !url.startsWith('blob:')),
    ).toEqual([]);
  });
});
