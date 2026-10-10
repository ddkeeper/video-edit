# video-edit

<div align="center">

**中文** | [English](./README_en.md)

</div>

基于转写的精确视频剪辑工具：**模型负责语义判断，脚本负责帧级精确的时间戳映射与渲染，两者严格解耦**。输入一段口播/讲课视频，自动清掉口误、口吃、重复口播，产出干净成片。

## 核心思路

- 编辑模型**永远看不到时间戳**，只看到 `[ID: N]` 的转写文本行。
- 模型返回一份 `{"id": N, "keep": "原文精确子串"}` 的 JSON 决策（纯语义，不碰时钟）。
- 脚本把决策映射回字级时间戳，生成毫秒级剪辑点（EDL），再用 NVENC 渲染。

这样模型可以随意替换，映射出错时**直接报错**，而不是静默错位。

## 四步流水线

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
                render ──▶ 成片
```

## 快速上手

### 1. 环境

- Python 3.10+、[FFmpeg](https://ffmpeg.org/)（`ffmpeg` + `ffprobe` 在 `PATH` 上）
- 一个 DashScope API key（用于转写）

```bash
pip install -r requirements.txt
```

### 2. 配置 key

复制 `.env.example` 为 `.env`，填入 `DASHSCOPE_API_KEY`。

### 3. 跑通流水线

```bash
# 1. 转写（产出 raw_timestamps.json + clean_transcript.txt）
python helpers/transcribe.py <视频> --edit-dir <目录>

# 2. 编辑模型读转写文本，产出 llm_output.json（唯一需要模型的一步）

# 3. 决策映射回毫秒级时间戳
python helpers/map_timestamps.py <目录>/llm_output.json <目录>/raw_timestamps.json

# 4. 渲染（有 NVENC 就用，否则回退 CPU）
python helpers/render.py <视频> <目录>/edl.json -o <目录>/final.mp4
```

无需视频、无需 key 的完整数据形态演示见 [`examples/`](examples/README.md)。

## 编辑契约

编辑模型只接收转写文本行，返回纯 JSON 数组：

```json
[
  {"id": 19, "keep": "exact source text"},
  {"id": 19, "keep": "another exact fragment"}
]
```

三条规则：

- `keep` 必须是该 `id` 对应源句的**精确连续子串**，不要「修正」ASR 错误、标点、空格或大小写。
- 数组里不出现的 `id` 会被**整体删除**。
- 同一 `id` 的多条记录 = 一次**句中删除**，按源顺序排列。要删句中口吃/口误，必须输出**同 `id` 的多条独立记录**——绝不能把保留的两段又合并回一条，否则中间剪切就丢了（完整例子见 [`SKILL.md`](SKILL.md) 第 6 条规则）。

## 完整规格

7 条编辑规则、分段处理（长转录稿）、编码默认值、编辑提示词等，全部见 [`SKILL.md`](SKILL.md)。
