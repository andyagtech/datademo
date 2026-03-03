/** Status of a row in the diff comparison */
export type DiffStatus = 'match' | 'diff' | 'old_only' | 'new_only';

/** A single row in the diff dataset */
export interface DiffRow {
  /** Row index in the original dataset */
  index: number;
  /** Primary key value (e.g., DESYNPUF_ID or CLM_ID) */
  key: string;
  /** Diff status for this row */
  status: DiffStatus;
  /** Column values from the old system (null if new_only) */
  oldValues: Record<string, string | null>;
  /** Column values from the new system (null if old_only) */
  newValues: Record<string, string | null>;
  /** List of column names that differ between old and new */
  diffColumns: string[];
}

/** Summary statistics for a diff dataset */
export interface DiffSummary {
  totalRows: number;
  matchedRows: number;
  diffRows: number;
  oldOnlyRows: number;
  newOnlyRows: number;
  columns: string[];
  keyColumn: string;
  /** Per-column diff counts */
  columnDiffCounts: Record<string, number>;
}

/** Filter state for the viewer */
export interface FilterState {
  statusFilter: DiffStatus | 'all';
  searchText: string;
  diffColumnsOnly: boolean;
  selectedColumns: string[];
}

/** Chunk metadata for paginated loading */
export interface ChunkMeta {
  chunkIndex: number;
  startRow: number;
  endRow: number;
  rowCount: number;
}
