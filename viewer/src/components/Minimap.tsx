import { useRef, useEffect, useCallback } from 'react';
import type { DiffRow } from '../types';

const STATUS_COLORS: Record<string, string> = {
  match: '#e2e8f0',    // slate-200
  diff: '#fca5a5',     // red-300
  old_only: '#fcd34d', // amber-300
  new_only: '#93c5fd', // blue-300
};

interface MinimapProps {
  rows: DiffRow[];
  visibleStartIndex: number;
  visibleEndIndex: number;
  height: number;
  onClickRow: (rowIndex: number) => void;
}

export default function Minimap({
  rows,
  visibleStartIndex,
  visibleEndIndex,
  height,
  onClickRow,
}: MinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const width = 60;

  // Draw the minimap
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    if (rows.length === 0) return;

    const rowHeight = Math.max(height / rows.length, 0.5);

    // Draw rows as colored lines
    for (let i = 0; i < rows.length; i++) {
      const y = (i / rows.length) * height;
      ctx.fillStyle = STATUS_COLORS[rows[i].status] || STATUS_COLORS.match;
      ctx.fillRect(0, y, width, Math.max(rowHeight, 1));
    }

    // Draw viewport indicator
    const vpTop = (visibleStartIndex / rows.length) * height;
    const vpBottom = (visibleEndIndex / rows.length) * height;
    const vpHeight = Math.max(vpBottom - vpTop, 4);

    ctx.strokeStyle = 'rgba(59, 130, 246, 0.8)';
    ctx.lineWidth = 2;
    ctx.fillStyle = 'rgba(59, 130, 246, 0.15)';
    ctx.fillRect(0, vpTop, width, vpHeight);
    ctx.strokeRect(0, vpTop, width, vpHeight);
  }, [rows, visibleStartIndex, visibleEndIndex, height]);

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const y = e.clientY - rect.top;
      const rowIndex = Math.floor((y / height) * rows.length);
      onClickRow(Math.max(0, Math.min(rowIndex, rows.length - 1)));
    },
    [rows.length, height, onClickRow]
  );

  return (
    <div className="minimap-container flex flex-col items-center">
      <div className="text-[10px] text-slate-500 mb-1 font-medium">MAP</div>
      <canvas
        ref={canvasRef}
        style={{ width: `${width}px`, height: `${height}px` }}
        className="rounded border border-slate-200"
        onClick={handleClick}
      />
      <div className="mt-2 space-y-1 text-[10px]">
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: STATUS_COLORS.match }} />
          <span className="text-slate-500">Match</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: STATUS_COLORS.diff }} />
          <span className="text-slate-500">Diff</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: STATUS_COLORS.old_only }} />
          <span className="text-slate-500">Old only</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: STATUS_COLORS.new_only }} />
          <span className="text-slate-500">New only</span>
        </div>
      </div>
    </div>
  );
}
