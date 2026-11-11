#!/bin/bash
export SHELL=/bin/bash
source /opt/miniconda3/etc/profile.d/conda.sh 2>/dev/null
conda activate virsorter2
exec virsorter "$@"
