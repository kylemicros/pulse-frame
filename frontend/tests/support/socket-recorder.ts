import type { Page } from '@playwright/test';

export const STREAM_URL = 'ws://127.0.0.1:8000/ws/stream';

type SocketMessage = { at: number; text: string };

type SocketRecord = {
  url: string;
  createdAt: number;
  openedAt: number | null;
  closedAt: number | null;
  closeCode: number | null;
  messages: SocketMessage[];
};

type RecorderWindow = Window & { socketRecords: SocketRecord[] };

export async function recordSockets(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const records: SocketRecord[] = [];
    Object.defineProperty(window, 'socketRecords', { value: records });
    const wrap = (Base: typeof WebSocket): typeof WebSocket =>
      class RecordedSocket extends Base {
        constructor(url: string | URL, protocols?: string | string[]) {
          super(url, protocols);
          const record: SocketRecord = {
            url: String(url),
            createdAt: performance.now(),
            openedAt: null,
            closedAt: null,
            closeCode: null,
            messages: [],
          };
          records.push(record);
          this.addEventListener('open', () => {
            record.openedAt = performance.now();
          });
          this.addEventListener('close', (event) => {
            record.closedAt = performance.now();
            record.closeCode = event.code;
          });
          this.addEventListener('message', (event) => {
            if (typeof event.data === 'string') {
              record.messages.push({ at: performance.now(), text: event.data });
            }
          });
        }
      };
    let current = wrap(window.WebSocket);
    Object.defineProperty(window, 'WebSocket', {
      configurable: true,
      get: () => current,
      set: (value: typeof WebSocket) => {
        current = wrap(value);
      },
    });
  });
}

export function socketRecords(page: Page): Promise<SocketRecord[]> {
  return page.evaluate(
    (url) => (window as unknown as RecorderWindow).socketRecords.filter((record) => record.url === url),
    STREAM_URL,
  );
}

export function retryGaps(records: SocketRecord[]): number[] {
  return records.slice(1).map((record, index) => record.createdAt - (records[index].closedAt ?? Number.NaN));
}

function parsed(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function firstMessageAfter(
  records: SocketRecord[],
  since: number,
  matches: (message: Record<string, unknown>) => boolean,
): SocketMessage | null {
  for (const record of records) {
    for (const message of record.messages) {
      const fields = parsed(message.text);
      if (message.at >= since && fields !== null && matches(fields)) {
        return message;
      }
    }
  }
  return null;
}
