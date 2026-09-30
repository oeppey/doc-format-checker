# 检测项标准化写法与单位规范

> 日期：2026-09-28
> 用途：模板管理页新建／编辑规则模板时的**标准语言**——前端录入的任何写法都先转成这里的标准形式，再编译为后端 YAML 规则（checker + params）。
> 范围：页面、字体、段落、页码四类（对应前端现有字段），外加现有两套模板已在用、但附件目录未覆盖的**结构类**规则。
> 依据：`src/document_checker/rules_schema.py`（9 类检查器及字段校验）、`template-management.html` 的 PRESETS、`tests/fixtures/manual/` 人工样本。

---

## 一、对附件方案的合理性分析

### 合理、可直接采纳的

1. **四层结构 `id / scope / expected / tolerance`**：职责划分正确——id 是「查什么」，scope 是「查哪里」，expected 是「标准值」，tolerance 是「允差」。
2. **`observed` 与 `expected` 分离**：上传 Word 读到的值不能直接当标准，这条必须保留，是防止「以错定标」的关键。
3. **单位表与换算规则**：mm→cm、号→pt、行距 cm→pt 的约定合理。
4. **倍数行距禁止换算成固定磅**：正确。Word 底层 `lineRule="auto"`（240=单倍）与 `exact/atLeast`（ twentieths of a point）是两种机制，换算会丢语义。
5. **两处文案歧义澄清**：「页脚底端距版心 1.75 厘米」与 Word `FooterDistance`（页脚距**纸张底边**）语义不同、「允许西文换行」有两种理解——都对，录入时必须让用户选明确义项。
6. **页码数字 1 不写死**：正确，页码是域结果，装饰（前后一字线）才是规则。

### 需要修正或补充的

| # | 问题 | 说明与建议 |
|---|---|---|
| R1 | `scope` 只有 `role` 不够 | 需要增加 `part` 维度：`body`／`table`／`footer-default`／`footer-first`／`footer-even`／`header`。16 号人工样本证明三类页脚是三个独立「故事」，页码规则本质是 `scope={part:"footer-*"}` 而不是角色 |
| R2 | 缺 `severity` | 规则必须有级别（12 号样本的「下空二行」是 warning）。建议字段必填，缺省 `error` |
| R3 | 缺角色缺失语义 | `font_format` 的 `required`（角色不存在是否报错）在标准语言里要有对应字段 |
| R4 | tolerance 只适用数值项 | 布尔、枚举项不应出现 tolerance；前端应按类型隐藏 |
| R5 | 「页码居中 = paragraph.alignment + role=page_number」与实现不一致 | 后端 `ROLES` 没有 `page_number` 角色，居中检查内嵌在 `page_number` checker 里。标准语言可以这样表达（逻辑视图），但**编译映射表必须写明它落到 page_number checker**，不能让前端以为存在这个段落角色 |
| R6 | 结构类规则不在前四类 26 个候选原子项里 | 现有两套模板各 12 条生效规则中，秘级、标题序号、附件、落款日期等结构规则不在「页面／字体／段落／页码」口径内。目录必须加 `structural.*` 一类，否则现有模板无法完整标准化 |
| R7 | 枚举值缺口 | 前端 PRESETS 正文对齐是「两端对齐」，但 `rules_schema.py` 的 alignment 只允许 left/center/right——`justify` 需要补实现或先从文案去掉 |
| R8 | 精度与允差 | Word 内部用 twips，3.8 cm 实测解析为 3.799 cm；`tolerance: 0.05 cm` 不是摆设，必须覆盖换算误差，不能收紧到 0 |
| R9 | 字号映射表不全 | 前端 `PT_SIZE` 到「小四」为止；解析器支持到「小五 9 pt」。标准应给全表（见下），否则五号字无法录入 |
| R10 | `char` 单位是相对量 | 「首行缩进 2 字符」的字符宽随字号变化；保留 `char` 单位正确，但标准里要注明它依赖本段字号，不与 cm 互换 |

