# video-edit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-green.svg)](https://ffmpeg.org/)

<div align="center">

**中文** | [English](./README_en.md)

</div>

基于转录文本稿的视频剪辑 SKILL：输入一段口播/讲课视频，自动清掉口误、口吃、重复口播，产出干净成片。

[安装](#安装) · [工作原理](#工作原理) · [剪辑要求](#剪辑要求)

## 为什么选它？

- **语义与时钟解耦** —— 编辑模型只读转写文本、只做语义判断，脚本负责字级时间戳映射与渲染，模型可随意替换。
- **帧级精确** —— 基于字级时间戳，能精确剪掉句中的口吃/口误，而非整句删除。
- **长视频友好** —— 转写稿超长自动分段处理，决策合并后一次性渲染整条视频。
- **GPU 加速渲染** —— 默认走 NVENC，无 NVENC 自动回退 CPU。

## 安装

> **给 AI Agent 的安装指令**：本仓库本身就是一个 skill。安装即「把仓库内容放进当前环境的 skills 目录，`SKILL.md` 作为入口」。请按以下步骤自动完成，全程无需打扰用户：

1. 找到当前 Agent 环境的用户级 skills 目录（常见位置：`~/.workbuddy/skills/`、`~/.agents/skills/`、`~/.claude/skills/` 等，按你所运行的环境判断）。
2. 在该目录下创建 `video-edit/`，并把本仓库全部文件放入其中（或直接 `git clone` 到该目录）。
3. 确认 `video-edit/SKILL.md` 存在——它即 skill 入口，装载后即生效。

**依赖与 key 由 Agent 在首次使用时按需处理**：缺 `dashscope` 就 `pip install`，缺 `ffmpeg` 就提示安装，缺 `DASHSCOPE_API_KEY` 就引导用户到 [阿里云百炼](https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key) 申请后写入 `.env`。不要把这些当作安装前置步骤。

装好后，用户只需说一句「帮我剪这段视频」，转写 → 决策 → 映射 → 渲染的完整流程由 Agent 按 [`SKILL.md`](SKILL.md) 自动执行。

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
