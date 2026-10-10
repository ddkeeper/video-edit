---
name: video-edit
description: High-precision AI video editing skill based on character-level timestamps. Uses DashScope Paraformer-V2 for speech recognition. Separates semantic decision-making (LLM) from physical time mapping (Code). Designed to automatically clean up stutters, false starts, and duplicate takes with exact word-boundary cuts.
---

# Video Edit

## Principle

1. **Semantic separation.** The LLM reads timestamp-free text and makes editorial decisions; the code maps those decisions back to character-level timestamps. The LLM is a semantic engine, not a clock.
2. **Human in the loop.** By default a sub-agent generates `llm_output.json` automatically; the user may take over editing at any point (see The Process, step 3).

## Hard Rules (Physical Correctness)

These prevent silent failures and synchronization disasters. They apply to the scripts, not the editor model.

1. **Never feed timestamps to the LLM.** Strip all `[00:00.00]` tags before sending text. Timestamps consume tokens and cause hallucination.
2. **Character-level ASR only.** Sentence-level or phrase-level timestamps cannot handle mid-sentence corrections. Use DashScope `fun-asr`.
3. **Asymmetric cut padding.** 250ms before the first character, 150ms after the last. Adjacent segments clamp at the midpoint of their unpadded boundaries — padding never crosses into the next segment, so there is zero overlap.
4. **30ms audio crossfades** at every cut boundary to prevent audible pops.

## Directory Layout

Each source video gets its own subdirectory under `<videos_dir>/edit/`:

```text
<videos_dir>/edit/<video_stem>/
├── raw_timestamps.json      # sentence-level, nested character timestamps
├── clean_transcript.txt     # [ID: N] lines, no timestamps — the LLM's view
├── llm_output.json          # [{"id": N, "keep": "..."}]
├── edl.json                 # mapped cuts [start, end, text, sentence_id]
├── preview.mp4 / final.mp4
└── segments/                # per-segment extracts (auto-deleted in final mode)
```

Pass `--edit-dir <videos_dir>/edit/<video_stem>` when invoking helpers.

## Setup

- `ffmpeg` + `ffprobe` on PATH.
- Python 3.10+, `pip install dashscope requests`.
- `DASHSCOPE_API_KEY` in `video-edit/.env` (or the environment). If missing, send the user this link to apply for one, then write the key to `.env`:
  [获取与配置 API Key - 阿里云百炼](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key?spm=5176.28197581.0.0.321674a1pKNTN2)

## Helpers

- **`transcribe.py <video> --edit-dir <dir>`** — uploads audio to DashScope (`fun-asr`), writes `raw_timestamps.json` + `clean_transcript.txt`.
- **`map_timestamps.py <llm_output.json> <raw_timestamps.json>`** — maps each `keep` to precise start/end timestamps, writes `edl.json` with asymmetric padding (250ms/150ms) and zero overlap.
- **`render.py <video> <edl.json> -o <out.mp4>`** — per-segment extract → lossless concat → output. Default `--encoder auto` resolves to NVENC (fastest) when available, else CPU. `--preview` for 720p fast iteration.

## Chunking

`transcribe.py` splits long transcripts automatically: up to 800 IDs per chunk, plus up to 20 read-only context IDs on each side. Each chunk header is machine-readable:

```text
[Chunk 001]
[Read range: IDs 1-820]
[Output range: IDs 1-800]
Context IDs are for understanding only; emit fragments only for the output range.
```

The editor model must never emit context IDs. Each chunk produces its own `chunk_NNN_decisions.json`; `map_timestamps.py <edit_dir>/chunks <edit_dir>/raw_timestamps.json` merges them in global ID order and writes `llm_output.json` before producing `edl.json`. Mapping runs once after all chunks are decided.

## The Process

1. **Transcribe:** `transcribe.py <video> --edit-dir <videos_dir>/edit/<video_stem>/`.
2. **Brief:** send `clean_transcript.txt` to the LLM, agree on edit strategy.
3. **Decide:** produce the decision JSON in one of two ways. For a short transcript this is `llm_output.json`; for a chunked transcript it is one `chunk_NNN_decisions.json` per chunk.
   - **Default — auto:** a sub-agent generates it using the Editor Prompt below.
   - **User takeover:** if the user says they want to fill it themselves, create an empty JSON containing `[]` and give them the `{id, keep}` format and the `clean_transcript.txt` path. Do not ask which mode they want; assume auto unless the user says otherwise.
4. **Map:** `map_timestamps.py llm_output.json raw_timestamps.json` → `edl.json` (or `<edit_dir>/chunks raw_timestamps.json` for a chunked transcript).
5. **Render:** `render.py <video> edl.json -o final.mp4` by default. Add `--preview` (720p, faster) only when the user explicitly asks for a preview.

## Editor Prompt

```text
You are a precision video editor for technical AI / LLM / deep-learning lectures. Read the transcript and discard false starts, stutters, and repetitive hesitations while preserving technical precision and logical continuity.

INPUT TEXT:
<clean_transcript.txt, or one chunk_NNN.txt for a chunked transcript>

RULES:
1. EXACT SUBSTRINGS: "keep" must be a character-for-character exact substring of the [ID: N] line. Do NOT fix typos or ASR errors (keep "GPT-RXL", "点击", "DFF" exactly as transcribed). Do NOT alter casing, spaces, or punctuation.
2. CONTINUOUS FLOW: derivations and reasoning flow across lines. Before deleting words at a line boundary, check adjacent IDs so equations and chains stay seamless.
3. PRESERVE TECHNICAL CONNECTIVES: never delete question/section labels ("问题A", "第一个问题"), logical markers ("所以", "因为", "接下来"), or bridging tokens ("Q、K、V", "S乘以D").
4. LATEST TAKE POLICY: on a restart or self-correction, keep only the final, most complete attempt; discard the earlier false start. Example — source has both "我们先算，我们先算一下这个矩阵的维度。" → keep only {"id": N, "keep": "我们先算一下这个矩阵的维度。"}.
5. COMPLETE OMISSION: if a whole line is an abandoned fragment ("来返回。", "他应该等于。"), omit the ID entirely. No empty strings.
6. SUB-SENTENCE CUTS: to remove disfluencies in the middle of a line, emit MULTIPLE objects with the SAME id, in order. Never merge the kept parts into one object.
   Example — source [ID: 19] "我们先把 这个 这个 公式推导一遍。":
   [
     {"id": 19, "keep": "我们先把"},
     {"id": 19, "keep": "公式推导一遍。"}
   ]
7. OUTPUT FORMAT: a raw JSON array of {"id": int, "keep": string}. No markdown fences, no commentary, no extra keys.

EXAMPLE:
[
  {"id": 19, "keep": "大家可以先结合我这里给出的几条估算提示，"},
  {"id": 19, "keep": "这四个问题自己先来做一下。"},
  {"id": 93, "keep": "我们接着来看问题B。"},
  {"id": 131, "keep": "继续算Z的梯度。"},
  {"id": 256, "keep": "哪怕是开 batch size 等于64，"},
  {"id": 256, "keep": "我们所需要的总显存量也不到6个 g。"}
]
```
