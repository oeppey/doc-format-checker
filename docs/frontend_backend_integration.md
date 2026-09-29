# 前后端联调说明（阶段 1–4）

更新：2026-09-28

## 启动

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn document_checker.api:app --host 127.0.0.1 --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。页面由本地服务提供；直接打开 `file://.../template-management.html` 不会运行真实数据流。服务默认只监听本机。当前仅接收最大 20 MB 的 `.docx`。审查任务默认同时执行 1 份，可通过 `DOCUMENT_CHECKER_MAX_REVIEWS` 调整；实际值应在部署算力确认后标定。

## 页面当前操作

| 页面动作 | 后端入口 | 结果 |
|---|---|---|
| 打开模板页 | `GET /api/catalog`，`GET /api/templates` | 36 个候选检测项的能力状态；两套内置 YAML 模板及已保存的自定义模板 |
| 上传样本 Word | `POST /api/templates/extract`，multipart `file` | 实际读到的候选格式、来源、混合值、未检查范围；候选均未启用 |
| 编辑并保存 | `POST /api/templates/validate`，`POST /api/templates`，JSON | 单位和规则校验；保存标准化规则和编译后的可执行规则 |
| 查看、删除 | `GET /api/templates/{id}`，`DELETE /api/templates/{id}` | 内置模板只读；自定义模板存于本机 `data/templates/` |
| 选择模板审查 | `POST /api/reviews`，multipart `template_id` + `file` | 格式 Finding、错字 Finding、逐规则状态、实际模型后端、未检查范围 |

页面不再将浏览器内的关键词匹配称为正式审查，也不再将一份样本文档的值直接保存为规范。样本中的同一属性有多种值时，返回 `mixed`，需要用户选择。不存在的角色不会从样本推断出“无需检查”。

## 阶段 4：逐页预览与标注

本地需安装 LibreOffice，或设置 `DOCUMENT_CHECKER_SOFFICE` 指向 `soffice` / Windows 的 `soffice.com`。本机验证时将官方 LibreOffice MSI 提取到被 Git 忽略的 `data/tools/lo-unpacked/`，开发服务会自动识别该路径；部署环境仍应显式提供渲染器。Python 依赖为 PyMuPDF。预览不调用模型；PDF 转换和页面栅格化占用 CPU，审查并发仍受 `DOCUMENT_CHECKER_MAX_REVIEWS` 限制。

`POST /api/reviews` 现返回 `preview`：`status` 为 `ready` 或 `failed`，成功时含随机 `review_id`、PDF URL、逐页图片 URL／页面磅尺寸及逐条 `annotations`。坐标矩形单位为 PDF pt，前端按页面宽高转成百分比叠加红色错字框和黄色格式框。正文段落通过 PDF 字符序列顺序匹配，run 和错字片段可细定位；跨行片段拆成多个矩形。`precision` 分 `text`／`run`／`paragraph`／`page`／`unlocated`。页面级错误显示角标，无法可靠匹配的节或页脚错误不猜坐标。

预览接口：`GET /api/reviews/{review_id}/pages/{page_number}`、`GET /api/reviews/{review_id}/preview.pdf`；`DELETE /api/reviews/{review_id}` 可删除该次渲染文件。渲染文件存于 `data/reviews/`，包含文档内容，应按部署环境的数据保留策略清理。渲染失败时审查结果仍返回，页面明确显示失败原因。

实测：人工 Word 样本 `02_body_font_second_run_bad.docx` 渲染 2 页；第二个 run 的字体错误映射到第 1 页两个黄色矩形，页面图片接口返回 200。浏览器中两页图片加载成功、Finding 可跳转标记、无脚本错误。新增 `tests/test_preview.py` 验证坐标与失败状态，并用真实 DOCX 验证红色错字坐标；浏览器另以「布署→部署」样本确认红框和问题列表跳转。LibreOffice 生成的分页可能与 Microsoft Word 有差异；原样程度需在目标字体和排版环境中对照验收。奇偶页留字已改为方向＋字数选项，并受「奇偶页不同」设置控制；视觉规则尚未实现，无法启用为自动检查。

## 检测项数量与能力

- **36**：带 ID 的产品候选原子项，其中包含部分支持和待实现项。
- **10**：后端已注册的检查器类别。
- **12**：每套内置 YAML 合并后的实际规则条数。
- 旧页面 **29 行展示字段**和写死的“26 项”均不表示实际检测能力；新页面按编译结果显示生效规则数。

自定义模板先开放能忠实映射到现有检查器的原子项。某些结构检查器现在会同时判定位置、存在性和文本格式，尚不能保证每个原子项独立执行，因而保留内置 YAML 的检查能力，但不开放相应自定义开关。印章相关项已于 2026-09-29 整支移除（业务确认不做印章）。

## 状态与结果约定

- 格式和错字报告各有自己的状态、Finding、未检查范围；页面同时显示这些信息，不把局部跳过或模型降级解释为“全文通过”。
- 错字流程默认不调用外部 LLM。设置 `DOCUMENT_CHECKER_USE_LLM=1` 且已配置真实网关时才尝试精检；实际后端名称写入报告。
- 阶段 4 已加入 DOCX→PDF 逐页渲染、页图和坐标标注。坐标以生成的 PDF 为准；不能可靠映射的 Finding 保留在列表并标为未定位。
- 修复下载属于阶段 5。当前页面不提供原型版“重建正文 DOCX”按钮，以免丢失表格、图片和原有结构。

## 后续工作

1. 继续验证不同系统字体、复杂表格和多节页脚下的 Word／LibreOffice 排版差异与坐标覆盖率。
2. 阶段 5：在原 DOCX 上定点修复可确定的格式问题，用户确认错字建议后修改并下载。
3. 按业务复核结果逐步扩展目录中“部分支持／待实现”的规则，包括表格适用范围、具体页脚故事、段前段后、缩进和结构原子项。

