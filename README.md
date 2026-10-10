# video-edit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

<div align="center">

**中文** | [English](./README_en.md)

</div>

基于转录文本稿的视频剪辑 SKILL：输入一段口播/讲课视频，自动清掉口误、口吃、重复口播，产出干净成片。

[安装与快速开始](#安装与快速开始) · [工作原理](#工作原理) · [编辑契约](#编辑契约)

## 为什么选它？

- **语义与时钟解耦** —— 编辑模型只读转写文本、只做语义判断，脚本负责字级时间戳映射与渲染，模型可随意替换。
- **帧级精确** —— 基于字级时间戳，能精确剪掉句中的口吃/口误，而非整句删除。
- **长视频友好** —— 转写稿超长自动分段处理，决策合并后一次性渲染整条视频。
- **GPU 加速渲染** —— 默认走 NVENC，无 NVENC 自动回退 CPU。

## 安装与快速开始

### 环境要求

- Python 3.10+、[FFmpeg](https://ffmpeg.org/)（`ffmpeg` + `ffprobe` 在 `PATH` 上）
- 一个 DashScope API key（用于转写）

### 快速开始（人类用户）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 key
cp .env.example .env   # 然后编辑 DASHSCOPE_API_KEY

# 3. 跑通一条视频（转写 → 编辑决策 → 映射 → 渲染）
python helpers/transcribe.py <视频> --edit-dir <目录>
# 编辑模型读转写文本，产出 llm_output.json（唯一需要模型/人工的一步）
python helpers/map_timestamps.py <目录>/llm_output.json <目录>/raw_timestamps.json
python helpers/render.py <视频> <目录>/edl.json -o <目录>/final.mp4
```

### 快速开始（AI Agent）

> 面向 AI Agent 的步骤，需按 [`SKILL.md`](SKILL.md) 的流程执行。

**第 1 步 — 配置环境**：安装依赖、配置 `DASHSCOPE_API_KEY`（缺 key 时引导用户到 [阿里云百炼](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key) 申请）。

**第 2 步 — 转写**：运行 `transcribe.py`，产出 `raw_timestamps.json` + `clean_transcript.txt`。

**第 3 步 — 编辑决策**：默认由 sub-agent 读转写文本产出 `llm_output.json`（遵循下方编辑契约）；用户说「我来填」时才切换为人工填充。不主动问选哪种。

**第 4 步 — 映射 + 渲染**：运行 `map_timestamps.py` 映射出 EDL，再 `render.py` 渲染 final（默认 final，仅用户显式要求预览时加 `--preview`）。

## 工作原理

编辑模型（LLM）与时间戳严格解耦：模型只读转写文本、只做语义判断，脚本负责字级时间戳映射与渲染。

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

## 编辑契约

编辑模型只接收转写文本行，返回纯 JSON 数组 `[{"id": N, "keep": "原文精确子串"}]`。三条规则：

- `keep` 必须是该 `id` 对应源句的**精确连续子串**，不要「修正」ASR 错误、标点、空格或大小写。
- 数组里不出现的 `id` 会被**整体删除**。
- 同一 `id` 的多条记录 = 一次**句中删除**，按源顺序排列。绝不能把保留的两段又合并回一条。

7 条编辑规则全文、分段处理、编码默认值、编辑提示词，见 [`SKILL.md`](SKILL.md)。无需视频、无需 key 的完整数据形态演示见 [`examples/`](examples/README.md)。
