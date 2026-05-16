// 标准遗传密码子表 (Standard Genetic Code)
const CODON_TABLE: Record<string, string> = {
  'ATA':'I', 'ATC':'I', 'ATT':'I', 'ATG':'M',
  'ACA':'T', 'ACC':'T', 'ACG':'T', 'ACT':'T',
  'AAC':'N', 'AAT':'N', 'AAA':'K', 'AAG':'K',
  'AGC':'S', 'AGT':'S', 'AGA':'R', 'AGG':'R',
  'CTA':'L', 'CTC':'L', 'CTG':'L', 'CTT':'L',
  'CCA':'P', 'CCC':'P', 'CCG':'P', 'CCT':'P',
  'CAC':'H', 'CAT':'H', 'CAA':'Q', 'CAG':'Q',
  'CGA':'R', 'CGC':'R', 'CGG':'R', 'CGT':'R',
  'GTA':'V', 'GTC':'V', 'GTG':'V', 'GTT':'V',
  'GCA':'A', 'GCC':'A', 'GCG':'A', 'GCT':'A',
  'GAC':'D', 'GAT':'D', 'GAA':'E', 'GAG':'E',
  'GGA':'G', 'GGC':'G', 'GGG':'G', 'GGT':'G',
  'TCA':'S', 'TCC':'S', 'TCG':'S', 'TCT':'S',
  'TTC':'F', 'TTT':'F', 'TTA':'L', 'TTG':'L',
  'TAC':'Y', 'TAT':'Y', 'TAA':'*', 'TAG':'*',
  'TGC':'C', 'TGT':'C', 'TGA':'*', 'TGG':'W',
};

const COMPLEMENT_MAP: Record<string, string> = { 
  'A':'T', 'T':'A', 'C':'G', 'G':'C', 
  'a':'t', 't':'a', 'c':'g', 'g':'c',
  'N':'N', 'n':'n'
};

export function reverseComplement(seq: string) {
  return seq.split('').reverse().map(c => COMPLEMENT_MAP[c] || c).join('');
}

export function translateDNA(dnaSequence: string): string {
  let aa = '';
  for (let i = 0; i < dnaSequence.length - 2; i += 3) {
    const codon = dnaSequence.substring(i, i + 3).toUpperCase();
    aa += CODON_TABLE[codon] || 'X';
  }
  return aa;
}

export function extractFeatureSequence(rawSequence: string, start: number, end: number, strand: string): string {
  if (!rawSequence) return '';
  // 1-based start, end inclusive
  const seq = rawSequence.substring(start - 1, end);
  return strand === '-' ? reverseComplement(seq) : seq;
}