**结论**：方案的骨架（四层结构 + 单位规范 + 输入转换）合理，按 R1–R10 补完后可作为模板标准语言；当前版本增加「奇偶页不同」设置，形成 35 项候选目录（移除印章专项后）。

---

## 二、标准写法 schema

```json
{
  "id": "font.size",
  "scope": {"part": "body", "role": "body"},
  "expected": {"value": 18, "unit": "pt"},
  "tolerance": {"value": 0.5, "unit": "pt"},
  "severity": "error",
  "required": false,
  "name": "正文字号",
  "source": "《常用公文格式》大字版"
}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `id` | `类别.属性`，全表唯一 | 查什么（见第三节总表） |
| `scope.part` | 当前仅执行 `body` 与 `footer-all`；`table`、各类页眉页脚定向 scope 待实现 | 查哪个部件 |
| `scope.role` | `title`｜`heading1`–`heading4`｜`body`｜`wenhao`｜`secrecy`｜`attachment`｜`signature`｜`date` | 查哪个角色；页面级规则省略 |
| `expected` | 数值 `{value, unit}`；枚举 `{value}`；布尔 `{value:true|false}`；字体 `{value, aliases:[...]}`；行距 `{mode, value, unit?}` | 标准值 |
| `tolerance` | `{value, unit}`，仅数值项可带，与 expected 同维度 | 允差 |
| `severity` | `error`｜`warning`｜`info`，缺省 error | 级别（必填项，R2） |
| `required` | true/false，缺省 false | 角色或部件不存在时是否报错（R3） |

## 三、全部检测项标准化总表

状态：✅ 已实现｜◐ 部分实现｜⛔ 待实现｜🖼 需渲染/VLM｜💼 待业务口径

| 类别 | 标准 id | scope | expected 写法（单位） | 编译目标 | 状态 |
|---|---|---|---|---|---|
| 页面 | `page.size` | — | `{width:210, height:297, unit:"mm", orientation:"portrait"}` | page_setup（待扩） | ⛔ |
| 页面 | `page.margin_top` | — | `{value:3.8, unit:"cm"}`，tolerance 0.05 cm | page_setup `top_cm` | ✅ |
| 页面 | `page.margin_bottom` | — | `{value:3.3, unit:"cm"}`，tolerance 0.05 cm | page_setup `bottom_cm` | ✅ |
| 页面 | `page.margin_left` | — | `{value:2.7, unit:"cm"}`，tolerance 0.05 cm | page_setup `left_cm` | ✅ |
| 页面 | `page.margin_right` | — | `{value:2.7, unit:"cm"}`，tolerance 0.05 cm | page_setup `right_cm` | ✅ |
| 页面 | `page.footer_distance` | — | `{value:1.75, unit:"cm"}`（页脚距**纸张底边**），tolerance 0.1 cm | 新模板编译为 page_setup `footer_distance_cm`；内置 YAML 暂沿用 page_number | ✅ |
| 字体 | `font.cjk` | role | `{value:"方正仿宋_GBK", aliases:[...]}` | font_format `fonts` | ✅ |
| 字体 | `font.latin` | role | `{value:"仿宋", aliases:[...]}` | font_format `ascii_fonts` | ✅ |
| 字体 | `font.size` | role | `{value:18, unit:"pt"}`（号→pt 见换算表） | font_format `size_pt` | ✅ |
| 字体 | `font.bold` | role | `{value:true}` | font_format `bold` | ✅ |
| 字体 | `font.character_spacing` | role | `{value:0.4, unit:"pt"}`（标准 0、加宽正、紧缩负） | char_spacing `spacing_pt` | ◐ 当前仅非负值可启用 |
| 段落 | `paragraph.alignment` | role | `{value:"left"\|"center"\|"right"\|"justify"}` | font_format `alignment` | ◐ justify 未实现（R7） |
| 段落 | `paragraph.line_spacing` | role（可多个） | `{mode:"exact"\|"at_least", value:32, unit:"pt"}` 或 `{mode:"multiple", value:1.5}`，tolerance 0.5 pt | line_spacing `line_pt` | ◐ 仅 exact |
| 段落 | `paragraph.first_line_indent` | role | `{value:2, unit:"char"}` 或 `{value:0.74, unit:"cm"}`（保留原单位类型） | 待新建 checker（解析器已读 `first_line_chars`） | ⛔ |
| 段落 | `paragraph.space_before` | role | `{value:0, unit:"line"\|"pt"}` | 待新建 checker | ⛔ |
| 段落 | `paragraph.space_after` | role | `{value:0, unit:"line"\|"pt"}` | 待新建 checker | ⛔ |
| 段落 | `paragraph.latin_wrap` | role | `{value:"break_at_word"\|"break_in_word"}`（不接受「允许西文换行」原文） | 待新建 checker（OOXML `w:wordWrap`） | ⛔ 💼 |
| 页码 | `page_number.field` | part=footer-* | `{value:"PAGE"}`（自动域，数字不写死） | page_number | ✅ |
| 页码 | `page_number.decoration` | part=footer-* | `{prefix:"— ", suffix:" —", space_count:1}` | page_number `dash` | ◐ 空格数未单独校验 |
| 页码 | `page_number.alignment` | part=footer-* | `{value:"center"}` | page_number `alignment`（见 R5） | ✅ |
| 页码 | `page_number.font_cjk` | part=footer-* | `{value:"宋体", aliases:["SimSun"]}` | page_number `fonts` | ✅ |
| 页码 | `page_number.font_size` | part=footer-* | `{value:14, unit:"pt"}` | page_number `size_pt` | ✅ |
| 页码 | `page_number.vertical_alignment` | part=footer-* | `{value:"center"}` | — | 🖼 |
| 页码 | `page_number.different_odd_even` | part=footer-all | `{value:true}`（奇偶页不同） | odd_even_setting | ✅ |
| 页码 | `page_number.odd_padding` | 奇数页页脚 | `{direction:"right", value:1, unit:"char"}`（右空／左空／不空＋字数） | page_number_padding | ✅ 按页脚段落字符单位缩进检查；口径见四.1 |
| 页码 | `page_number.even_padding` | 偶数页页脚 | `{direction:"left", value:1, unit:"char"}`（左空／右空／不空＋字数） | page_number_padding | ✅ 按页脚段落字符单位缩进检查；口径见四.1 |
| 页码 | `page_number.continuous_on_attachment` | — | `{value:true}` | — | ⛔ |
| 结构 | `structural.secrecy_position` | role=secrecy | `{value:"first_paragraph_top_left"}` | secrecy（位置+对齐） | ✅ |
| 结构 | `structural.secrecy_inner_space` | role=secrecy | `{value:true}`（「秘 密」空一格） | secrecy `inner_space` | ✅ |
| 结构 | `structural.heading_numbering` | role=heading1–4 | `{level1:"一、", level2:"（一）", level3:"1.", level4:"（1）", no_space_after_level3_4:true}` | heading_number | ✅ |
| 结构 | `structural.attachment_indent` | role=attachment | `{value:2, unit:"char"}` | attachment `indent_chars` | ✅ 💼（Q5 全角空格） |
| 结构 | `structural.attachment_blank_before` | role=attachment | `{value:1, unit:"blank_line"}` | attachment `blank_lines_before` | ✅ |
| 结构 | `structural.attachment_trailing_punct` | role=attachment | `{value:"forbidden"}` | attachment `forbid_trailing_punct` | ✅ |
| 结构 | `structural.signature_blank_before` | role=signature | `{value:2, unit:"blank_line"}`，空段行距 `{value:32, unit:"pt"}` | signature `blank_lines_before` 等 | ✅ 💼（Q4「下空二行」） |
| 结构 | `structural.date_format` | role=date | `{value:"chinese_full"}`（2026年9月18日） | signature `date_format` | ✅ 💼（Q3 规则来源） |

> 2026-09-29 业务确认：不做印章，盖章／不盖章两种情形的署名日期排版规则（署名右空二字、日期右移二字、日期右空四字、署名相对日期居中）一并取消，本表不再收录。

> `blank_line`：当前实现数**空段落数**，是「视觉空行」的代理指标（仅作为代理，不保证与渲染后的视觉空行等价）。Q4 业务确认前保留该单位并注明代理性质。
> 同一 role 的多个 `font.*` 原子规则编译时合并为一条 `font_format` 规则（见第六节示例）。

## 四、单位规范与换算表

| 维度 | 存储单位 | 输入换算 |
|---|---|---|
| 页面长度 | `cm`（保留 2 位） | `mm ÷ 10`；允差 ≥0.05 cm（twips 换算误差） |
| 字号 | `pt` | 号→pt 见下表 |
| 行距 | exact/at_least：`pt`；multiple：无量纲倍数 | `cm × 28.3465`→pt（保留 1 位）；**倍数禁止转 pt** |
| 字符间距 | `pt`（带符号） | 标准=0、加宽=正、紧缩=负 |
| 缩进 | `char` 或 `cm`，**保留原单位类型** | char 宽 = 本段字号，不与 cm 互换 |
| 段前段后 | `line` 或 `pt`，保留原单位类型 | — |
| 空行数 | `blank_line`（空段落数，代理指标） | — |
| 对齐 | 枚举 left/center/right/justify | 中文文案映射：左对齐/居中/右对齐/两端对齐 |
| 布尔 | true/false | — |

字号映射全表（补齐 R9）：

| 号 | pt | 号 | pt |
|---|---|---|---|
| 初号 | 42 | 小三 | 15 |
| 小初 | 36 | 四号 | 14 |
| 一号 | 26 | 小四 | 12 |
| 小一 | 24 | 五号 | 10.5 |
| 二号 | 22 | 小五 | 9 |
| 小二 | 18 | 三号 | 16 |

### 四.1 奇偶页页码留字的结构检查口径

此项只检查 **DOCX 中承载 PAGE 域的页脚段落** 是否使用字符单位缩进，不需要将 Word 渲染为 PDF。direction=right、value=1、unit=char 对应 w:ind/@w:rightChars=100 且左侧字符缩进为 0；direction=left 则反过来；direction=none 要求两侧字符缩进均为 0。解析时使用段落直接格式、段落样式链和文档默认值的有效属性。

规则要求同时开启并在模板中启用「奇偶页不同」。奇数页检查普通页脚，以及文档第 1 节启用「首页不同」时的首页页脚；偶数页检查偶数页页脚。后续节的独立首页页脚实际奇偶页无法从 DOCX 结构确定，明确列入未检查。跨节继承追溯到实际来源，同一来源只报告一次。找不到 PAGE 域或页脚来源无法解析时报告问题，不能当作留字符合要求。

**判定边界**：这是结构规则，判断文档是否按约定用字符缩进表达留字；它不保证渲染后页码与版心边缘的几何距离。用空格、制表位、文本框或其他长度缩进做出的视觉效果不属于这一规则的标准表达。需要核对实际页面坐标时，仍由独立的逐页预览／定位流程处理。

## 五、输入 → 标准语言转换表

| 用户输入 | 标准形式 |
|---|---|
| `上边距 38 mm` | `page.margin_top = {value:3.8, unit:"cm"}` |
| `正文小二号` | `font.size {scope.role:body} = {value:18, unit:"pt"}` |
| `标题方正小标宋、小一、加黑、居中` | 4 条原子规则：`font.cjk`／`font.size 24pt`／`font.bold true`／`paragraph.alignment center`，scope.role=title |
| `固定行距 32 磅` | `paragraph.line_spacing = {mode:"exact", value:32, unit:"pt"}` |
| `固定行距 0.8 cm` | `{mode:"exact", value:22.7, unit:"pt"}` |
| `1.5 倍行距` | `{mode:"multiple", value:1.5}`（不换算） |
| `行距 0.8 cm`（未说固定/最小） | **拦截**：让用户先选 mode |
| `首行缩进 2 字符` | `paragraph.first_line_indent = {value:2, unit:"char"}` |
| `段前 0 行、段后 0 行` | 两条独立规则，unit 均为 `line` |
| `字符间距加宽 0.4 磅` | `font.character_spacing = {value:0.4, unit:"pt"}` |
| `字符间距标准` | `font.character_spacing = {value:0, unit:"pt"}` |
| `页码 — 1 — 居中` | `page_number.field=PAGE`、`decoration={prefix:"— ",suffix:" —"}`、`alignment=center` 三条 |
| `页脚底端距版心 1.75 厘米` | **拦截**：提示语义差异，确认映射为 Word「页脚距底边」后保存 `page.footer_distance = {value:1.75, unit:"cm"}` |
| `允许西文换行` | **拦截**：让用户选 `break_at_word` 或 `break_in_word` |

原则：**能结构化录入就不解析文字**；文字输入只接受上表约定写法，歧义输入一律拦截让用户选，不猜。

## 六、新建模板的编译示例

标准语言（前端产物）：

```json
[
  {"id": "font.cjk", "scope": {"part": "body", "role": "body"},
   "expected": {"value": "方正仿宋_GBK", "aliases": ["方正仿宋GBK", "方正仿宋简体"]},
   "severity": "error"},
  {"id": "font.size", "scope": {"part": "body", "role": "body"},
   "expected": {"value": 18, "unit": "pt"}, "severity": "error"},
  {"id": "font.bold", "scope": {"part": "body", "role": "body"},
   "expected": {"value": true}, "severity": "error"}
]
```

编译为后端 YAML（同一 role 的 font.* 原子规则合并为一个 font_format 规则）：

```yaml
- id: font-body
  name: 正文字体字号
  severity: error
  checker: font_format
  params:
    role: body
    fonts: [方正仿宋_GBK, 方正仿宋GBK, 方正仿宋简体]
    size_pt: 18
    bold: true
