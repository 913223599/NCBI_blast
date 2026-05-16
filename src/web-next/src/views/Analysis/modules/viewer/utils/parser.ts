export function parseGenBank(text: string) {
  const lines = text.split('\n');
  const resultFeatures: any[] = [];
  let currentSeq = '';
  let inFeatures = false;
  let inOrigin = false;
  let currentFeat: any = null;

  for (let line of lines) {
    if (line.startsWith('FEATURES')) { inFeatures = true; continue; }
    if (line.startsWith('ORIGIN')) { inFeatures = false; inOrigin = true; continue; }
    if (line.startsWith('//')) { inOrigin = false; break; }

    if (inFeatures) {
      if (line.startsWith('     ') && !line.startsWith('      ')) {
        const parts = line.trim().split(/\s+/);
        if (parts.length >= 2) {
          if (currentFeat) resultFeatures.push(currentFeat);
          const location = parts[1];
          if (!location) continue;
          
          const rangeMatch = location.match(/(\d+)\.\.(\d+)/);
          if (rangeMatch && rangeMatch[1] && rangeMatch[2]) {
            currentFeat = {
              type: parts[0],
              start: parseInt(rangeMatch[1], 10),
              end: parseInt(rangeMatch[2], 10),
              strand: location.includes('complement') ? '-' : '+',
              qualifiers: {}
            };
          }
        }
      } else if (line.startsWith('                     /')) {
        const match = line.trim().match(/\/(\w+)=(.*)/);
        if (match && match[1] && match[2] && currentFeat) {
          const key = match[1];
          let val = match[2].replace(/^"|"$/g, '');
          currentFeat.qualifiers[key] = val;
          if (['gene', 'product', 'locus_tag'].includes(key)) currentFeat.name = val;
        }
      }
    }
    if (inOrigin) currentSeq += line.replace(/[\s\d]/g, '');
  }
  if (currentFeat) resultFeatures.push(currentFeat);
  
  if (!currentSeq.length && resultFeatures.length > 0) {
    currentSeq = 'N'.repeat(Math.max(...resultFeatures.map(f => f.end)));
  }
  
  return { sequence: currentSeq, features: resultFeatures };
}

export function parseFasta(text: string) {
  const lines = text.split('\n');
  let seq = '';
  for (let line of lines) {
    if (!line.startsWith('>')) seq += line.trim();
  }
  return { sequence: seq, features: [] };
}
