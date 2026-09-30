# 开发服务器迁移记录（2026-09-29）

> 本文记录项目从 Windows 开发机迁移到 NVIDIA Linux 开发服务器的完整操作、
> 遇到的问题与解法、最终状态和遗留事项。后续更新服务器代码见文末「日常维护」。

## 一、目标环境探测结果

| 项 | 值 |
|---|---|
| 主机 | zzx（120.195.114.115），超微 ESC8000-G4 |
| 账户 | ybzhao（SSH 公钥免密，本机 `~/.ssh/id_ed25519.pub` 已授权） |
| OS | Ubuntu 22.04.5 LTS，locale zh_CN.UTF-8 |
| GPU | 6× NVIDIA GeForce RTX 4090 |
| 系统 Python | 3.10.12（**不满足项目 ≥3.11**，见问题 2） |
| LibreOffice | 7.3.7.2（/usr/bin/soffice，已装） |
| 外网 | pypi.org、github.com 均可达（但 git 克隆慢，见问题 3） |

## 二、迁移步骤与问题处理

### 1. SSH 免密

本机公钥追加到服务器 `~/.ssh/authorized_keys`（账户 ybzhao 本人操作）。
注意：曾误加到其他账户时的撤销命令为
`sed -i '/<公钥指纹>/d' ~/.ssh/authorized_keys`，只删匹配行、不动其他 key。

### 2. 问题：SSH 报 `remote port forwarding failed for listen port 17890`

本机 `~/.ssh/config` 或 VSCode 会话带有端口转发，与服务器既有监听冲突。
**解法：所有 ssh/scp 命令加 `-o ClearAllForwardings=yes`。**

### 3. 问题：服务器上 `git clone https://github.com/...` 挂起

服务器访问 GitHub 的 git 协议不稳定（且私有仓库会卡在凭据提示）。
**解法：本机 `git bundle create repo.bundle --all` 打包完整历史，scp 上传后
`git clone repo.bundle doc-format-checker`。** 代价：服务器仓库的 origin 指向
bundle 文件，后续更新用增量 bundle（见「日常维护」）。

### 4. 问题：系统 Python 3.10，无 sudo 免密

**解法：用户空间安装 uv（`curl -LsSf https://astral.sh/uv/install.sh | sh`），
`uv python install 3.11` 得到 3.11.16，完全不动系统 Python、不需要 sudo。**
备选：有 sudo 时 `apt install python3.11 python3.11-venv`（22.04 源里有候选版本）。

### 5. 虚拟环境与依赖

```bash
cd ~/doc-format-checker
export PATH=$HOME/.local/bin:$PATH
uv venv --python 3.11 .venv
```

依赖安装遇到三个连环问题：

1. **官方 PyPI 极慢**（torch＋CUDA 组件约 3–4 GB，实测约 1 MB/s）→
   换阿里云镜像 `UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`。
2. **镜像滞后于 requirements.lock**：lock 里钉的是 2026 年新版本
   （如 regex==2026.9.29），镜像尚未同步，解析失败 →
   放弃精确锁定，改按 pyproject 范围安装
   `uv pip install --python .venv/bin/python -e ".[dev,detector]"`。
   requirements.lock 保留作参考，不作为服务器安装依据。
3. **远程自杀式 pkill**：`pkill -f 'uv pip install'` 的模式匹配到了
   执行该命令的远程 shell 自身（命令行里含同样字符串），SSH 连接被自己掐断 →
   改用 `pkill -f '[u]v pip install'` 或按 PID kill。

大下载放后台执行并轮询：
`nohup env UV_INDEX_URL=... uv pip install ... > /tmp/pip-install.log 2>&1 &`

## 三、最终状态与验证

| 验证项 | 结果 |
|---|---|
| 代码版本 | `b331a6c`（与 GitHub 远程一致） |
| Python | 3.11.16（uv 管理的独立解释器） |
| torch | 2.14.0+cu130，`torch.cuda.is_available() = True` |
| 基线测试 | **161 passed，36 秒**（Windows 同 suite 约 85–117 秒） |
| 关键 import | torch / fastapi / python-docx / PyYAML / pymupdf 全部正常 |

## 四、遗留事项

| 事项 | 状态 | 负责人 |
|---|---|---|
| 方正字体（仿宋_GBK、小标宋_GBK、黑体/楷体 GBK、宋体） | **未安装**，fc-list 为 0；不装则 PDF 预览分页与坐标和用户 Word 不一致。字体文件放 `~/.fonts/` 后 `fc-cache -f`，注意授权 | 用户提供字体 |
| ELECTRA 权重 | 未上传；上服务器后设 `CED_MODEL_DIR` | 待做 |
| 4B／27B 精检服务 | 权重来源待定；用 vLLM 起 OpenAI 兼容服务后配置 `DOCUMENT_CHECKER_CORRECTOR_*` | 待做 |
| 服务器 git 远程 | origin 指向本地 bundle；更新走增量 bundle（见下） | 约定如此 |

## 五、日常维护

### 更新服务器代码（增量 bundle）

本机：

```bash
git bundle create /tmp/update.bundle b331a6c..refactor/package-layout
scp -o ClearAllForwardings=yes /tmp/update.bundle zzx:~/
```

服务器：

```bash
cd ~/doc-format-checker
git fetch ../update.bundle refactor/package-layout
git merge --ff-only FETCH_HEAD
```

（`b331a6c` 换成服务器当前所在的提交。）

注意：**不要往服务器仓库目录里直接 scp 单个文件**——未跟踪文件会阻塞后续
`git merge`（报「未跟踪的文件将会因为合并操作而被覆盖」）。临时传脚本请放
仓库外（如 `~/tmp/`），正式改动一律走 bundle。

### 常用环境变量

| 变量 | 用途 |
|---|---|
| `CED_MODEL_DIR` | ELECTRA 权重目录 |
| `DOCUMENT_CHECKER_USE_LLM=1` | 启用精检 |
| `DOCUMENT_CHECKER_CORRECTOR_BASE_URL` / `_MODEL` / `_API_KEY` / `_PROTOCOL` / `_TIMEOUT_S` | OpenAI 兼容精检服务配置 |
| `DOCUMENT_CHECKER_SOFFICE` | soffice 路径（已在 PATH 可免设） |
| `DOCUMENT_CHECKER_CORS_ORIGINS` | 前端跨域来源 |
| `DOCUMENT_CHECKER_MAX_REVIEWS` | 审查并发上限（默认 1） |

### 启动服务

```bash
cd ~/doc-format-checker && source .venv/bin/activate
python -m uvicorn document_checker.api:app --host 0.0.0.0 --port 8765
```
