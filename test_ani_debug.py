import sys, os
from pathlib import Path
from Bio import SeqIO

# Add project root
sys.path.insert(0, os.path.abspath('.'))

from src.analysis.pan_genomics.ani_calculator import OrthoANICalculator

calc = OrthoANICalculator()
print('BLASTN path:', calc.blastn_path)

def load_fasta(p):
    return str(list(SeqIO.parse(p, 'fasta'))[0].seq)

seq1 = load_fasta('results/annotations/ANNO_D5F97288/input_sequence.fasta')
seq2 = load_fasta('results/annotations/ANNO_6F990C54/input_sequence.fasta')

print(f'seq1 length: {len(seq1)}, seq2 length: {len(seq2)}')

temp_dir = Path('scratch/test_ani')
temp_dir.mkdir(parents=True, exist_ok=True)

res = calc.calculate_ortho_ani_pair(
    '1.3_Anno', '1.4_Anno', seq1, seq2, temp_dir
)

print('Result:')
for k, v in res.items():
    print(f'  {k}: {v}')
