#!/bin/bash
# 🛡️ 稳健生存版 SPAdes 包装器 (24G 限制)
# 针对 30G WSL 容器优化，防止 OOM 导致的静默失败

if [[ "$*" == *"--version"* ]] || [[ "$*" == *"-v"* ]]; then
  echo "SPAdes genome assembler v3.99.9"
  exit 0
fi

CMD_ARGS=()
SKIP_NEXT=false

for arg in "$@"; do
  if [ "$SKIP_NEXT" = true ]; then
    SKIP_NEXT=false
    continue
  fi

  case "$arg" in
    -m|--memory)
      SKIP_NEXT=true
      ;;
    *)
      CMD_ARGS+=("$arg")
      ;;
  esac
done

# 强制限制在 24G，确保 SPAdes 在 30G 的 WSL 容器内安全运行
/usr/local/bin/spades.real --memory 24 "${CMD_ARGS[@]}"
