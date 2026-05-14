import os
import urllib.request
import gzip
import shutil
import subprocess

db_dir = "/root/.conda/envs/vibrant/share/vibrant-1.2.1/db/databases"
pfam_url = "ftp://ftp.ebi.ac.uk/pub/databases/Pfam/releases/Pfam32.0/Pfam-A.hmm.gz"
gz_path = os.path.join(db_dir, "Pfam-A.hmm.gz")
hmm_path = os.path.join(db_dir, "Pfam-A_v32.HMM")

print("Downloading Pfam-A.hmm.gz (approx 270MB)...")
try:
    urllib.request.urlretrieve(pfam_url, gz_path)
    print("Download completed.")
except Exception as e:
    print(f"Failed to download Pfam: {e}")
    # Try alternative approach using wget
    print("Trying wget...")
    subprocess.run(["wget", "-q", "-O", gz_path, pfam_url], check=True)
    print("Download completed via wget.")

print(f"Extracting to {hmm_path}...")
try:
    with gzip.open(gz_path, 'rb') as f_in:
        with open(hmm_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    print("Extraction successful.")
except Exception as e:
    print(f"Extraction failed: {e}")
    # Try gunzip
    print("Trying gunzip command...")
    subprocess.run(["gunzip", "-c", gz_path], stdout=open(hmm_path, 'wb'), check=True)
    print("Extraction successful via gunzip.")

print("Running hmmpress...")
conda_activate = "source /opt/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source /root/.conda/etc/profile.d/conda.sh 2>/dev/null; conda activate vibrant; hmmpress Pfam-A_v32.HMM"
try:
    subprocess.run(conda_activate, shell=True, executable='/bin/bash', cwd=db_dir, check=True)
    print("hmmpress completed successfully!")
except Exception as e:
    print(f"hmmpress failed: {e}")
