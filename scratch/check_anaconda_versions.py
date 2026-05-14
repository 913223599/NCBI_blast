import json
import urllib.request
import sys

tools = ["fastp", "kraken2", "unicycler", "spades", "vibrant", "bwa", "samtools", "checkv", "pharokka"]
channels = ["bioconda", "conda-forge"]

for tool in tools:
    latest_version = None
    for channel in channels:
        url = f"https://api.anaconda.org/package/{channel}/{tool}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                latest_version = data.get("latest_version")
                if latest_version:
                    break
        except Exception:
            pass
    print(f"{tool}: {latest_version}")
