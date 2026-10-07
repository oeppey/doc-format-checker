# NVIDIA 服务器部署手册（错字检查全链路）

适用场景：把 doc-format-checker 部署到一台新的 NVIDIA Linux 服务器，4B 与另一个模型服务共享一张 GPU。
本手册是 2026-09-29 ~ 10-02 在 zzx 服务器（120.195.114.115）实际操作的复刻版。
预计耗时：1~2 小时（不含模型下载）。

## 0. 开始前先拿到三个信息

| 信息 | 问谁 | 本例的值 |
|---|---|---|
| 分给你用的 GPU 编号 | 管理员 | 5 |
| 共享卡上已被占用的显存 | `nvidia-smi` 自查 | 邻居占约 25.5G |
| 可对外开放的端口 | 管理员 | 8765（需防火墙放行） |

## 1. 代码与 Python 环境

```bash
git clone git@github.com:oeppey/doc-format-checker.git
cd doc-format-checker
python3.11 -m venv .venv                    # 或用 uv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install -e ".[detector]"      # torch + transformers（Linux 默认 CUDA 版）
.venv/bin/python -c "import torch; print(torch.cuda.is_available())"   # 期望 True
.venv/bin/python -m pytest -q               # 基线：全部通过再继续
```

## 2. ELECTRA 权重（389M，不入库，需手动传）

权重无训练流水线，从现有环境直接复制（二选一）：

```bash
# 从 zzx 服务器（源）
scp -r ybzhao@120.195.114.115:~/doc-format-checker/data/models/ChineseErrorDetectorElectra \
    data/models/ChineseErrorDetectorElectra

# 或从 Windows 本机（源）
scp -r D:/zyb/Projects/doc-format-checker/data/models/ChineseErrorDetectorElectra \
    <用户>@<新服务器>:~/doc-format-checker/data/models/
```

校验：目录内应有 `model.safetensors`、`config.json`、`tokenizer.json` 等 5 个文件，总约 389M。

## 3. 4B 权重下载（7.6G）

```bash
mkdir -p ~/models
# ModelScope（国内推荐）或 HuggingFace 二选一
pip install modelscope
modelscope download --model twnlp/ChineseErrorCorrector4-4B \
    --local_dir ~/models/ChineseErrorCorrector4-4B
```

校验：两个 safetensors 分片 + index.json + tokenizer 文件齐全，总约 7.6G。

## 4. vLLM 独立环境（不要装进项目 .venv）

```bash
python3.11 -m venv ~/vllm-env
~/vllm-env/bin/pip install vllm==0.30.0
```

架构原则：vLLM 服务与项目环境分离，项目只通过 HTTP 调用模型。

## 5. 启动 4B 服务（共享卡的关键参数）

```bash
CUDA_VISIBLE_DEVICES=<GPU编号> \
VLLM_USE_FLASHINFER_SAMPLER=0 \
nohup ~/vllm-env/bin/vllm serve ~/models/ChineseErrorCorrector4-4B \
  --served-model-name twnlp/ChineseErrorCorrector4-4B \
  --host 127.0.0.1 --port 8000 \
  --max-model-len 2048 --max-num-seqs 4 \
  --gpu-memory-utilization 0.35 --seed 42 \
  > ~/chinese_corrector.log 2>&1 &
```

| 参数 | 为什么 |
|---|---|
| `VLLM_USE_FLASHINFER_SAMPLER=0` | **必须**。FlashInfer sampler 的 JIT 编译在该服务器 nvcc 下失败（--compress-mode=size 不支持），不加会在引擎初始化最后阶段崩溃，且报错看起来像 OOM |
| `--gpu-memory-utilization 0.35` | 共享卡：4B 实占约 16.6G，给邻居留空间；邻居先占了就相应调低 |
| `--max-num-seqs 4` | 并发上限保守，配合项目端 MAX_REVIEWS=1 足够 |
| `--host 127.0.0.1` | 模型服务不直接对外，只有本机的审查 API 调它 |

观察日志直到出现 `Application startup complete`（首次约 1~2 分钟）。

## 6. 验证 4B（两层）

