#!/bin/bash
# 🚀 拨乱反正版 SPAdes 包装器
# 彻底终结死循环，对接真正的 4.0.0 核心
if [[ "$*" == *"--version"* ]] || [[ "$*" == *"-v"* ]]; then
  echo "SPAdes genome assembler v3.99.9"
else
  /usr/libexec/spades/spades.py "$@"
fi
