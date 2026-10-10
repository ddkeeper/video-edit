# video-edit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-green.svg)](https://ffmpeg.org/)

<div align="center">

[中文](./README.md) | **English**

</div>

Transcript-driven video editing SKILL: feed it a spoken lecture video and it cleans up false starts, stutters, and duplicate takes into a tidy final cut.

[Installation & Quick Start](#installation--quick-start) · [How it works](#how-it-works) · [Editing requirements](#editing-requirements)

## Why?

- **Visual/text separation**: the LLM makes semantic decisions on the transcript and produces edit decisions; scripts handle character-level timestamp mapping and rendering.
- **Precise cuts**: character-level timestamps let it cut mid-sentence stutters precisely; unkept speech and pauses are dropped naturally.
- **Long-video chunking**: long transcripts are chunked automatically, decisions merged, and the whole video rendered in one pass, with no length limit.
- **GPU-accelerated rendering**: defaults to NVENC; an 11-minute final cut renders in about 2 minutes (measured on an RTX 3060 Laptop); the foreground stays responsive during rendering (falls back to CPU without a GPU).

## Suitable / not suitable

- **Suitable for**: videos driven by text-and-speech logic — lectures, course recordings, exam-prep explainers, tech talks.
- **Not suitable for**: videos driven by visual logic — camera-movement showcases, dance/sports tutorials, visual narratives without speech.

## Installation & Quick Start

### Quick start (humans)

1. Install:

```bash
cd <your project dir>
mkdir -p .agent/skill
cd .agent/skill
git clone https://github.com/ddkeeper/video-edit.git
```

2. Enter a prompt in your Agent to edit a video with the installed skill, e.g.:

> Use the video-edit skill at `/path/to/video-edit` to edit this video for me.

### Quick start (AI agents)

> For AI agents: use git to install this repo into the current project's skills directory.

```bash
git clone https://github.com/ddkeeper/video-edit.git <skills_dir>/video-edit
```

`SKILL.md` is the skill entry point and takes effect once loaded; then follow the pipeline in [`SKILL.md`](SKILL.md).

### Note

Transcription relies on a cloud speech-recognition model and needs an API key ([Get & Configure API Key - Alibaba Cloud Model Studio](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key?spm=5176.28197581.0.0.321674a1pKNTN2)). In practice the Agent handles this via the skill; this is just for your awareness.

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
