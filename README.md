# virtual-tryon-desktop

A local desktop GUI for real-time virtual try-on. Point your webcam at yourself, upload a garment image, and see it on you live — no browser, no web store, no upload of anything to a service you don't control except the frames the model needs.

Built on [Decart's](https://platform.decart.ai) `lucy-vton` realtime model via the Python SDK.

> Personal tool. Not affiliated with or endorsed by Decart.AI, Inc.

## Status

🚧 Scaffolding. Nothing runs yet.

## How it works

The model is not local. Your camera frames are streamed over WebRTC to Decart's GPUs, transformed frame-by-frame, and streamed back. Latency is ~40 ms per frame at 768×432/20 fps, which is what makes it feel live rather than rendered.

```
 webcam ──▶ RGB24 frames ──▶ LiveKit VideoSource ──┐
                                                    ├──▶ Decart lucy-vton ──▶ edited stream ──▶ Qt window
 garment image ──▶ SetInput(image=..., prompt=...) ─┘
```

Unlike the image-based try-on models (CatVTON, IDM-VTON), this doesn't warp the real garment onto you — it *regenerates* each frame with the garment as conditioning, preserving your motion and body shape. Fit and fine detail are inferred, not measured.

## Planned stack

| Piece | Choice |
|---|---|
| GUI | PySide6 (Qt) |
| Realtime transport | `decart[realtime]` → LiveKit Python client |
| Camera capture | OpenCV (`cv2.VideoCapture`) |
| Python | 3.10+ |

## Cost

Decart bills realtime by active generation time.

| | Rate |
|---|---|
| `lucy-vton` realtime | **$0.02 / sec** ($1.20 / min) |

The app shows a live session timer and running cost, and disconnects automatically after an idle timeout. Leaving a session open is the expensive failure mode.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.local.toml   # then add your API key
```

Get an API key at [platform.decart.ai](https://platform.decart.ai). New accounts come with free credits.

`config.local.toml` is gitignored. Do not commit your key.

## Known platform gotchas (macOS)

- **Camera permission (TCC)** is granted to the *launching process*. Running from Terminal grants it to Terminal. Packaging into an unsigned `.app` later requires re-granting and may be blocked outright — develop from the terminal first.
- **Frame format**: LiveKit expects RGB24; OpenCV hands you BGR. Convert, or everything is blue.

## License

MIT
