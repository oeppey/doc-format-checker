# 公文格式检查系统（原型 v0.1）

按《常用公文格式》内部要求（参考 GB/T 9704-2012）对 Word 公文做自动格式检查。
当前目标：**跑通"规则配置 → 解析 → 角色映射 → 检查 → 报告"全链路，验证技术路线可行**；
精度与规则覆盖后续迭代。

当前工程状态、验证证据、风险和后续工作见 [工程状态与后续工作](docs/engineering_status.md)；规则需求源头见 [格式规则](docs/format_rules.md)；三张原图逐条实现情况见 [格式要求审计](docs/format_requirements_audit.md)；本轮 IR 扩展与待办见 [TODO](docs/TODO.md)。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\Activate.ps1

# 需要本地 ELECTRA 时再安装
.\.venv\Scripts\python -m pip install -e ".[detector]"
# 已有模型网关权限时再安装
.\.venv\Scripts\python -m pip install -e ".[gateway]"

# 生成合成样本
document-checker generate --type dazi --out samples/合规-呈报稿大字版.docx
document-checker generate --type dazi --out samples/违规示例.docx --violate body_font,line_spacing

# 检查（文书类型按标题字号自动识别，也可 --type 强制指定）
document-checker check samples/违规示例.docx --report 报告.md --json 报告.json
```

已注入 10 类违规的演示样本见 `samples/`，对应报告见 `samples/检查报告-违规示例.md`。
本轮验证过的合规样本是 `samples/合规-呈报稿大字版-新版.docx` 与小字版对应文件，均为 0 Finding。旧同名文件使用旧附件缩进规则，不能作为当前合规依据。19 个 Word 回归案例（16 份不同 DOCX）的 gold 仍待业务人工复核。

## 本地页面与接口

安装基础依赖后运行：

```powershell
.\.venv\Scripts\python -m uvicorn document_checker.api:app --host 127.0.0.1 --port 8765
```

在浏览器打开 [本地模板管理页](http://127.0.0.1:8765/)。请从该地址打开，不要直接用 `file://` 打开 HTML。页面现可上传 DOCX 提取**候选属性**、确认并保存自定义规则、选模板执行真实格式和错字检查。自定义模板保存在本机 `data/templates/`，该目录不进入 Git。接口和当前边界见 [前后端联调说明](docs/frontend_backend_integration.md)。

错字精检默认不调用外部大模型；若已配置可用模型网关，设置 `DOCUMENT_CHECKER_USE_LLM=1` 后才尝试调用。报告会显示实际后端及未检查范围。逐页 PDF 预览和红黄坐标标注已接入，需安装 LibreOffice 并保证 `soffice` 可执行，或设置 `DOCUMENT_CHECKER_SOFFICE` 路径；本机开发环境可使用 `data/tools/lo-unpacked/` 中提取的渲染器。原 DOCX 修复下载尚未接入。

## 处理链路

```
Word 文件
  → docx_parser    解析层：段落/run/字体(中西文)/字号/行距/字符间距/缩进/页边距/页脚页码域
  → role_mapper    语义角色映射：① 样式/大纲级别 → ② 文本正则+位置 → ③ 字体启发式 → ④ LLM(预留)
  → rule_engine    规则引擎：加载 YAML（common + 文书类型两层合并），按 checker 名调度
  → checkers/*     检查器：注册表式可插拔，只依赖解析层数据结构
  → report         Markdown + JSON 双形态报告（规则/级别/位置/期望/实际/修复建议）
  → preview        LibreOffice 渲染 PDF；PyMuPDF 获取页图及文字坐标，前端红黄标注
```

## 规则 YAML 写法

```yaml
meta: {id: chengbaogao_dazi, name: 呈报稿（大字版）, version: "0.1"}
rules:
  - id: font-body            # 规则 id：common.yaml 同名 id 会被本文件覆盖（params 合并）
    name: 正文字体字号
    severity: error          # error / warning / info
    checker: font_format     # 对应 src/document_checker/checkers/ 里 @register("font_format")
    params:
      role: body             # 作用于哪个段落角色
      fonts: [方正仿宋_GBK, 方正仿宋GBK, 方正仿宋简体]   # 别名列表，归一化后匹配
      size_pt: 18
      bold: true
```

需求迭代原则上只改 YAML；`common.yaml` 放各文书类型通用规则（页码、标题序号、附件、落款）。

## 已实现检查器

| checker | 覆盖要求 |
|---|---|
| page_setup | 页边距 上3.8/下3.3/左2.7/右2.7 cm |
| font_format | 标题/正文/一二级标题的字体（含别名）、字号、加粗、对齐；西文仿宋 |
| line_spacing | 固定行距 32 磅（大字版）/ 29.5 磅（小字版） |
| char_spacing | 字符间距加宽 0.4 磅 / 标准 |
| page_number | "— 1 —"格式、一字线、居中、宋体四号、页脚底端距离 1.75cm |
| odd_even_setting | 奇偶页不同设置；奇偶页留字的视觉检测尚未实现 |
| heading_number | 一、／（一）／1.／（1）层级形式，三四级右侧不空格，正文可疑编号 |
| secrecy | 秘级位置（左上角顶格）、字体字号加粗、"秘 密"空一格 |
| attachment | 左空两字、前文空行、名称后不加标点 |
| signature | 署名/成文日期存在性与顺序、日期写法、下空二行；印章为 VLM 预留 |

## Synthetic Document Generator（正式造数据模块）

测试数据是一等公民，不是临时工作。闭环：

```
规则 YAML → 生成 Golden Document → 逐案例注入单点违规 → Checker → Gold 标注 → pytest
```

