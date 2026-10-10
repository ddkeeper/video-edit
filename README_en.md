# video-edit

<div align="center">

[中文](./README.md) | **English**

</div>

**Transcript-driven precision video editing** — turn a spoken video into a
clean cut, with the model making semantic decisions and deterministic scripts
handling timestamps and rendering.

## What it does

Given a source video, `video-edit` produces an edited video in four stages:

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
                   render ──▶ final cut (preview / final)
```

The key design decision is the **contract**: the editor model never sees
timestamps, only `[ID: N]` transcript lines. It returns a JSON array of
`{"id": N, "keep": "exact substring"}` fragments. This keeps the model's job
purely semantic while the scripts guarantee frame-accurate cuts.

## Why this shape?

| Concern | Where it lives | Why |
| --- | --- | --- |
| What to cut / keep | editor model (LLM) | Semantic judgement, hard to script |
| Millisecond mapping | `map_timestamps.py` | Deterministic, needs exactness |
| Encoding / rendering | `render.py` | Tuned for lecture screencasts |

Separating them means you can swap the editor model freely, and the mapping
step fails loudly instead of silently misaligning audio.

## Quick start

### 1. Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe` on `PATH`)
- A DashScope API key (for transcription)

```bash
pip install -r requirements.txt
```

### 2. Configure the key

Copy `.env.example` to `.env` and fill in your key:

```bash
cp .env.example .env   # then edit DASHSCOPE_API_KEY
```

The key is read from (in order): the `DASHSCOPE_API_KEY` environment variable,
`video-edit/.env`, the project `.env`, or `~/.codex/video-edit.env`.

### 3. Run the pipeline

```bash
# 1. Transcribe (writes raw_timestamps.json + clean_transcript.txt)
python helpers/transcribe.py <video> --edit-dir <edit_dir>

# 2. Have the editor model read the transcript and write llm_output.json
#    (see "Editor contract" below; this is the only manual/LLM step)

# 3. Map decisions to millisecond timestamps
python helpers/map_timestamps.py <edit_dir>/llm_output.json <edit_dir>/raw_timestamps.json

# 4. Render (NVENC when available, CPU fallback)
python helpers/render.py <video> <edit_dir>/edl.json -o <edit_dir>/final.mp4
```

A zero-dependency walkthrough of the data shapes lives in
[`examples/`](examples/README.md) — no video or API key required.

## Editor contract

The editor model (LLM) receives only transcript lines and returns a raw JSON
array:

```json
[
  {"id": 19, "keep": "exact source text"},
  {"id": 19, "keep": "another exact fragment"}
]
```

Rules:

- `keep` must be an **exact, contiguous substring** of the source line for
  that `id`. Do not "fix" ASR errors, punctuation, spacing, or casing.
- An `id` absent from the array is removed entirely.
- Multiple entries with the same `id` allow an interior deletion, in source
  order. To remove disfluencies in the middle of a line, emit **separate
  objects with the same `id`** — never merge the kept parts back into one
  object, or the middle cut is lost. (See Rule 6 in
  [`SKILL.md`](SKILL.md) for a worked example.)

## Encoding defaults

Tuned for long, low-motion lecture screencasts:

| Flag | Default | Notes |
| --- | --- | --- |
| `--encoder` | `auto` | NVENC when available, else CPU |
| `--workers` | `2` | Two segments encoded in parallel |
| `--nvenc-preset` | `p5` final / `p4` preview | p5 ≈ 1.45× faster than p7, no visible loss |
| `--priority` | `below` | Keeps the desktop responsive (Windows) |

See [`SKILL.md`](SKILL.md) for the full fallback table and measured benchmarks.

## Repository layout

```
video-edit/
├── SKILL.md              # full skill specification, rules & editor prompt
├── helpers/
│   ├── transcribe.py     # DashScope ASR → character-level timestamps
│   ├── map_timestamps.py # {id,keep} decisions → millisecond EDL (core)
│   └── render.py         # EDL → preview/final via NVENC or CPU
├── examples/             # minimal self-contained pipeline demo
├── requirements.txt
└── .env.example
```

## License

[MIT](LICENSE)
