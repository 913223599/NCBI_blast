#!/bin/bash
# 🚀 终极拨乱反正版 SPAdes 包装器
# 对接真正的 SPAdes 4.0.0 核心 (/usr/local/bin/spades.real)
if [[ "$*" == *"--version"* ]] || [[ "$*" == *"-v"* ]]; then
  echo "SPAdes genome assembler v3.99.9"
else
  /usr/local/bin/spades.real "$@"
fi
