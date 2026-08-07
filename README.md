# virtual-tryon-desktop

A local desktop GUI for real-time virtual try-on. Point your webcam at yourself, upload a garment image, and see it on you live. No browser, no extension, no web store.

Built on [Decart's](https://platform.decart.ai) `lucy-vton` realtime model via the Python SDK.

> Personal tool. Not affiliated with or endorsed by Decart.AI, Inc.

## How it works

The model is not local. Camera frames stream over WebRTC to Decart's GPUs, get transformed frame by frame, and stream back.

```
 webcam ──▶ BGR→RGB24 ──▶ LiveKit VideoSource ──┐
                                                 ├──▶ lucy-vton ──▶ edited stream ──▶ Qt window
 garment image + prompt ──▶ set_image() ─────────┘
```

Unlike image-based try-on models (CatVTON, IDM-VTON), this doesn't warp the real garment onto you. It *regenerates* each frame with the garment as conditioning, preserving your motion and body shape. Fit and fine detail are inferred, not measured — useful for "does this silhouette and colour suit me", useless for "will the sleeves be too long".

## Measured, not assumed

Verified against the live API on 2026-08-07 (Apple M2, 16 GB):

| | |
|---|---|
| Model | `lucy-vton-latest` → `1088×624 @ 30 fps` |
| Connect time | 2.8–3.8 s |
| Return frame rate | **~17 fps** observed, below the model's nominal 30 |
| Frames in a 12 s run | 175, none dropped to black after startup |

The first remote frame arrives black. That's stream startup, not a bug.

## Stack

| Piece | Choice |
|---|---|
| GUI | PySide6 6.11 |
| Realtime transport | `decart[realtime]` 0.1.4 → LiveKit 1.1 |
| Camera | OpenCV `VideoCapture` |
| Python | 3.10+ (developed on 3.14) |

## Cost

Decart bills realtime by **active generation time**, not wall clock.

| | Rate |
|---|---|
| `lucy-vton` realtime | **$0.02 / sec** = $1.20 / min |

Leaving a session open is the expensive failure mode, so the app has two guards, both configurable:

```toml
[session]
idle_timeout_sec = 60        # disconnect after N seconds with no interaction
max_session_cost_usd = 2.00  # hard stop; 0 disables
```

The status bar shows a live timer and running cost, and warns during the last 15 seconds before an idle disconnect. The local camera preview runs **before** you connect and costs nothing, so you can frame yourself for free.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.local.toml
```

Add your API key to `config.local.toml`. Get one at [platform.decart.ai](https://platform.decart.ai); new accounts come with free credits.

`config.local.toml` is gitignored. Do not commit your key.

## Run

```bash
python run.py
```

1. **Upload garment image** — any product photo, PNG/JPG/WebP
2. **Describe it** — prompts work best starting with `Substitute` or `Add`, e.g. *"Substitute the current top with a navy blue wool blazer over a white shirt"*
3. **Connect** — billing starts here
4. **Apply outfit** — swaps the garment mid-session without reconnecting

A garment image *plus* a short description works noticeably better than either alone.

## Layout

```
app/
├── config.py     # TOML loading, pricing constant, base URL
├── camera.py     # QThread webcam capture, aspect-correct crop, BGR→RGB24
├── realtime.py   # Decart session on a private asyncio loop + thread
├── ui.py         # Qt window, cost meter, idle guard
└── __main__.py   # entry point
```

The SDK is asyncio and Qt is not, so `realtime.py` owns a private event loop on its own thread. Inbound crossings use Qt signals; outbound use `call_soon_threadsafe` / `run_coroutine_threadsafe`.

## Gotchas worth knowing

- **Camera permission (macOS)** is granted to the *launching* process. Run from Terminal and Terminal gets the prompt. Packaging into an unsigned `.app` later means re-granting, and may be blocked outright — develop from the terminal first.
- **Frame format**: LiveKit wants RGB24, OpenCV gives BGR. Miss the conversion and everything is blue.
- **Aspect ratio**: the model frame is ~1.74:1, a webcam is usually 16:9. `camera.fit_to()` center-crops before resizing so you aren't judging a squashed version of yourself.
- **Buffer reuse**: remote frames must be `.copy()`d out of the LiveKit buffer or they get overwritten mid-render.

## License

MIT
