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

## 服务器 GPU 冒烟（2026-09-29，zzx 6×RTX 4090）

ELECTRA 权重由 Windows 本机 scp 直传（389 MB，revision b58d6b 字节级一致），服务器路径 `~/doc-format-checker/data/models/ChineseErrorDetectorElectra`，经 `CED_MODEL_DIR` 指定。CUDA 冒烟结果：设备 cuda，模型加载 4.8 秒（CPU 7.8 秒），四句批量推理 0.26 秒；检出与 CPU 完全一致（「布署」句标出布 0.98／署 0.898，「按排」句标出按 0.999，两句正常样本无嫌疑）。4B 精检仍为 not tested，待 vLLM 服务就绪。小批量下 GPU 无速度优势，吞吐优势需在 T-02 阈值标定时以大批量复测。

复现命令（服务器）：

    export CED_MODEL_DIR=~/doc-format-checker/data/models/ChineseErrorDetectorElectra
    .venv/bin/python scripts/typo_model_smoke.py --detector-model-dir $CED_MODEL_DIR --device cuda --threshold 0.8

## 4B 真实精检冒烟（2026-09-30，zzx GPU 5）

部署：vLLM 0.30 独立环境（`~/vllm-env`，与项目 venv 隔离），权重在 `~/models/ChineseErrorCorrector4-4B`，`--max-model-len 2048 --gpu-memory-utilization 0.9`，服务 `http://127.0.0.1:8000/v1`。启动期踩过 FlashInfer sampler JIT 与系统 nvcc 不兼容的坑，以 `VLLM_USE_FLASHINFER_SAMPLER=0` 回退 native sampler 解决。

结果：`typo_model_smoke.py --corrector-url http://127.0.0.1:8000/v1 --corrector-model twnlp/ChineseErrorCorrector4-4B --corrector-protocol corrected_text` 全链路通过——ELECTRA 筛出的两个嫌疑句分别得到 4B 修正「布→部」（offset 4）和「按→安」（offset 1），差分校验通过，corrector 字段显示 real service 而非回退。

实测数据：单句精检延迟约 **0.85 秒**（含 think 段，约 87 个补全 token）；vLLM 按 0.9 显存利用率预占，GPU 5 占用约 **42 GiB**。注意 zzx 是共享服务器，其余各卡也有 42–47 GiB 被他人任务占用——回答前端「并发与资源抢占」问题时须按共享环境估算。

已观察到的精度边界（不作结论，待 T-02 标定）：对「项目已经布署完成，请尽快按排检查」这种一句双错，4B 只改了「按排」漏了「布署」；ELECTRA 也会把正常的「检」字标过阈值（0.803）。

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
