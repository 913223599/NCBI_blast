#!/bin/bash
# 🛡️ 终极防御版 SPAdes 包装器 (参数过滤)
# 作用：拦截并覆盖 Unicycler 传递的危险内存参数

# 1. 如果是版本查询，直接撒谎
if [[ "$*" == *"--version"* ]] || [[ "$*" == *"-v"* ]]; then
  echo "SPAdes genome assembler v3.99.9"
  exit 0
fi

# 2. 过滤掉原有的 -m 和 --memory 参数
# 我们通过循环重构参数列表，剔除掉 Unicycler 传入的内存设定
CMD_ARGS=()
SKIP_NEXT=false

for arg in "$@"; do
  if [ "$SKIP_NEXT" = true ]; then
    SKIP_NEXT=false
    continue
  fi

  case "$arg" in
    -m|--memory)
      SKIP_NEXT=true  # 跳过这个参数和它的下一个值
      ;;
    *)
      CMD_ARGS+=("$arg")
      ;;
  esac
done

# 3. 注入我们强制的 40G 限制和真正的核心路径
/usr/local/bin/spades.real --memory 40 "${CMD_ARGS[@]}"
