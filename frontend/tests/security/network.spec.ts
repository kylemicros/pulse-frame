import { expect, test } from '@playwright/test';
import { MockBackend, STREAM_URL } from '../support/mock-backend';
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
});
