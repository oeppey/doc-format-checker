# 错字模型接入与本轮验证

更新：2026-09-29。此文记录第 4 步 ELECTRA 初筛和第 5 步 4B/27B 精检的实际状态。印章不在本轮范围。

## 当前状态

| 环节 | 本轮结果 | 尚未验证 |
|---|---|---|
| ChineseErrorDetectorElectra | 下载公开权重，Windows CPU 上真实加载并对中文句子推理；模型文件在 Git 忽略的 data/models/ChineseErrorDetectorElectra | NVIDIA Linux 的 CUDA 推理、吞吐与并发；真实卷宗上的阈值 |
| ChineseErrorCorrector4-4B | 已接 OpenAI 兼容服务协议；解析官方模型的 think 段和改正后的整句；模拟 HTTP 服务测试通过 | 当前没有 4B 权重/服务，未进行真实 4B 推理 |
| 现有 27B | 已接显式指定的 OpenAI 兼容服务与 JSON 返回协议；模拟 HTTP 服务测试通过 | 服务地址、模型名、访问权限和实际返回协议尚未提供，未进行真实 27B 推理 |
| 降级与报告 | CLI 可用 --require-models 要求两个真实模型；缺任一模型时失败，不把词表回退当作模型验收 | 前端/接口是否默认启用严格模式，待部署策略确认 |

模型资料：[ELECTRA 模型页](https://huggingface.co/xurong123/ChineseErrorDetectorElectra)、[4B 模型页及 OpenAI 兼容示例](https://huggingface.co/twnlp/ChineseErrorCorrector4-4B)、[4B 官方推理适配](https://github.com/TW-NLP/ChineseErrorCorrector/blob/main/ChineseErrorCorrector/llm/infer/openai_infer.py)。

## 已运行的真实初筛冒烟

使用 ELECTRA 仓库 revision b58d6bdbc60b4f308352ff7c87a8dd419c4019be，阈值 0.8，CPU，四句一批。模型加载约 7.8 秒，批量推理约 0.20 秒。两句正常样本未进入嫌疑队列；“布署”“按排”所在的两句进入队列。另用这四句生成临时 DOCX 运行完整 Word 入口：共 4 句、ELECTRA 嫌疑 2 句、失败 0 句；启发式纠错给出 2 处建议，报告状态为“未检查”并明确注明 4B/27B 精检未执行。个别无关字符也超过阈值，不能据此宣布字级定位或精度合格。阈值 0.8 只用于冒烟，不是正式标定值。

复现命令（Windows 本地）：

    .venv\Scripts\python.exe scripts/typo_model_smoke.py --detector-model-dir data/models/ChineseErrorDetectorElectra --device cpu --threshold 0.8

脚本仅在提供 --corrector-url 与 --corrector-model 后调用真实精检服务；未提供时输出明确的 not tested。

## 在 NVIDIA Linux 开发服务器上运行

1. 建立 Python 3.11+ 环境并安装项目及 detector 可选依赖。PyTorch 应按服务器 CUDA/驱动环境安装兼容版本，再执行：

       pip install -e ".[detector,dev]"

2. 下载同一版本的 ELECTRA 到服务器本地目录：

       python -c "from huggingface_hub import snapshot_download; snapshot_download('xurong123/ChineseErrorDetectorElectra', revision='b58d6bdbc60b4f308352ff7c87a8dd419c4019be', local_dir='data/models/ChineseErrorDetectorElectra', allow_patterns=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt'])"

3. 如选择 4B，先在可用的 GPU 环境单独部署 OpenAI 兼容服务。官方模型页给出 vLLM serve 示例。示例：

       vllm serve twnlp/ChineseErrorCorrector4-4B --host 127.0.0.1 --port 8000

   4B 服务与本项目可在同机不同进程。显存、并发和超时参数须根据服务器资源实测。若改用现有 27B 服务，请取得其 OpenAI 兼容地址、准确模型名及返回协议；若其输出不是 JSON，需先适配该协议。

4. 对 4B 做真实冒烟：

       python scripts/typo_model_smoke.py --detector-model-dir data/models/ChineseErrorDetectorElectra --device cuda --threshold 0.8 --corrector-url http://127.0.0.1:8000/v1 --corrector-model twnlp/ChineseErrorCorrector4-4B --corrector-protocol corrected_text

5. 检查 DOCX 且禁止回退：

       document-checker typo case.docx --detector-model-dir data/models/ChineseErrorDetectorElectra --device cuda --model twnlp/ChineseErrorCorrector4-4B --corrector-url http://127.0.0.1:8000/v1 --corrector-protocol corrected_text --require-models --json typo.json

可用环境变量：CED_MODEL_DIR、DOCUMENT_CHECKER_CORRECTOR_BASE_URL、DOCUMENT_CHECKER_CORRECTOR_MODEL、DOCUMENT_CHECKER_CORRECTOR_PROTOCOL、DOCUMENT_CHECKER_CORRECTOR_TIMEOUT_S、DOCUMENT_CHECKER_CORRECTOR_API_KEY。凭证只放服务环境变量，不写进命令、报告或仓库。使用 27B 时明确设定 --corrector-protocol json；这只是本项目约定，需按真实服务返回确认。

## 结果解释与待办

ELECTRA 是句子门控，嫌疑字符用于提示及定位，不应直接当作确定错字。4B 返回的整句要经过差分和单处修改校验；整句重写、受保护术语修改、无效服务响应计为精检失败。纯插入/删除会产生零长度原文或建议，前端高亮还需单独约定可视锚点。

当前 Word 错字流水线仍过滤部分句子，页脚也未纳入错字检查；报告状态会显示未检查范围。上线前需用人工标注集核对召回和误报，并在 NVIDIA 服务器记录 GPU 显存、延迟、批量大小与并发。当前模拟服务测试只证明接口与定位流程，不能代替 4B/27B 真实模型验收。
