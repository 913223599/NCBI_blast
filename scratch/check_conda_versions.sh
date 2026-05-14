#!/bin/bash
/opt/miniconda3/bin/conda search -c bioconda fastp kraken2 unicycler spades checkv pharokka bwa samtools | awk '$1 ~ /^(fastp|kraken2|unicycler|spades|checkv|pharokka|bwa|samtools)$/ {print $1, $2}' | sort -V | awk '
{
  if ($1 != prev_pkg) {
    if (prev_pkg != "") print prev_pkg, last_ver
    prev_pkg = $1
  }
  last_ver = $2
}
END { print prev_pkg, last_ver }'
