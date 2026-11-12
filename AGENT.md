# 仓库级长期规则（jagent 启动时读取一次并注入 system 提示）

## 项目背景
这是 LLM 课程期末项目仓库，包含：`Agent/jagent`（Agent 主体）、`PetHospitalmcp`（宠物医院 MCP）、
`AnythingLLMCP`（AnythingLLM MCP）、`AnythingLLMWebpage`（上传网页）。

## 编码约定
- Python 3.11+，仅使用标准库 + 项目 `requirements.txt` 中声明的依赖
- 所有工具函数返回 JSON 字符串：成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": {"code", "message"}}`
- 不新增网络调用到测试里；测试一律用 `unittest` + `httpx.MockTransport` / 假模型客户端

## 安全红线
- 不把任何真实密钥写进代码、配置或前端页面；示例值只能写占位符
- 文件操作必须经过 `core/tools/paths.py` 的 `PathPolicy`，不要绕过它直接拼路径
- 删除、重命名等破坏性操作保持 `confirm=true` 的门槛，不要为了"顺手"去掉

## 常用命令
```bash
python run_tests.py                 # 全部测试
python run_tests.py jagent          # 只跑 Agent
cd Agent/jagent && python main.py   # 启动 TUI
```

## 交付要求
- 新增能力必须同时更新对应 README 与验证清单
- 改动日志格式或错误码时，同步更新 `README.md` 的"错误码/配置矩阵"章节
