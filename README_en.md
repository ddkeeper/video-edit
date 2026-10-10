# video-edit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-green.svg)](https://ffmpeg.org/)

<div align="center">

[中文](./README.md) | **English**

</div>

Transcript-driven video editing SKILL: feed it a spoken lecture video and it cleans up false starts, stutters, and duplicate takes into a tidy final cut.

[Installation](#installation) · [How it works](#how-it-works) · [Editing requirements](#editing-requirements)

## Why?

- **Semantic/clock decoupling** — the editor model reads only the transcript and makes semantic decisions; scripts handle character-level timestamp mapping and rendering. Swap the model freely.
- **Frame-accurate** — character-level timestamps let it cut mid-sentence stutters precisely, rather than dropping whole sentences.
- **Long-video friendly** — long transcripts are chunked automatically, decisions merged, and the whole video rendered in one pass.
- **GPU-accelerated rendering** — defaults to NVENC, falls back to CPU when unavailable.

## Installation

> **Installation instructions for AI agents**: this repo is itself a skill. Installing means "put the repo contents into the current environment's skills directory, with `SKILL.md` as the entry point." Complete the following automatically, without bothering the user:

1. Locate the user-level skills directory of your current Agent environment (common locations: `~/.workbuddy/skills/`, `~/.agents/skills/`, `~/.claude/skills/`, etc. — judge by the environment you run in).
2. Create a `video-edit/` directory there and copy all repo files into it (or `git clone` directly into that directory).
3. Verify `video-edit/SKILL.md` exists — it is the skill entry point and takes effect once loaded.

**Dependencies and keys are handled by the Agent on first use**: if `dashscope` is missing, `pip install` it; if `ffmpeg` is missing, prompt to install; if `DASHSCOPE_API_KEY` is missing, guide the user to [Alibaba Cloud Model Studio](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key) and write it to `.env`. Do not treat these as installation prerequisites.

Once installed, the user just says "edit this video for me" — the Agent runs the full transcribe → decide → map → render pipeline per [`SKILL.md`](SKILL.md).

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

## Editing requirements

The editor model receives only transcript lines and returns a raw JSON array `[{"id": N, "keep": "exact source substring"}]`. Core rules:

- `keep` must be an **exact, contiguous substring** of the source line for that `id` — do not "fix" ASR errors, punctuation, spacing, or casing.
- An `id` absent from the array is **removed entirely**.
- Multiple entries with the same `id` = one **interior deletion**, in source order — never merge the kept parts back into one object.

All 7 rules (preserving technical connectives, latest-take policy, sub-sentence cuts, etc.) live in the `Editor Prompt` of [`SKILL.md`](SKILL.md).

> **Switching use cases**: this SKILL defaults to spoken lectures. To target another domain (interviews, meeting-note editing, etc.), just edit the `RULES` and examples in the `Editor Prompt` of [`SKILL.md`](SKILL.md) — the rest of the pipeline (transcribe, map, render) stays unchanged.

A zero-dependency walkthrough of the data shapes is in [`examples/`](examples/README.md) — no video or API key required.
