# examples/

A minimal, self-contained, and ASR-free example of the whole pipeline. The
audio source is fictional (a cache-hit-rate problem walkthrough), so you can
read every artifact without a DashScope key or a video file.

## Files and their roles

| File | Stage | Produced by |
| --- | --- | --- |
| `raw_timestamps.json` | input | `helpers/transcribe.py` (here: hand-written fixture) |
| `clean_transcript.txt` | input | `helpers/transcribe.py` (here: derived by hand) |
| `llm_output.json` | decision | the editor model (here: written by hand) |
| `edl.json` | output | `helpers/map_timestamps.py` |

The editor decision omits `ID 3` ("这个这个我们先看第一个子问题"), an
abandoned fragment, so it is cut entirely. The remaining four fragments are
mapped to millisecond-accurate ranges with the default padding (250 ms before,
150 ms after) and clamped at boundaries.

## Regenerate `edl.json`

```bash
python helpers/map_timestamps.py examples/llm_output.json examples/raw_timestamps.json -o examples/edl.json
```

Expected output: `Total Segments: 4`, `Total Kept Duration: 8.80s`.

## 说明（中文）

这是一组**最小、自包含、无需 ASR** 的完整流水线示例。音频内容是虚构的
（一道「缓存命中率」例题讲解），因此无需 DashScope key 或视频文件即可阅读
全部产物。

`llm_output.json` 省略了 `ID 3`（“这个这个我们先看第一个子问题”，一句被
放弃的口误），因此被整体剪掉；其余 4 个片段被映射为毫秒级区间，并使用默认
padding（前 250ms、后 150ms）并在边界处做了收敛。
