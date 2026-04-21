#!/bin/bash
set -e

QUERY="/ncbi_blast_link/results/assembly/AS_1776601910417/consensuscorrectionstep/polished_assembly.fasta"
DB_DIR="/ncbi_blast_link/database"
OUT="/ncbi_blast_link/results/assembly/AS_1776601910417/phageannotationstep/Host_Prediction_Plan_B.tsv"
TMP_ALL="/tmp/all_chunk_hits.tsv"

> "$TMP_ALL"

for i in $(seq -w 1 9); do
    CHUNK="$DB_DIR/chunk_0${i}.msh"
    echo "[Chunk $i/9] Querying $CHUNK ..."
    mash dist -p 16 "$CHUNK" "$QUERY" 2>/dev/null | sort -t'	' -k3 -g | head -n 20 >> "$TMP_ALL"
    echo "[Chunk $i/9] Done."
done

echo "[Merge] Ranking all hits..."
sort -t'	' -k3 -g "$TMP_ALL" | head -n 50 > /tmp/final_top.tsv

echo "[Write] Building report..."
printf 'Rank\tAccession\tSimilarity\tDistance\tP_Value\tHashes\n' > "$OUT"
rank=0
while IFS='	' read -r ref query dist pval hashes; do
    rank=$((rank+1))
    acc=$(echo "$ref" | cut -d'.' -f1)
    sim=$(echo "scale=2; (1 - $dist) * 100" | bc)
    printf '%s\t%s\t%s%%\t%s\t%s\t%s\n' "$rank" "$acc" "$sim" "$dist" "$pval" "$hashes"
done < /tmp/final_top.tsv >> "$OUT"

echo ""
echo "=== TOP 10 ==="
head -n 11 "$OUT" | column -t -s'	'
rm -f "$TMP_ALL" /tmp/final_top.tsv
