#!/bin/bash
# 通过 NCBI Entrez API 查询 WGS accession 对应的生物体信息

for acc in DAGGVC01 CABGTA01 CABEJE01 JAKWGH01 DAFZUC01 DAFZUK01 DAFZUS01 DAFZVF01 DAFZYP01 DAFZYS01; do
    # WGS accession 前缀查 BioProject/organism
    result=$(curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=nuccore&term=${acc}[Accession]&retmode=json" 2>/dev/null)
    uid=$(echo "$result" | grep -o '"idlist":\["[0-9]*"' | grep -o '[0-9]*' | head -1)
    
    if [ -n "$uid" ]; then
        summary=$(curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=nuccore&id=${uid}&retmode=json" 2>/dev/null)
        organism=$(echo "$summary" | grep -o '"organism":"[^"]*"' | head -1 | cut -d'"' -f4)
        title=$(echo "$summary" | grep -o '"title":"[^"]*"' | head -1 | cut -d'"' -f4)
        echo "${acc} => Organism: ${organism:-Unknown} | Title: ${title:-N/A}"
    else
        echo "${acc} => [NCBI lookup failed]"
    fi
    sleep 0.5
done