```

编译后即进入 `rules_schema.validate_ruleset` 校验（未知 checker、未知参数、缺参数在运行前失败）。未实现的项可作为禁用候选保存在模板数据中，**不编译进可执行 YAML**；前端按「可自动检查／部分支持／待实现」展示，不得计入已执行规则。


---

## 七、第一轮代码落地边界（2026-09-28）

- 目录包含 **35 个候选原子检测项**（2026-09-29 移除印章专项后）；旧页面原有 **29 行展示字段**，原型写死的「26 项」不是能力数量。现有后端是 **11 类检查器**；两套内置 YAML 每套合并后 **12 条生效规则**。
- `GET /api/catalog` 返回候选项、输入类型及能力状态。上传 DOCX 的 `POST /api/templates/extract` 仅返回 `observed` 候选值、混合值和未检查范围；所有候选默认 `enabled:false`，用户确认后才是标准。
- 自定义模板目前能编译页面边距及页脚距离、正文角色的中文／西文字体、字号、加粗、左／中／右对齐、固定行距、非负字符间距，以及所有有效页脚统一的 PAGE 域、居中、字体和字号。奇偶页页码留字可分别启用为页脚段落字符缩进结构规则，前提是同时启用「奇偶页不同」且期望为是。表格定向、倍数／最小行距、紧缩字符间距及多数结构原子项不能启用。两套内置 YAML 保持原有结构检查能力。
- `scope.part` 的产品设计可以继续保留表格及各类页眉页脚，但第一轮编译仅接受正文 `body` 和全部有效页脚 `footer-all`。无法表达的适用范围会被校验拒绝。
- 同一角色的字体与对齐原子项仍合并到一个 `font_format` 检查器；这些项的 `severity` 必须相同。每个页面数值项独立编译，以保留各自允差。
- 当前上传和审查入口只接受 `.docx`。错字检查会记录真实使用的检测器／纠错器；模型不可用时的启发式结果标为未检查。逐页预览与基础坐标标注已在阶段 4 接入；原 DOCX 修复仍在后续阶段实现。

