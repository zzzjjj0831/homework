# 李白.Skill — 中文文本去AI化润色专家

> 检测并消除中文文本中的 AI 生成痕迹，将生硬的机器输出转化为自然流畅的人类文笔。

## 核心能力

- **AI 痕迹检测**：脚本取证（`detect.py` 16 类词/句式计数 + 4 项标点）+ 七维定论（D1-D7，含脚本测不到的结构与内容维度）
- **分层改写**：四步排雷法（表层清理）+ 破式五层法（深层重构），从词汇到语气逐层去味
- **四步质控闭环**：检测诊断→执行改写→自检验收→交付结果，每步可追溯验收
- **证据化执行**：诊断取证 → 最小改动 → 四层质检留痕（数值 + 未改断言）；判据达标即可，不要求改法一致
- **骨架 + 双引擎**：细则下沉到 `resources/`，靠**路由引擎**（按步读哪个文件，**未读＝该步未生效**）与**意识引擎**（触发信号 → 必须想起的判据）+ 漏读自查，保证不断层
- **三模式交付**：A 完整专业版 / B 轻量润色版（默认）/ C 仅诊断，按需选择
- **文体智能适配**：三档强度（保守/标准/激进）× 文体浓度对照（网文/社交 100% → 学术/政务 30%），口径见 `SKILL.md` 的「1.2 润色强度自动匹配」

## 快速触发

只需一句话即可激活，如 "帮我把这篇文章去 AI 味"。支持 12 个触发词：去AI味、去AI痕迹、AI润色、降AI、人味、人味注入、去机器味、deai、humanize、文章润色、文本润色、AI改写。

## 文件结构

```
libai-skill/
├── SKILL.md              # 骨架：四步闭环 + 门禁 + 指针（≤8000 字符，防平台截断）
├── README.md             # 本文件 — 技能概览
├── QUICKSTART.md          # 5 分钟上手
├── faq.md                 # 常见问题
├── scripts/               # Python CLI 工具（detect / rewrite / transform / compare + 共享库）
└── resources/             # 规则语料 + 分步细则（本技能唯一的辅助目录）
    ├── zh_rules.json / zh_rules_archived.json / synonyms.json               # 规则集与词库（脚本读取）
    ├── banned-words.md / examples.md / examples-advanced.md / structures.md # 禁用词、示例库、句法参考
    ├── diagnosis.md       #   细则·诊断：七维定论表 / 脚本↔维度映射 / 两条例外
    ├── rewrite-playbook.md#   细则·改写：破式五层 / 清除清单 / 风格注入 / 四问 / 三狠招
    └── qa-delivery.md     #   细则·质检交付：四层清单 / A·B·C 三模式格式
```

> **骨架 + 按需加载**：`SKILL.md` 只留流程、门禁与判据；分步细则在 `resources/` 的 `diagnosis.md` / `rewrite-playbook.md` / `qa-delivery.md`，执行到对应步骤时才读（对照 `SKILL.md` 的「路由引擎」）。

## 依赖

- **Python ≥ 3.8**（脚本层），无外部 pip 依赖（纯标准库）
- **装 Python**：Windows `winget install Python.Python.3.12`；macOS `brew install python3`（或 `xcode-select --install`）；Debian/Ubuntu `sudo apt install python3`
- **Windows 注意**：`python` 可能只是应用商店的执行别名（真实路径落在 `WindowsApps`）——改用 `py -3` 或 `python3`，或从 python.org 装正式版
- **无 Python 也能用**：`scripts/*` 不可用时技能降级为**纯 LLM 模式**（手工改写 + 七维诊断），核心能力不受影响

## 版本

**v2.2.0** | 作者：智慧半岛

## 相关文档

- [QUICKSTART.md](./QUICKSTART.md) — 5 分钟上手
- [faq.md](./faq.md) — 常见问题
