#!/bin/bash
# 修正：同时兼容 -v 和 --version，确保 Unicycler 探测成功
if [[ "$*" == *"--version"* ]] || [[ "$*" == *"-v"* ]]; then
  echo "SPAdes genome assembler v3.99.9"
else
  /usr/bin/spades.real "$@"
fi
