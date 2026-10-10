# video-edit

<div align="center">

[中文](./README.md) | **English**

</div>

Transcript-driven precision video editing: **the model makes semantic decisions, deterministic scripts handle frame-accurate timestamp mapping and rendering — the two stay strictly decoupled**. Feed it a spoken lecture video and it cleans up false starts, stutters, and duplicate takes into a tidy final cut.

## Core idea

- The editor model **never sees timestamps**, only `[ID: N]` transcript lines.
- It returns a JSON decision of `{"id": N, "keep": "exact source substring"}` — purely semantic, no clock-touching.
- Scripts map those decisions to character-level timestamps, produce millisecond cut points (EDL), and render with NVENC.

This lets you swap the editor model freely, and the mapping step **fails loudly** instead of silently misaligning audio.

## Four-stage pipeline

```
source video ──transcribe──▶ timestamped transcript
                                │
                                ▼
                   editor model emits {id, keep} decisions
                                │
                                ▼
            map_timestamps ──▶ EDL (millisecond cut points)
                                │
                                ▼
                   render ──▶ final cut
```

## Quick start

### 1. Prerequisites

- Python 3.10+, [FFmpeg](https://ffmpeg.org/) (`ffmpeg` + `ffprobe` on `PATH`)
- A DashScope API key (for transcription)

```bash
pip install -r requirements.txt
```

### 2. Configure the key

Copy `.env.example` to `.env` and fill in `DASHSCOPE_API_KEY`.

### 3. Run the pipeline

```bash
# 1. Transcribe (writes raw_timestamps.json + clean_transcript.txt)
python helpers/transcribe.py <video> --edit-dir <edit_dir>

# 2. Editor model reads the transcript, writes llm_output.json (the only model step)

# 3. Map decisions to millisecond timestamps
python helpers/map_timestamps.py <edit_dir>/llm_output.json <edit_dir>/raw_timestamps.json

# 4. Render (NVENC when available, CPU fallback)
python helpers/render.py <video> <edit_dir>/edl.json -o <edit_dir>/final.mp4
```

A zero-dependency walkthrough of the data shapes lives in [`examples/`](examples/README.md) — no video or API key required.

## Editor contract

The editor model receives only transcript lines and returns a raw JSON array:

```json
[
  {"id": 19, "keep": "exact source text"},
  {"id": 19, "keep": "another exact fragment"}
]
```

Three rules:

- `keep` must be an **exact, contiguous substring** of the source line for that `id` — do not "fix" ASR errors, punctuation, spacing, or casing.
- An `id` absent from the array is **removed entirely**.
- Multiple entries with the same `id` = one **interior deletion**, in source order. To cut disfluencies mid-line, emit **separate objects with the same `id`** — never merge the kept parts back into one object, or the middle cut is lost (worked example in Rule 6 of [`SKILL.md`](SKILL.md)).

## Full spec

All 7 editing rules, long-transcript chunking, encoding defaults, and the editor prompt live in [`SKILL.md`](SKILL.md).
