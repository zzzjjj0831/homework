# jagent 项目规则（在本目录启动时自动注入）

## 你的位置
工作目录是 `Agent/jagent`：`core/` 是能力层（agent/tools/mcp/skills/session/context/config），
`tui/` 是界面层，`tests/` 是单元测试。不要在 `tui/` 里写业务逻辑。

## 改代码时
- 工具返回值统一走 `core/tools/envelope.py`：成功 `{"ok": true, ...}`，失败
  `{"ok": false, "error": {"code", "message"}}`，不要发明第三种格式；
- 任何文件/目录操作必须使用 `core/tools/paths.py::PathPolicy` 解析路径，禁止直接拼接；
- 新增工具时同步更新 `core/tools/registry.py` 的 schema 与 `tests/` 里的用例；
- 破坏性操作保留 `confirm=true` 门控。

## 验证
```bash
python -m unittest discover -s tests -t .    # 32 个用例
python ../../run_tests.py                    # 三个子项目一起跑
```

## 回答风格
先给结论，再给证据（文件:行号）；不确定的事标注"未验证"，不要编造运行结果。
