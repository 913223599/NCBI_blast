import os
from Bio import SeqIO
from Bio.Seq import Seq

def load_fasta(path):
    recs = list(SeqIO.parse(path, 'fasta'))
    seq = str(recs[0].seq)
    return seq

samples = {
    '1.1': 'results/annotations/ANNO_8F7D6620/input_sequence.fasta',
    '1.2': 'results/annotations/ANNO_70F218CB/input_sequence.fasta',
    '1.3': 'results/annotations/ANNO_D5F97288/input_sequence.fasta',
    '1.4': 'results/annotations/ANNO_6F990C54/input_sequence.fasta',
}

seqs = {}
for name, p in samples.items():
    if os.path.exists(p):
        s = load_fasta(p)
        seqs[name] = s
        print(f'{name}: len = {len(s)}')

print('\nDirect comparisons:')
print('1.1 == 1.3?', seqs['1.1'] == seqs['1.3'])
print('1.2 == 1.4?', seqs['1.2'] == seqs['1.4'])
print('1.1 == 1.2?', seqs['1.1'] == seqs['1.2'])
print('1.1 == rc(1.2)?', seqs['1.1'] == str(Seq(seqs['1.2']).reverse_complement()))
print('1.3 == rc(1.4)?', seqs['1.3'] == str(Seq(seqs['1.4']).reverse_complement()))

# What about 1.1 vs 1.2? If not exact RC, what is the relation?
s1 = seqs['1.1']
s2 = seqs['1.2']
rc_s2 = str(Seq(s2).reverse_complement())

# Check overlap or subslice:
print(f'Length 1.1: {len(s1)}, Length 1.2: {len(s2)}')
if s2 in s1:
    print('1.2 is exact substring of 1.1 at pos:', s1.find(s2))
if rc_s2 in s1:
    print('rc(1.2) is exact substring of 1.1 at pos:', s1.find(rc_s2))

# Check BLAST or local alignment
overlap = 0
for i in range(len(s1)):
    if s1[i:i+100] in s2:
        overlap += 1
print(f'100bp k-mer match count (s1 in s2): {overlap}')

overlap_rc = 0
for i in range(len(s1)):
    if s1[i:i+100] in rc_s2:
        overlap_rc += 1
print(f'100bp k-mer match count (s1 in rc(s2)): {overlap_rc}')
