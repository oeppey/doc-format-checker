# 业务复核清单：标题序号、表格、成文日期、空行

状态：**待业务人工复核**。本文件提供可裁定的样本与暂定口径；请复核人直接打开 DOCX，记录判断与证据。复核完成后同步修改相应 gold、规则 YAML 和本文件，署名与日期不得代填。

依据：[国家标准公开信息](https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=F3CC9BEF482524C895FDA7A08BB4A70E)；[GB/T 9704-2012 原文转载（中国矿业大学党政办）](https://dzb.cumtb.edu.cn/info/1040/1184.htm)。内部“下空二行”以项目的《常用公文格式》照片为来源。

## 复核顺序与需要记录的决定

| 顺序 | 样本 | 现行工程判断 | 业务需决定 |
|---|---|---|---|
| Q1 | [10 号 DOCX](../tests/fixtures/manual/heading/10_heading_number_in_body_bad.docx) 与 [gold](../tests/fixtures/manual/heading/10_heading_number_in_body_bad.gold.json)，对照 [14 号 DOCX](../tests/fixtures/manual/heading/14_heading1_misnumbered_labeled.docx) | 10 号以“1、”开头，现映射为 body，报 heading-number: error；国标 7.3.3 给出四级结构序数，但不直接禁止所有正文列举 | 第 11 段实际是结构标题、正文列举，还是无法判定？该场景应报 error、warning 或不报？ |
| Q2 | [15 号 DOCX](../tests/fixtures/manual/table/15_body_in_table.docx) 与 [gold](../tests/fixtures/manual/table/15_body_in_table.gold.json) | 表格文字已解析；角色、格式与错字规则暂不适用，报告列未检查 | 哪些单元格属于正文？表头、编号／数字列、签批栏是否另用规则？格式检查和错字检查分别是否适用？ |
| Q3 | [11 号 DOCX](../tests/fixtures/manual/signature/11_signature_date_format_bad.docx) 与 [gold](../tests/fixtures/manual/signature/11_signature_date_format_bad.gold.json) | 根据国标 7.3.5.4，2026.9.18 报 error；2026年09月18日 也不通过 | 这些文书是否一律按 2026年9月18日 写？是否存在正式批准的例外？ |
| Q4 | [12 号 DOCX](../tests/fixtures/manual/signature/12_signature_blank_lines_bad.docx) 与 [gold](../tests/fixtures/manual/signature/12_signature_blank_lines_bad.gold.json)，对照 [01 号合规样本](../tests/fixtures/manual/font/01_body_font_ok.docx)及[大字版新合规样本](../samples/compliant-dazi-q4.docx) | 内部照片“下空二行”暂用两个空 Word 段、各段固定行距等于正文行距判断；12 号只有一个空段，报 warning | 该内部要求用于盖章、不盖章、哪类文书？接受此空段代理吗？是否需按渲染视觉间距判断？ |

## 复核操作与记录

1. 在 Word 中显示段落标记（¶），逐份确认文字、段落顺序、样式、行距和表格单元格内容；Q4 同时查看打印布局或 PDF，确认“下空二行”的视觉效果。
2. 对 Q1 写明真实语义角色和理由；对 Q2 至少提供一个应查单元格与一个不应查或用专用规则的单元格；对 Q3/Q4 写明适用文书及例外。
3. 在下面记录结论、复核人和日期。涉及改动时先修 DOCX 或 gold，再调整 YAML／检查器，并运行全量测试。手工修改的 DOCX 需同步生成脚本或另存为人工样本，以免重建时被覆盖。

| 问题 | 业务结论与正反例依据 | 复核人 | 日期 | 是否已同步 gold／YAML／代码 |
|---|---|---|---|---|
| Q1 | 待填写 | 待填写 | 待填写 | 否 |
| Q2 | 待填写 | 待填写 | 待填写 | 否 |
| Q3 | 待填写 | 待填写 | 待填写 | 否 |
| Q4 | 待填写 | 待填写 | 待填写 | 否 |

**已知边界：**空 Word 段不是实际页面上的“二行”证明；表格 15 号虽能读出文字，当前未套用规则。未获得业务结论前不得把上述暂定判断写成正式验收结论。
