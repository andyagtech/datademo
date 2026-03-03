import { Search, Filter, BarChart3, ArrowUpDown } from 'lucide-react';
import type { DiffSummary, FilterState, DiffStatus } from '../types';

interface FilterSidebarProps {
  summary: DiffSummary;
  filters: FilterState;
  onFiltersChange: (filters: FilterState) => void;
  viewMode: 'side-by-side' | 'unified';
  onViewModeChange: (mode: 'side-by-side' | 'unified') => void;
  onJumpToNextDiff: () => void;
  onJumpToPrevDiff: () => void;
  currentDiffIndex: number;
  totalDiffs: number;
}

const STATUS_OPTIONS: { value: DiffStatus | 'all'; label: string; color: string; count?: number }[] = [
  { value: 'all', label: 'All rows', color: 'bg-slate-200' },
  { value: 'match', label: 'Matched', color: 'bg-slate-200' },
  { value: 'diff', label: 'Different', color: 'bg-red-200' },
  { value: 'old_only', label: 'Old only', color: 'bg-amber-200' },
  { value: 'new_only', label: 'New only', color: 'bg-blue-200' },
];

export default function FilterSidebar({
  summary,
  filters,
  onFiltersChange,
  viewMode,
  onViewModeChange,
  onJumpToNextDiff,
  onJumpToPrevDiff,
  currentDiffIndex,
  totalDiffs,
}: FilterSidebarProps) {
  const counts: Record<string, number> = {
    all: summary.totalRows,
    match: summary.matchedRows,
    diff: summary.diffRows,
    old_only: summary.oldOnlyRows,
    new_only: summary.newOnlyRows,
  };

  // Top 10 columns by diff count
  const topDiffColumns = Object.entries(summary.columnDiffCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);

  const maxDiffCount = topDiffColumns.length > 0 ? topDiffColumns[0][1] : 1;

  return (
    <div className="w-64 bg-slate-50 border-r border-slate-200 flex flex-col overflow-y-auto p-3 gap-4">
      {/* Summary Stats */}
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
          Summary
        </h3>
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-white rounded-lg p-2 border border-slate-200">
            <div className="text-lg font-bold text-slate-800">
              {summary.totalRows.toLocaleString()}
            </div>
            <div className="text-[10px] text-slate-500">Total rows</div>
          </div>
          <div className="bg-white rounded-lg p-2 border border-red-200">
            <div className="text-lg font-bold text-red-600">
              {summary.diffRows.toLocaleString()}
            </div>
            <div className="text-[10px] text-red-500">Differences</div>
          </div>
          <div className="bg-white rounded-lg p-2 border border-amber-200">
            <div className="text-lg font-bold text-amber-600">
              {summary.oldOnlyRows.toLocaleString()}
            </div>
            <div className="text-[10px] text-amber-500">Old only</div>
          </div>
          <div className="bg-white rounded-lg p-2 border border-blue-200">
            <div className="text-lg font-bold text-blue-600">
              {summary.newOnlyRows.toLocaleString()}
            </div>
            <div className="text-[10px] text-blue-500">New only</div>
          </div>
        </div>
      </div>

      {/* Search */}
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
          <Search size={12} /> Search
        </h3>
        <input
          type="text"
          placeholder="Search by key or value..."
          className="w-full px-2 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-300"
          value={filters.searchText}
          onChange={(e) =>
            onFiltersChange({ ...filters, searchText: e.target.value })
          }
        />
      </div>

      {/* Status Filter */}
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
          <Filter size={12} /> Filter by Status
        </h3>
        <div className="space-y-1">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              className={`w-full flex items-center justify-between px-2 py-1.5 text-sm rounded-md transition-colors ${
                filters.statusFilter === opt.value
                  ? 'bg-white border-2 border-blue-400 shadow-sm'
                  : 'hover:bg-white border border-transparent'
              }`}
              onClick={() =>
                onFiltersChange({ ...filters, statusFilter: opt.value })
              }
            >
              <div className="flex items-center gap-2">
                <span className={`w-2.5 h-2.5 rounded-sm ${opt.color}`} />
                <span className="text-slate-700">{opt.label}</span>
              </div>
              <span className="text-slate-400 text-xs">
                {counts[opt.value]?.toLocaleString()}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Diff Navigation */}
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
          <ArrowUpDown size={12} /> Navigate Diffs
        </h3>
        <div className="flex items-center gap-2">
          <button
            className="flex-1 px-2 py-1.5 text-sm bg-white border border-slate-200 rounded-md hover:bg-slate-100 transition-colors"
            onClick={onJumpToPrevDiff}
          >
            ← Prev
          </button>
          <span className="text-xs text-slate-500 whitespace-nowrap">
            {totalDiffs > 0 ? `${currentDiffIndex + 1}/${totalDiffs}` : '0/0'}
          </span>
          <button
            className="flex-1 px-2 py-1.5 text-sm bg-white border border-slate-200 rounded-md hover:bg-slate-100 transition-colors"
            onClick={onJumpToNextDiff}
          >
            Next →
          </button>
        </div>
      </div>

      {/* View Mode Toggle */}
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
          View Mode
        </h3>
        <div className="flex rounded-md border border-slate-200 overflow-hidden">
          <button
            className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
              viewMode === 'side-by-side'
                ? 'bg-blue-500 text-white'
                : 'bg-white text-slate-600 hover:bg-slate-100'
            }`}
            onClick={() => onViewModeChange('side-by-side')}
          >
            Side by Side
          </button>
          <button
            className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
              viewMode === 'unified'
                ? 'bg-blue-500 text-white'
                : 'bg-white text-slate-600 hover:bg-slate-100'
            }`}
            onClick={() => onViewModeChange('unified')}
          >
            Unified
          </button>
        </div>
      </div>

      {/* Show diff columns only */}
      <div>
        <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
          <input
            type="checkbox"
            className="rounded border-slate-300"
            checked={filters.diffColumnsOnly}
            onChange={(e) =>
              onFiltersChange({ ...filters, diffColumnsOnly: e.target.checked })
            }
          />
          Show diff columns only
        </label>
      </div>

      {/* Top Changed Columns */}
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
          <BarChart3 size={12} /> Most Changed Columns
        </h3>
        <div className="space-y-1">
          {topDiffColumns.map(([col, count]) => (
            <div key={col} className="flex items-center gap-2">
              <div className="flex-1 min-w-0">
                <div className="text-[11px] text-slate-700 truncate" title={col}>
                  {col}
                </div>
                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-red-400 rounded-full"
                    style={{ width: `${(count / maxDiffCount) * 100}%` }}
                  />
                </div>
              </div>
              <span className="text-[10px] text-slate-400 w-8 text-right">
                {count}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
