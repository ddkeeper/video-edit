# video-edit

<div align="center">

**中文** | [English](./README_en.md)

</div>

基于转录文本稿的视频剪辑技能：输入一段口播/讲课视频，自动清掉口误、口吃、重复口播，产出干净成片。

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

## Agent 上手

1. 配置 `DASHSCOPE_API_KEY`（转写用），装好依赖。
2. 按 [`SKILL.md`](SKILL.md) 的流程跑通一条视频：转写 → 编辑模型产出决策 → 映射 → 渲染。
3. 编辑决策的契约（`keep` 须为原文精确子串、缺省 `id` 整体删除、句中删除用同 `id` 多条）与 7 条规则，见 [`SKILL.md`](SKILL.md)。

无需视频、无需 key 的完整数据形态演示见 [`examples/`](examples/README.md)。
