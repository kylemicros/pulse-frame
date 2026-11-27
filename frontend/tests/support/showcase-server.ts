import { existsSync, readFileSync, statSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export const SHOWCASE_ROOT = fileURLToPath(new URL('../../../showcase', import.meta.url));

export const HEADERS_FILE = join(SHOWCASE_ROOT, '_headers');

export const REPO_URL = 'https://github.com/kylemicros/pulse-frame';

const LOCAL_ORIGIN = 'http://127.0.0.1';

export const SHOWCASE_POLICY: Record<string, string[]> = {
  'default-src': ["'none'"],
  'style-src': ["'self'"],
  'img-src': ["'self'"],
  'frame-ancestors': ["'none'"],
  'base-uri': ["'none'"],
  'form-action': ["'none'"],
};

export const SHOWCASE_HEADERS: Record<string, string> = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'no-referrer',
  'permissions-policy': 'camera=(), microphone=(), geolocation=()',
};

const CONTENT_TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
};

export class ShowcaseHeadersMissing extends Error {
  constructor() {
    super(`SHOWCASE_HEADERS_MISSING: ${HEADERS_FILE} does not exist, so the page cannot be served under its policy`);
  }
}

export function headersForAllPaths(): Record<string, string> {
  if (!existsSync(HEADERS_FILE)) {
    throw new ShowcaseHeadersMissing();
  }
  const headers: Record<string, string> = {};
  let inAllPaths = false;
  for (const line of readFileSync(HEADERS_FILE, 'utf8').split(/\r?\n/)) {
    if (line.trim() === '' || line.trim().startsWith('#')) {
      continue;
    }
    if (!/^\s/.test(line)) {
      inAllPaths = line.trim() === '/*';
      continue;
    }
    const colon = line.indexOf(':');
    if (inAllPaths && colon > 0) {
      headers[line.slice(0, colon).trim().toLowerCase()] = line.slice(colon + 1).trim();
    }
  }
  return headers;
}

function decodedPath(pathname: string): string | null {
  try {
    return decodeURIComponent(pathname === '/' ? '/index.html' : pathname);
  } catch (error) {
    if (error instanceof URIError) {
      return null;
    }
    throw error;
  }
}

function fileFor(relative: string): string | null {
  const file = resolve(SHOWCASE_ROOT, `.${relative}`);
  const inside = file.startsWith(`${SHOWCASE_ROOT}${SHOWCASE_ROOT.endsWith(sep) ? '' : sep}`);
  const hidden = relative.split('/').some((segment) => segment.startsWith('_') || segment.startsWith('.'));
  if (!inside || hidden || !existsSync(file) || !statSync(file).isFile()) {
    return null;
  }
  return file;
}

export type ShowcaseServer = { url: string; origin: string; close: () => Promise<void> };

export async function startShowcaseServer(): Promise<ShowcaseServer> {
  const server: Server = createServer((request, response) => {
    const pathname = new URL(request.url ?? '/', LOCAL_ORIGIN).pathname;
    let headers: Record<string, string>;
    try {
      headers = headersForAllPaths();
    } catch (error) {
      response.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' });
      response.end(error instanceof Error ? error.message : 'SHOWCASE_HEADERS_UNREADABLE');
      return;
    }
    const relative = decodedPath(pathname);
    if (relative === null) {
      response.writeHead(400, { ...headers, 'content-type': 'text/plain; charset=utf-8' });
      response.end(`SHOWCASE_BAD_PATH: ${pathname} holds a malformed percent escape`);
      return;
    }
    const file = fileFor(relative);
    if (file === null) {
      response.writeHead(404, { ...headers, 'content-type': 'text/plain; charset=utf-8' });
      response.end(`SHOWCASE_FILE_NOT_FOUND: ${pathname} is not in the showcase folder`);
      return;
    }
    response.writeHead(200, {
      ...headers,
      'content-type': CONTENT_TYPES[extname(file)] ?? 'application/octet-stream',
    });
    response.end(readFileSync(file));
  });
  await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
  const address = new URL(LOCAL_ORIGIN);
  address.port = String((server.address() as AddressInfo).port);
  return {
    url: address.href,
    origin: address.origin,
    close: () => new Promise<void>((done) => server.close(() => done())),
  };
}
