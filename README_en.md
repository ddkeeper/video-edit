# video-edit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

<div align="center">

[中文](./README.md) | **English**

</div>

Transcript-driven video editing SKILL: feed it a spoken lecture video and it cleans up false starts, stutters, and duplicate takes into a tidy final cut.

[Installation](#installation--quick-start) · [How it works](#how-it-works) · [Editor contract](#editor-contract)

## Why?

- **Semantic/clock decoupling** — the editor model reads only the transcript and makes semantic decisions; scripts handle character-level timestamp mapping and rendering. Swap the model freely.
- **Frame-accurate** — character-level timestamps let it cut mid-sentence stutters precisely, rather than dropping whole sentences.
- **Long-video friendly** — long transcripts are chunked automatically, decisions merged, and the whole video rendered in one pass.
- **GPU-accelerated rendering** — defaults to NVENC, falls back to CPU when unavailable.

## Installation & Quick Start

### Prerequisites

- Python 3.10+, [FFmpeg](https://ffmpeg.org/) (`ffmpeg` + `ffprobe` on `PATH`)
- A DashScope API key (for transcription)

### Quick start (humans)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure the key
cp .env.example .env   # then edit DASHSCOPE_API_KEY

# 3. Process one video (transcribe → edit → map → render)
python helpers/transcribe.py <video> --edit-dir <edit_dir>
# editor model reads the transcript, writes llm_output.json (the only manual/LLM step)
python helpers/map_timestamps.py <edit_dir>/llm_output.json <edit_dir>/raw_timestamps.json
python helpers/render.py <video> <edit_dir>/edl.json -o <edit_dir>/final.mp4
```

### Quick start (AI agents)

> Steps for AI agents, following the pipeline in [`SKILL.md`](SKILL.md).

**Step 1 — Set up**: install dependencies and configure `DASHSCOPE_API_KEY` (if missing, point the user to [Alibaba Cloud Model Studio](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key) to get one).

**Step 2 — Transcribe**: run `transcribe.py` to produce `raw_timestamps.json` + `clean_transcript.txt`.

**Step 3 — Edit**: by default a sub-agent reads the transcript and emits `llm_output.json` (following the contract below); switch to manual only when the user says they want to fill it in. Never ask which mode they want.

**Step 4 — Map & render**: run `map_timestamps.py` to produce the EDL, then `render.py` for the final cut (final by default; add `--preview` only when the user explicitly asks).

## How it works

The editor model (LLM) stays strictly decoupled from timestamps: it reads only the transcript and makes semantic decisions, while scripts handle character-level timestamp mapping and rendering.

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

## Editor contract

The editor model receives only transcript lines and returns a raw JSON array `[{"id": N, "keep": "exact source substring"}]`. Three rules:

- `keep` must be an **exact, contiguous substring** of the source line for that `id` — do not "fix" ASR errors, punctuation, spacing, or casing.
- An `id` absent from the array is **removed entirely**.
- Multiple entries with the same `id` = one **interior deletion**, in source order. Never merge the kept parts back into one object.

All 7 rules, long-transcript chunking, encoding defaults, and the editor prompt live in [`SKILL.md`](SKILL.md). A zero-dependency walkthrough of the data shapes is in [`examples/`](examples/README.md) — no video or API key required.