```bash
# 第一层：服务活着
curl -s http://127.0.0.1:8000/v1/models
# 期望返回含 "twnlp/ChineseErrorCorrector4-4B"；访问 / 返回 404 是正常的

# 第二层：真的会纠错
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"twnlp/ChineseErrorCorrector4-4B",
       "messages":[{"role":"user","content":"你是一名中文文本纠错专家。请纠正下面句子中的错误，只输出纠正后的句子：对待每一项工作都要一丝不够。"}],
       "temperature":0,"max_tokens":128}'
# 期望 choices[0].message.content ≈ 「对待每一项工作都要一丝不苟。」
```

## 7. 项目侧端到端验证

```bash
cd ~/doc-format-checker
export CED_MODEL_DIR=$HOME/doc-format-checker/data/models/ChineseErrorDetectorElectra
.venv/bin/python scripts/typo_model_smoke.py \
  --device cuda --threshold 0.8 \
  --corrector-url http://127.0.0.1:8000/v1 \
  --corrector-model twnlp/ChineseErrorCorrector4-4B \
  --corrector-protocol corrected_text
# 期望：ELECTRA 初筛 + 4B 精检全链路跑通，失败 0 句
```

## 8. 启动审查 API

```bash
bash scripts/start_api.sh --port 8765
# 脚本：环境变量默认值、杀旧进程、nohup、PID、健康检查
# 成功标志：打印「API 已启动」并给出 http://<IP>:8765/
```

需要开机自启 + 崩溃自愈时，建 systemd 用户服务（需管理员已开 linger）：

```ini
# ~/.config/systemd/user/document-checker.service
[Unit]
Description=Document checker API
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/<用户>/doc-format-checker
Environment=CED_MODEL_DIR=/home/<用户>/doc-format-checker/data/models/ChineseErrorDetectorElectra
Environment=DOCUMENT_CHECKER_USE_LLM=1
Environment=DOCUMENT_CHECKER_CORRECTOR_BASE_URL=http://127.0.0.1:8000/v1
Environment=DOCUMENT_CHECKER_CORRECTOR_MODEL=twnlp/ChineseErrorCorrector4-4B
Environment=DOCUMENT_CHECKER_CORRECTOR_PROTOCOL=corrected_text
ExecStart=/home/<用户>/doc-format-checker/.venv/bin/python -m uvicorn document_checker.api:app --host 0.0.0.0 --port 8765
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now document-checker.service
```

## 9. 端口与转发

| 端口 | 绑定 | 用途 | 对外 |
|---|---|---|---|
| 8000 | 127.0.0.1 | 4B 模型服务 | 不对外 |
| 8765 | 0.0.0.0 | 审查 API＋前端页面 | 需防火墙放行 |

```bash
# 确认绑定口径：显示 0.0.0.0:8765 才具备外网条件
ss -tln | grep 8765

# 防火墙放行（管理员执行；知道对方出口 IP 时建议限定来源）
sudo ufw allow 8765/tcp
# 或 sudo ufw allow from <对方IP> to any port 8765 proto tcp

# 防火墙未放行前的本机访问方式（SSH 隧道，效果等同公网）
ssh -L 8765:127.0.0.1:8765 <用户>@<服务器IP>
# 然后浏览器打开 http://127.0.0.1:8765/
```

前端无需任何配置：API 自带静态页托管，前端走相对路径 `/api`，同域同源。

## 10. 故障速查

| 现象 | 原因与处理 |
|---|---|
| vLLM 启动报 `Engine initialization failed` | 沿 traceback 找最底层第一条错误；是 FlashInfer/nvcc 就加 `VLLM_USE_FLASHINFER_SAMPLER=0` |
| CUDA OOM | 邻居占显存过多：降 `--gpu-memory-utilization`（0.35→0.25）或换卡 |
| 审查报告错字区显示「未检查」 | 看报告头部检测器/精检行：heuristic 说明 `CED_MODEL_DIR` 或 4B 环境变量没配上 |
| 首次审查 10 秒+、后续 5 秒 | 正常（ELECTRA 每请求加载）；生产化再改常驻 |
| 页面 404 只有 favicon | 无害，页面本身正常 |
| 外网超时但 `ss` 显示 0.0.0.0 | 防火墙未放行，与 28000/38000 等已放行端口对照确认 |

## 11. 安全提醒

API 无鉴权、HTTP 明文。公文内容敏感：公网开放务必限定来源 IP，正式使用建议 HTTPS。
