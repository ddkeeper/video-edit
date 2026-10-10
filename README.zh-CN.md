# video-edit

**基于转写的精确视频剪辑** —— 把一段口播视频剪成干净成片。模型负责语义判断，
脚本负责确定性的时间戳映射与渲染，两者严格解耦。

## 它做什么

给定一段源视频，`video-edit` 分四步产出成片：

```
源视频 ──transcribe──▶ 带时间戳的转写文本
                          │
                          ▼
              编辑模型产出 {id, keep} 决策
                          │
                          ▼
         map_timestamps ──▶ EDL（毫秒级剪辑点）
                          │
                          ▼
                render ──▶ 成片（preview / final）
```

核心设计是**契约（contract）**：编辑模型永远看不到时间戳，只看到
`[ID: N]` 的转写文本行；它返回一份 `{"id": N, "keep": "原文精确子串"}` 的
JSON 决策。这让模型的工作纯粹是语义性的，而脚本负责帧级精确的剪辑。

## 为什么这样设计？

| 职责 | 归属 | 原因 |
| --- | --- | --- |
| 剪什么 / 留什么 | 编辑模型（LLM） | 语义判断，难以脚本化 |
| 毫秒级映射 | `map_timestamps.py` | 需要确定性、精确 |
| 编码 / 渲染 | `render.py` | 针对讲课录屏调优 |

两者解耦后，你可以随意替换编辑模型；而映射步骤遇到问题会**直接报错**，
而不是静默错位。

## 快速上手

### 1. 环境准备

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/)（`ffmpeg` 和 `ffprobe` 需在 `PATH` 上）
- 一个 DashScope API key（用于转写）

```bash
pip install -r requirements.txt
```

### 2. 配置 key

复制 `.env.example` 为 `.env` 并填入你的 key：

```bash
cp .env.example .env   # 然后编辑 DASHSCOPE_API_KEY
```

key 的读取顺序：`DASHSCOPE_API_KEY` 环境变量 → `video-edit/.env` → 项目
`.env` → `~/.codex/video-edit.env`。

### 3. 跑通流水线

```bash
# 1. 转写（产出 raw_timestamps.json + clean_transcript.txt）
python helpers/transcribe.py <视频> --edit-dir <目录>

# 2. 让编辑模型读取转写文本，写出 llm_output.json
#    （见下方「编辑契约」，这是唯一需要模型/人工的一步）

# 3. 把决策映射回毫秒级时间戳
python helpers/map_timestamps.py <目录>/llm_output.json <目录>/raw_timestamps.json

# 4. 渲染（有 NVENC 就用，否则回退 CPU）
python helpers/render.py <视频> <目录>/edl.json -o <目录>/final.mp4
```

无需视频、无需 key 的完整数据形态演示见 [`examples/`](examples/README.md)。

## 编辑契约

编辑模型（LLM）只接收转写文本行，返回一个纯 JSON 数组：

```json
[
  {"id": 19, "keep": "exact source text"},
  {"id": 19, "keep": "another exact fragment"}
]
```

规则：

- `keep` 必须是该 `id` 对应源句的**精确连续子串**。不要「修正」ASR 错误、
  标点、空格或大小写。
- 数组里不出现的 `id` 会被整体删除。
- 同一 `id` 的多条记录表示一次**内部删除**，按源顺序排列。要在句中删掉
  口吃/口误时，必须输出**同 `id` 的多条独立记录**——绝不能把保留的两段又
  合并回一条，否则中间的剪切就丢失了。（见 [`SKILL.md`](SKILL.md) 第 6 条规则的完整例子。）

## 编码默认值

面向长时间、低动态的录屏讲课场景调优：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--encoder` | `auto` | 有 NVENC 就用，否则 CPU |
| `--workers` | `2` | 两段并行编码 |
| `--nvenc-preset` | `p5` final / `p4` preview | p5 比 p7 快约 1.45×，肉眼无差 |
| `--priority` | `below` | 渲染时保持桌面流畅（Windows） |

完整 fallback 与实测数据见 [`SKILL.md`](SKILL.md)。

## 目录结构

```
video-edit/
├── SKILL.md              # 完整 skill 规格、规则与编辑提示词
├── helpers/
│   ├── transcribe.py     # DashScope ASR → 字级时间戳
│   ├── map_timestamps.py # {id,keep} 决策 → 毫秒级 EDL（核心）
│   └── render.py         # EDL → preview/final（NVENC 或 CPU）
├── examples/             # 最小自包含流水线演示
├── requirements.txt
└── .env.example
```

## License

[MIT](LICENSE)

## English

[README.md](README.md)
