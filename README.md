# pulse-frame

A webcam heart-rate monitor. Your browser sends face frames to a small backend on your own machine, and the page shows your pulse in beats per minute, a live pulse trace and how good the signal is. It works by remote photoplethysmography (rPPG): each heartbeat changes the colour of your skin a tiny bit, and the backend reads that change from your forehead and cheeks.

Nothing leaves your machine on macOS. The backend listens on 127.0.0.1 only, frames live in memory while they are read, and nothing is saved. On macOS the server also wraps itself in a network sandbox, so nothing it loads can phone home. Linux has no such sandbox yet; see Known limitations.

## Run it

You need [uv](https://docs.astral.sh/uv/) for the backend and Node 24 with pnpm 10 for the page.

```
cd backend
uv sync --locked
uv run python -m pulse_frame.vision.model   # once: downloads the face model
uv run python -m pulse_frame.stream         # ws://127.0.0.1:8000/ws/stream
```

In a second terminal:

```
cd frontend
pnpm install --frozen-lockfile
pnpm build && pnpm preview                  # http://127.0.0.1:4173
```

That is the normal way to run the page: the content security policy lives on the built page only. For development, `pnpm dev` serves http://127.0.0.1:5173 with hot reload and no policy.

Open the page, press Start, allow the camera and sit still. The first number shows after about 20 seconds. Looking away or moving a lot resets the count.

## Light matters

**Daylight works; an evening lamp does not.** In daylight from a window the reading settles and tracks well. Under a warm evening lamp the pulse is too faint for the camera to pick up, and the page shows a dash with a hint that more light helps. Better readings under lamp light are planned work, not something this version does.

## Known limitations

- **MediaPipe usage logging on Linux.** MediaPipe, which finds the face, ships a usage logging client that can send usage statistics to Google, with no switch to turn it off. The privacy promise holds on macOS, where the server applies a loopback-only network sandbox at startup and the usage log goes nowhere. Linux has no such sandbox, so MediaPipe may send its usage log on any Linux run, CI included. This exception is retired once Linux runs without network access.
- One browser tab at a time: the backend takes one connection, and a second tab waits until the first lets go.
- Heart rate only, from a still face in good light. It is a side project, not a medical device.
