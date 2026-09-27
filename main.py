"""兼容旧命令：安装项目后可继续运行 python main.py。"""
from document_checker.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