- **单一事实源**：`src/document_checker/synth/golden.py` 从规则 YAML 直接推导生成参数
  （字体/字号/加粗/边距/行距/字符间距/秘级/页码全部来自规则本身）。
  **需求变更 = 只改 YAML**，然后 `pytest` 重新生成并断言，生成器参数零手工同步。
- **变异注册表** `src/document_checker/synth/mutations.py`：12 个案例，每个案例 = 单点违规 +
  `expected_findings`（期望命中的规则 id，即 Gold 标注）。
- **批量产出** `src/document_checker/synth/corpus.py` / `document-checker synth --type dazi --outdir tests/corpus/dazi`：
  一份 `golden.docx` + 每案例一份 `wrong_<case_id>.docx` + `gold.json`。
- **pytest 闭环** `tests/test_synthetic.py`：
  golden 零 error（不许误报）；每个 wrong_* 期望规则 ⊆ 实际命中（不许漏报）；
  另有错字注入检测用例（启发式后端，不依赖模型/LLM，CI 可跑）。

```bash
document-checker synth --type dazi --outdir tests/corpus/dazi   # 生成语料
python -m pytest tests/ -q                                    # 回归断言
```

已验证的需求变更场景：把大字版行距从 32 磅改为 30 磅，**只改 YAML 一处**，
pytest 依旧全绿（Golden 自动按新参数生成）。

## 合成数据：两条内容生产线

**1. 内置模板**（`generate`）：手工内容模板，覆盖各级标题/附件/落款全要素。

**2. 真实公文导入**（`import`，推荐）：内容取自中国政府网公开公文附件
（`samples/public_raw/`，含《服务业发展资金管理办法》《科技馆免费开放补助资金管理办法》
《土壤污染防治基金管理办法》等），脚本抽取内容后按目标格式重排：

```bash
document-checker import samples/public_raw/服务业发展资金管理办法.docx \
    --type dazi --out samples/imported/服务业发展资金管理办法-大字版.docx
```

抽取映射：首个非空段→标题；"第X章 xx"→一级标题"X、xx"；"一、"→一级标题；
"（一）"→二级标题；"1."（短句）→三级标题；其余→正文；文末自动识别署名/日期；
文首"附件："引导行剔除；表格/图片暂不导入（会计数提示）。公开件不带秘级。

**3. 违规注入**（两条生产线通用）：`--violate` 支持 `title_font, body_font,
body_size, heading_bold, margin, spacing, char_spacing, page_number,
heading_num, attachment_punct, date_format, secrecy_bold`（旧名
`margin_left/line_spacing` 仍兼容）。

合规样本（含导入重排件）应零误报，注入的每类违规应全部命中。
**每次改规则或检查器后，`python -m pytest tests/` 即完成回归。**

## 错别字检查

链路：DOCX 解析 → 过滤和分句 → ChineseErrorDetectorElectra 初筛 → 4B 或显式配置的 27B 服务精检 → 校验、定位及报告。

本机真实 ELECTRA 初筛冒烟（未配置 4B/27B 时只测第 4 步）：

    python scripts/typo_model_smoke.py --detector-model-dir data/models/ChineseErrorDetectorElectra --device cpu

模型服务可用后，要求两个模型均真实运行，不允许回退：

    document-checker typo 文件.docx --detector-model-dir data/models/ChineseErrorDetectorElectra --device cuda --model twnlp/ChineseErrorCorrector4-4B --corrector-url http://127.0.0.1:8000/v1 --corrector-protocol corrected_text --require-models --json typo.json

ELECTRA 已在本机 CPU 用公开权重真实运行。4B/27B 尚无可用权重或服务；当前只完成 OpenAI 兼容服务的模拟测试，不能作为真实模型验收。普通模式下缺模型仍可退回词表验证链路，但报告标记为“未检查”；--require-models 会直接失败。4B 的官方输出是整句纠正结果，代码会剥离 think 段并逐字比对；27B 的 JSON 协议须与实际服务确认。

下载模型、服务部署、复现命令和边界见 [错字模型接入与验证](docs/typo_model_integration.md)。

## 已知边界与后续路线

- python-docx 只能读到 XML 里显式写的格式；真实公文若把格式设在样式链/主题里，
  需要补样式继承解析（当前只兜底了段落样式一层）。拿到真实样本后重点验证这里。
- 真实分页不可见（页码所在页、印章压字位置）→ 需 Word→PDF（LibreOffice）渲染 + VLM，
  `signature` 检查器里已留接口；`role_mapper.map_roles_llm` 为 LLM 兜底预留。
- 单双页页码分居（单页右空一字/双页左空一字）、红头、版记等规则未覆盖。
- 错别字检查链路（ELECTRA 粗筛 + 大模型精检）与本系统复用解析层和报告结构，
  作为独立子命令接入。

## 目录

```text
├── pyproject.toml           # 基础依赖、可选模型依赖、开发依赖、CLI 入口
├── main.py                  # 旧命令兼容入口（需先安装项目）
├── src/document_checker/
│   ├── cli.py               # check / generate / synth / import / typo / inject
│   ├── docx_parser.py       # DOCX → 文档 IR
│   ├── role_mapper.py       # 语义角色映射
│   ├── rule_engine.py       # YAML 加载与检查调度
│   ├── report.py            # 格式检查报告
│   ├── checkers/            # 格式检查器
│   ├── typo/                # 错别字流水线与模型适配
│   ├── synth/               # 样本生成、内容导入与违规注入
│   └── rules/               # 随包发布的默认 YAML 规则；--rules 可指定外部目录
├── tests/
├── docs/
└── samples/
```

基础安装只包含 DOCX 解析和 YAML。`detector` 与 `gateway` 是独立可选依赖；
没有模型时错别字命令仍可使用启发式后端，报告会显示实际后端。
