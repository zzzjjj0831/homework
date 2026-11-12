# AnythingLLM 上传网页

单文件网页（`index.html`，无构建、无依赖）：选择文件 → 上传到 AnythingLLM → 加入工作区完成向量化。

## 使用

1. 启动 AnythingLLM（默认 `http://127.0.0.1:3001`）；
2. 直接用浏览器打开 `index.html`（或 `python -m http.server 5500` 后访问 `http://127.0.0.1:5500/index.html`）；
3. 在页面顶部填写 **API 地址** 与 **API Key**，点"保存并连接"；
4. 拖拽/选择文件 → "上传并嵌入"。

## 连接配置与密钥

- 地址与 Key **不写在源码里**，由用户在页面输入，仅保存在浏览器 `sessionStorage`（关闭标签页即失效）；
- 页面只用 Key 组装 `Authorization: Bearer <key>` 请求头，不写入 `localStorage`、不回显到 DOM；
- 若把页面部署到服务器，请额外加一层反向代理鉴权——**浏览器直连意味着 Key 会进入该浏览器**，
  正式环境应把 Key 留在服务端代理里。

## 主流程与状态

| 阶段 | 接口 | 页面表现 |
| --- | --- | --- |
| 连接 | `GET /api/v1/workspaces` | 加载中转圈 → 成功显示目标工作区 → 失败显示原因与排查提示 |
| 上传 | `POST /api/v1/document/upload`（multipart） | 每个文件一行进度，成功显示标题与词数，失败显示错误 |
| 向量化 | `POST /api/v1/workspace/{slug}/update-embeddings` | 显示"正在嵌入 N 个文档"→ 完成提示；失败提示"已上传但未向量化" |

## 安全

- 所有来自接口与用户的文本都通过 `textContent` 写入，不使用 `innerHTML`/`insertAdjacentHTML`，
  文件名、工作区名不会造成 XSS；
- 源码中不含任何 Key（可在仓库根执行 `rg -n "Bearer [A-Z0-9]" ` 自查）；
- 只访问用户填写的地址，不做跨域写入。

## 限制

- 只做"上传 + 向量化"一条主流程，不含对话与工作区切换；
- 未做分片上传，单文件过大时由 AnythingLLM 侧限制。
