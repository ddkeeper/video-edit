# video-edit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-green.svg)](https://ffmpeg.org/)

<div align="center">

**中文** | [English](./README_en.md)

</div>

基于转录文本稿的视频剪辑 SKILL：输入一段口播/讲课视频，自动清掉口误、口吃、重复口播，产出干净成片。

[安装与快速开始](#安装与快速开始) · [工作原理](#工作原理) · [剪辑要求](#剪辑要求)

## 为什么选它？

- **语义与时钟解耦** —— 编辑模型只读转写文本、只做语义判断，脚本负责字级时间戳映射与渲染，模型可随意替换。
- **帧级精确** —— 基于字级时间戳，能精确剪掉句中的口吃/口误，而非整句删除。
- **长视频友好** —— 转写稿超长自动分段处理，决策合并后一次性渲染整条视频。
- **GPU 加速渲染** —— 默认走 NVENC，无 NVENC 自动回退 CPU。

## 安装与快速开始

### 快速开始（人类用户）

1. 安装：

```bash
git clone https://github.com/ddkeeper/video-edit.git
```

2. 在 Agent 里输入提示词，让它用安装好的 skill 剪辑视频，例如：

> 用 video-edit skill 帮我剪辑这段视频。

### 快速开始（AI Agent）

> 以下指令面向 AI Agent，请用 git 将本仓库安装到当前环境对应的 skill 目录。

```bash
git clone https://github.com/ddkeeper/video-edit.git <skills目录>/video-edit
```

`SKILL.md` 即 skill 入口，装载后生效；装好后按 [`SKILL.md`](SKILL.md) 的流程自动执行。

### 说明

转录依赖云端语音识别模型，需要相应的 API key（[获取与配置 API Key - 阿里云百炼](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key?spm=5176.28197581.0.0.321674a1pKNTN2)）。实际使用中由 Agent 执行 skill 引导完成，此处仅供知悉。

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

## 剪辑要求

编辑模型只接收转写文本行，返回纯 JSON 数组 `[{"id": N, "keep": "原文精确子串"}]`。核心规则：

- `keep` 必须是该 `id` 对应源句的**精确连续子串**，不要「修正」ASR 错误、标点、空格或大小写。
- 数组里不出现的 `id` 会被**整体删除**。
- 同一 `id` 的多条记录 = 一次**句中删除**，按源顺序排列，绝不能把保留的两段又合并回一条。

完整 7 条规则（含技术连接词保留、最后版本优先、子句剪切等）见 [`SKILL.md`](SKILL.md) 的 `Editor Prompt`。

> **换使用场景**：本 SKILL 默认面向口播/讲课视频。若要用于别的场景（如访谈、会议纪要剪辑），只需修改 [`SKILL.md`](SKILL.md) 里 `Editor Prompt` 的 `RULES` 与例句即可，其余流程（转写、映射、渲染）无需改动。

无需视频、无需 key 的完整数据形态演示见 [`examples/`](examples/README.md)。
