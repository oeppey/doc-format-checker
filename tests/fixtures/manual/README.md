# Word 标注回归样本

当前有 **19 个案例、16 份不同的 DOCX**；01、04、06、08 共用同一大字版合规底稿，各自的 gold 检查不同规则。每份 DOCX 都有对应的 `*.gold.json`。生成入口是 `tests/fixtures/build_manual_fixtures.py`。

gold 仍是 **AI 起草的技术标注，未经过业务人工复核**。三层含义：

- `parse_expectations`：DOCX 客观文本和属性；每个案例至少有一项。
- `role_labels`：所有非空正文／表格段落都必须列出；表格角色尚未应用时另记 `role_known_gaps`。
- `expected_findings`：规则、级别、位置及期望／实际值的一一对应；`run` 和 `field` 现在也参与测试匹配。
- `known_gaps`：确有错误而当前链路仍未检出的地方；15 号表格正文是现存样本。

本轮新增三个独立反例：17 将密级段移到标题之后；18 保留 PAGE 域但清空其缓存数字；19 使附件段前只有一个全角空格。18 号检验的是 DOCX 包内的缓存结果；Word 打开或保存时可能更新 PAGE 域，人工复核应先核对原始 OOXML，不要用保存后的显示结果覆盖原件。原有 07 只测密级居中，05 只测无页脚，09 只测一个半角空格，三者保留作为不同反例。10、11、12 也已补解析层期望。样本生成器与保存的 17—19 号 DOCX 有逐包内容一致性测试。

位置如 `body/p4/run2`（第 4 个正文段的第二个 run）、`table1/r1c1/p1`、`footer/first/p1`，均从 1 起。下面的命令会**覆盖生成器管理的 DOCX**；若直接用 Word 手改，请同步改生成逻辑或另存为不受生成器管理的原件。

```powershell
.\.venv\Scripts\python tests\fixtures\build_manual_fixtures.py
.\.venv\Scripts\python -m pytest tests\test_manual_fixtures.py -q
```

新增 gold 应先根据样本设计和 Word／OOXML 写期望，再核对程序结果，不得把检查器输出自动抄为真值。业务复核时保留 AI 起草来源，另记复核人、日期、结论和争议。Windows 当前环境缺 LibreOffice，新增 DOCX 已经结构与 XML 校验，**尚未完成渲染视觉核对**；视觉条款须在 Word 或约定的 PDF 渲染环境另验。
