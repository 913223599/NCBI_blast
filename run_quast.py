import os
import subprocess

def run_quast():
    quast_path = "/tmp/quast/quast.py"
    ref = "/ncbi_blast_link/test_data/ref_staph.fasta"
    
    # Check outputs
    base_dir = "/ncbi_blast_link/results/assembly/test_SRR37941745_lytic"
    
    bash_cmd = f"""
    target=""
    for c in "{base_dir}/assembly.polished.fasta" "{base_dir}/assembly.filled.fasta" "{base_dir}/scaffolds.fasta" "{base_dir}/assembly.fasta"; do
        if [ -f "$c" ]; then
            target="$c"
            break
        fi
    done
    
    if [ -z "$target" ]; then
        echo "No assembly output found!"
        exit 1
    fi
    
    echo "Running QUAST on $target vs {ref}"
    python3 {quast_path} "$target" -r "{ref}" -o "{base_dir}/quast_report"
    """
    
    cmd = ["wsl", "-d", "Ubuntu", "-u", "root", "bash", "-c", bash_cmd]
    subprocess.run(cmd)
    
    print("QUAST evaluation finished.")

if __name__ == "__main__":
    run_quast()
