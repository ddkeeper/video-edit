# video-edit

<div align="center">

[中文](./README.md) | **English**

</div>

Transcript-driven video editing: feed it a spoken lecture video and it cleans up false starts, stutters, and duplicate takes into a tidy final cut.

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

## Getting started

1. Configure `DASHSCOPE_API_KEY` (for transcription) and install the dependencies.
2. Follow the pipeline in [`SKILL.md`](SKILL.md) to process one video: transcribe → editor model emits decisions → map → render.
3. The edit contract (`keep` must be an exact source substring, omitted `id`s are removed entirely, interior cuts use multiple same-`id` entries) and all 7 rules live in [`SKILL.md`](SKILL.md).

A zero-dependency walkthrough of the data shapes lives in [`examples/`](examples/README.md) — no video or API key required.
