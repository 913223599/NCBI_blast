#!/bin/bash
METAFILE="/mnt/f/NCBI blast/database/Prophage.3281395sequence.metadata.tsv"

for acc in DAGGVC010000033 CABGTA010000012 CABEJE010000005 JAKWGH010000023 DAFZUC010000017 DAFZUK010000079 DAFZUS010000014 DAFZVF010000060 DAFZYP010000009 DAFZYS010000086; do
    result=$(grep -m1 "$acc" "$METAFILE" 2>/dev/null)
    if [ -n "$result" ]; then
        echo "$acc => $result"
    else
        echo "$acc => [Not in local metadata]"
    fi
done
