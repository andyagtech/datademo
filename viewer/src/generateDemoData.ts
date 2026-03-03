import type { DiffRow, DiffSummary, DiffStatus } from './types';

const COLUMNS = [
  'DESYNPUF_ID', 'BENE_BIRTH_DT', 'BENE_DEATH_DT', 'BENE_SEX_IDENT_CD',
  'BENE_RACE_CD', 'BENE_ESRD_IND', 'SP_STATE_CODE', 'BENE_COUNTY_CODE',
  'BENE_HI_CVRAGE_TOT_MONS', 'BENE_SMI_CVRAGE_TOT_MONS', 'BENE_HMO_CVRAGE_TOT_MONS',
  'PLAN_CVRG_MOS_NUM', 'MEDREIMB_IP', 'BENRES_IP', 'PPPYMT_IP',
  'MEDREIMB_OP', 'BENRES_OP', 'PPPYMT_OP', 'MEDREIMB_CAR', 'BENRES_CAR',
  'PPPYMT_CAR', 'SP_ALZHDMTA', 'SP_CHF', 'SP_CHRNKIDN', 'SP_CNCR',
  'SP_COPD', 'SP_DEPRESSN', 'SP_DIABETES', 'SP_ISCHMCHT', 'SP_OSTEOPRS',
  'SP_RA_OA', 'SP_STRKETIA',
];

const KEY_COLUMN = 'DESYNPUF_ID';

function randomId(): string {
  return Math.random().toString(36).substring(2, 18).toUpperCase();
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomDate(): string {
  const y = randomInt(1920, 2000);
  const m = String(randomInt(1, 12)).padStart(2, '0');
  const d = String(randomInt(1, 28)).padStart(2, '0');
  return `${y}${m}${d}`;
}

function randomMoney(): string {
  return (Math.random() * 50000).toFixed(2);
}

function randomBinary(): string {
  return Math.random() > 0.7 ? '1' : '2';
}

function generateRowValues(): Record<string, string> {
  const vals: Record<string, string> = {};
  vals['DESYNPUF_ID'] = randomId();
  vals['BENE_BIRTH_DT'] = randomDate();
  vals['BENE_DEATH_DT'] = Math.random() > 0.85 ? randomDate() : '';
  vals['BENE_SEX_IDENT_CD'] = Math.random() > 0.5 ? '1' : '2';
  vals['BENE_RACE_CD'] = String(randomInt(1, 5));
  vals['BENE_ESRD_IND'] = Math.random() > 0.95 ? 'Y' : '0';
  vals['SP_STATE_CODE'] = String(randomInt(1, 53)).padStart(2, '0');
  vals['BENE_COUNTY_CODE'] = String(randomInt(1, 999)).padStart(3, '0');

  for (const col of COLUMNS) {
    if (vals[col] !== undefined) continue;
    if (col.startsWith('MEDREIMB') || col.startsWith('BENRES') || col.startsWith('PPPYMT')) {
      vals[col] = randomMoney();
    } else if (col.includes('MONS') || col.includes('MOS')) {
      vals[col] = String(randomInt(0, 12));
    } else if (col.startsWith('SP_')) {
      vals[col] = randomBinary();
    } else {
      vals[col] = String(randomInt(0, 100));
    }
  }
  return vals;
}

function mutateValues(original: Record<string, string>): {
  newVals: Record<string, string>;
  diffCols: string[];
} {
  const newVals = { ...original };
  const diffCols: string[] = [];
  const mutableCols = COLUMNS.filter(c => c !== KEY_COLUMN);

  // Mutate 1-5 random columns
  const numMutations = randomInt(1, 5);
  const shuffled = mutableCols.sort(() => Math.random() - 0.5).slice(0, numMutations);

  for (const col of shuffled) {
    if (col.startsWith('MEDREIMB') || col.startsWith('BENRES') || col.startsWith('PPPYMT')) {
      newVals[col] = (parseFloat(original[col]) + (Math.random() - 0.5) * 1000).toFixed(2);
    } else if (col.startsWith('SP_')) {
      newVals[col] = original[col] === '1' ? '2' : '1';
    } else if (col.includes('DT')) {
      newVals[col] = randomDate();
    } else {
      newVals[col] = String(randomInt(0, 100));
    }
    diffCols.push(col);
  }

  return { newVals, diffCols };
}

export function generateDemoData(totalRows: number = 5000): {
  rows: DiffRow[];
  summary: DiffSummary;
} {
  const rows: DiffRow[] = [];
  const columnDiffCounts: Record<string, number> = {};
  COLUMNS.forEach(c => { columnDiffCounts[c] = 0; });

  let matchCount = 0;
  let diffCount = 0;
  let oldOnlyCount = 0;
  let newOnlyCount = 0;

  for (let i = 0; i < totalRows; i++) {
    const oldVals = generateRowValues();
    const r = Math.random();
    let status: DiffStatus;
    let newVals: Record<string, string | null> | null = null;
    let diffColumns: string[] = [];

    if (r < 0.55) {
      // matched, no diff
      status = 'match';
      newVals = { ...oldVals };
      matchCount++;
    } else if (r < 0.85) {
      // matched with diffs
      status = 'diff';
      const result = mutateValues(oldVals);
      newVals = result.newVals;
      diffColumns = result.diffCols;
      diffColumns.forEach(c => { columnDiffCounts[c]++; });
      diffCount++;
    } else if (r < 0.93) {
      // old only
      status = 'old_only';
      oldOnlyCount++;
    } else {
      // new only
      status = 'new_only';
      newVals = generateRowValues();
      newOnlyCount++;
    }

    rows.push({
      index: i,
      key: oldVals[KEY_COLUMN],
      status,
      oldValues: status === 'new_only' ? {} : oldVals,
      newValues: newVals ?? {},
      diffColumns,
    });
  }

  return {
    rows,
    summary: {
      totalRows,
      matchedRows: matchCount,
      diffRows: diffCount,
      oldOnlyRows: oldOnlyCount,
      newOnlyRows: newOnlyCount,
      columns: COLUMNS,
      keyColumn: KEY_COLUMN,
      columnDiffCounts,
    },
  };
}
