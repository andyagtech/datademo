import { useRef, useCallback, useEffect } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import type { DiffRow } from '../types';

const ROW_HEIGHT = 28;

interface DiffTableProps {
  rows: DiffRow[];
  columns: string[];
  viewMode: 'side-by-side' | 'unified';
  onScrollChange: (startIndex: number, endIndex: number) => void;
  scrollToIndex?: number;
}

function cellClass(row: DiffRow, col: string): string {
  if (row.status === 'old_only') return 'cell-old-only';
  if (row.status === 'new_only') return 'cell-new-only';
  if (row.status === 'diff' && row.diffColumns.includes(col)) return 'cell-diff';
  return 'cell-match';
}

function rowClass(row: DiffRow): string {
  return `row-${row.status}`;
}

function StatusBadge({ status }: { status: DiffRow['status'] }) {
  const styles: Record<string, string> = {
    match: 'bg-slate-100 text-slate-600',
    diff: 'bg-red-100 text-red-700',
    old_only: 'bg-amber-100 text-amber-700',
    new_only: 'bg-blue-100 text-blue-700',
  };
  const labels: Record<string, string> = {
    match: '=',
    diff: '≠',
    old_only: '−',
    new_only: '+',
  };
  return (
    <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold ${styles[status]}`}>
      {labels[status]}
    </span>
  );
}

export default function DiffTable({
  rows,
  columns,
  viewMode,
  onScrollChange,
  scrollToIndex,
}: DiffTableProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 20,
  });

  // Report visible range on scroll
  useEffect(() => {
    const items = virtualizer.getVirtualItems();
    if (items.length > 0) {
      onScrollChange(items[0].index, items[items.length - 1].index);
    }
  }, [virtualizer.getVirtualItems(), onScrollChange]);

  // Scroll to a specific index when requested
  useEffect(() => {
    if (scrollToIndex !== undefined && scrollToIndex >= 0) {
      virtualizer.scrollToIndex(scrollToIndex, { align: 'center' });
    }
  }, [scrollToIndex, virtualizer]);

  const renderSideBySide = useCallback(() => {
    return (
      <div className="relative w-full" style={{ height: `${virtualizer.getTotalSize()}px` }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const row = rows[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              className={`absolute left-0 w-full flex items-center border-b border-slate-100 ${rowClass(row)} hover:bg-slate-50`}
              style={{
                height: `${ROW_HEIGHT}px`,
                top: `${virtualRow.start}px`,
              }}
            >
              {/* Row number */}
              <div className="w-12 flex-shrink-0 text-right pr-2 text-slate-400 text-[10px]">
                {virtualRow.index + 1}
              </div>
              {/* Status badge */}
              <div className="w-8 flex-shrink-0 flex justify-center">
                <StatusBadge status={row.status} />
              </div>
              {/* Columns */}
              {columns.map((col) => {
                const oldVal = row.oldValues[col] ?? '';
                const newVal = row.newValues[col] ?? '';
                const isDiff = row.diffColumns.includes(col);

                return (
                  <div
                    key={col}
                    className={`flex-shrink-0 flex ${cellClass(row, col)}`}
                    style={{ width: '240px' }}
                  >
                    {/* Old value */}
                    <div
                      className={`w-[120px] px-1 truncate ${isDiff ? 'line-through text-red-500 decoration-red-300' : 'text-slate-700'}`}
                      title={oldVal}
                    >
                      {row.status === 'new_only' ? '—' : oldVal}
                    </div>
                    {/* New value */}
                    <div
                      className={`w-[120px] px-1 truncate ${isDiff ? 'font-semibold text-green-700' : 'text-slate-700'}`}
                      title={newVal}
                    >
                      {row.status === 'old_only' ? '—' : newVal}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    );
  }, [rows, columns, virtualizer]);

  const renderUnified = useCallback(() => {
    return (
      <div className="relative w-full" style={{ height: `${virtualizer.getTotalSize()}px` }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const row = rows[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              className={`absolute left-0 w-full flex items-center border-b border-slate-100 ${rowClass(row)} hover:bg-slate-50`}
              style={{
                height: `${ROW_HEIGHT}px`,
                top: `${virtualRow.start}px`,
              }}
            >
              <div className="w-12 flex-shrink-0 text-right pr-2 text-slate-400 text-[10px]">
                {virtualRow.index + 1}
              </div>
              <div className="w-8 flex-shrink-0 flex justify-center">
                <StatusBadge status={row.status} />
              </div>
              {columns.map((col) => {
                const isDiff = row.diffColumns.includes(col);
                const displayVal = row.status === 'old_only'
                  ? (row.oldValues[col] ?? '')
                  : (row.newValues[col] ?? row.oldValues[col] ?? '');

                return (
                  <div
                    key={col}
                    className={`flex-shrink-0 px-1 truncate ${cellClass(row, col)} ${isDiff ? 'font-semibold' : ''}`}
                    style={{ width: '120px' }}
                    title={isDiff ? `Old: ${row.oldValues[col]} → New: ${row.newValues[col]}` : displayVal}
                  >
                    {displayVal}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    );
  }, [rows, columns, virtualizer]);

  const colWidth = viewMode === 'side-by-side' ? 240 : 120;
  const totalWidth = 12 + 8 + columns.length * colWidth + 20; // row# + badge + cols + padding

  return (
    <div
      ref={parentRef}
      className="virtual-table overflow-auto flex-1 bg-white"
      style={{ contain: 'strict' }}
    >
      {/* Sticky header */}
      <div
        className="sticky top-0 z-10 flex items-center bg-slate-50 border-b-2 border-slate-200 font-semibold text-[11px] text-slate-600"
        style={{ width: `${totalWidth}px`, height: `${ROW_HEIGHT}px` }}
      >
        <div className="w-12 flex-shrink-0 text-right pr-2">#</div>
        <div className="w-8 flex-shrink-0 text-center">ST</div>
        {columns.map((col) => (
          <div
            key={col}
            className="flex-shrink-0 px-1 truncate"
            style={{ width: `${colWidth}px` }}
            title={col}
          >
            {viewMode === 'side-by-side' ? (
              <div className="flex">
                <span className="w-[120px] text-red-600 truncate">{col} (old)</span>
                <span className="w-[120px] text-green-600 truncate">{col} (new)</span>
              </div>
            ) : (
              col
            )}
          </div>
        ))}
      </div>

      {/* Virtual rows */}
      <div style={{ width: `${totalWidth}px` }}>
        {viewMode === 'side-by-side' ? renderSideBySide() : renderUnified()}
      </div>
    </div>
  );
}
