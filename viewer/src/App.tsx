import { useState, useMemo, useCallback } from 'react';
import { FileText, Database, AlertTriangle } from 'lucide-react';
import './App.css';

import type { DiffSummary, FilterState } from './types';
import { generateDemoData } from './generateDemoData';
import DiffTable from './components/DiffTable';
import FilterSidebar from './components/FilterSidebar';
import Minimap from './components/Minimap';

function App() {
  // Generate demo data on first render
  const { rows: allRows, summary: rawSummary } = useMemo(
    () => generateDemoData(10_000),
    []
  );

  const [filters, setFilters] = useState<FilterState>({
    statusFilter: 'all',
    searchText: '',
    diffColumnsOnly: false,
    selectedColumns: [],
  });

  const [viewMode, setViewMode] = useState<'side-by-side' | 'unified'>('side-by-side');
  const [visibleStart, setVisibleStart] = useState(0);
  const [visibleEnd, setVisibleEnd] = useState(50);
  const [scrollToIndex, setScrollToIndex] = useState<number | undefined>(undefined);
  const [currentDiffIdx, setCurrentDiffIdx] = useState(-1);

  // Filter rows
  const filteredRows = useMemo(() => {
    let result = allRows;

    if (filters.statusFilter !== 'all') {
      result = result.filter((r) => r.status === filters.statusFilter);
    }

    if (filters.searchText.trim()) {
      const term = filters.searchText.toLowerCase();
      result = result.filter((r) => {
        if (r.key.toLowerCase().includes(term)) return true;
        for (const v of Object.values(r.oldValues)) {
          if (v && v.toLowerCase().includes(term)) return true;
        }
        for (const v of Object.values(r.newValues)) {
          if (v && v.toLowerCase().includes(term)) return true;
        }
        return false;
      });
    }

    return result;
  }, [allRows, filters.statusFilter, filters.searchText]);

  // Visible columns
  const visibleColumns = useMemo(() => {
    if (filters.diffColumnsOnly) {
      const diffCols = new Set<string>();
      filteredRows.forEach((r) => r.diffColumns.forEach((c) => diffCols.add(c)));
      // Always include the key column first
      const cols = [rawSummary.keyColumn];
      rawSummary.columns.forEach((c) => {
        if (c !== rawSummary.keyColumn && diffCols.has(c)) cols.push(c);
      });
      return cols.length > 1 ? cols : rawSummary.columns;
    }
    return rawSummary.columns;
  }, [filteredRows, filters.diffColumnsOnly, rawSummary]);

  // Diff indices for navigation
  const diffIndices = useMemo(
    () => filteredRows
      .map((r, i) => (r.status === 'diff' || r.status === 'old_only' || r.status === 'new_only' ? i : -1))
      .filter((i) => i >= 0),
    [filteredRows]
  );

  // Updated summary reflecting filters
  const summary: DiffSummary = useMemo(() => {
    const s = { ...rawSummary, totalRows: filteredRows.length };
    s.matchedRows = filteredRows.filter((r) => r.status === 'match').length;
    s.diffRows = filteredRows.filter((r) => r.status === 'diff').length;
    s.oldOnlyRows = filteredRows.filter((r) => r.status === 'old_only').length;
    s.newOnlyRows = filteredRows.filter((r) => r.status === 'new_only').length;
    return s;
  }, [filteredRows, rawSummary]);

  const handleScrollChange = useCallback((start: number, end: number) => {
    setVisibleStart(start);
    setVisibleEnd(end);
  }, []);

  const handleMinimapClick = useCallback((rowIndex: number) => {
    setScrollToIndex(rowIndex);
    // Reset after a tick so the same index can be clicked again
    setTimeout(() => setScrollToIndex(undefined), 50);
  }, []);

  const handleJumpToNextDiff = useCallback(() => {
    if (diffIndices.length === 0) return;
    const next = currentDiffIdx + 1 >= diffIndices.length ? 0 : currentDiffIdx + 1;
    setCurrentDiffIdx(next);
    setScrollToIndex(diffIndices[next]);
    setTimeout(() => setScrollToIndex(undefined), 50);
  }, [diffIndices, currentDiffIdx]);

  const handleJumpToPrevDiff = useCallback(() => {
    if (diffIndices.length === 0) return;
    const prev = currentDiffIdx - 1 < 0 ? diffIndices.length - 1 : currentDiffIdx - 1;
    setCurrentDiffIdx(prev);
    setScrollToIndex(diffIndices[prev]);
    setTimeout(() => setScrollToIndex(undefined), 50);
  }, [diffIndices, currentDiffIdx]);

  return (
    <div className="h-screen flex flex-col bg-white text-slate-800">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-2 bg-slate-900 text-white border-b border-slate-700">
        <div className="flex items-center gap-3">
          <Database size={20} className="text-blue-400" />
          <h1 className="text-sm font-semibold">CMS Claims Diff Viewer</h1>
          <span className="text-xs text-slate-400 ml-2">
            {filteredRows.length.toLocaleString()} rows
            {filters.statusFilter !== 'all' && ` (filtered from ${allRows.length.toLocaleString()})`}
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-slate-400">
          <span className="flex items-center gap-1">
            <FileText size={14} />
            {visibleColumns.length} columns
          </span>
          {summary.diffRows > 0 && (
            <span className="flex items-center gap-1 text-red-400">
              <AlertTriangle size={14} />
              {summary.diffRows.toLocaleString()} differences
            </span>
          )}
          <span className="text-slate-500">Demo data (10K rows)</span>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: filters */}
        <FilterSidebar
          summary={summary}
          filters={filters}
          onFiltersChange={setFilters}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          onJumpToNextDiff={handleJumpToNextDiff}
          onJumpToPrevDiff={handleJumpToPrevDiff}
          currentDiffIndex={currentDiffIdx}
          totalDiffs={diffIndices.length}
        />

        {/* Center: diff table */}
        <div className="flex-1 flex overflow-hidden diff-table">
          <DiffTable
            rows={filteredRows}
            columns={visibleColumns}
            viewMode={viewMode}
            onScrollChange={handleScrollChange}
            scrollToIndex={scrollToIndex}
          />
        </div>

        {/* Right: minimap */}
        <div className="w-20 border-l border-slate-200 bg-slate-50 flex items-start justify-center pt-2">
          <Minimap
            rows={filteredRows}
            visibleStartIndex={visibleStart}
            visibleEndIndex={visibleEnd}
            height={600}
            onClickRow={handleMinimapClick}
          />
        </div>
      </div>
    </div>
  );
}

export default App;
