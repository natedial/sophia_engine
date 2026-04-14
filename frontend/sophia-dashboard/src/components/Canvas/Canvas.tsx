import { useCallback, useMemo } from 'react'
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import { ChartCard } from './ChartCard'
import { useCanvasStore } from '../../store/canvasStore'
import { useWebSocket } from '../../hooks/useWebSocket'
import type { LayoutItem } from '../../types/canvas'

import 'react-grid-layout/css/styles.css'

const AutoWidthGridLayout = WidthProvider(GridLayout)
const GRID_COLS = 12
const ROW_HEIGHT = 80
const MARGIN: [number, number] = [16, 16]

export function Canvas() {
  const { canvasId, charts, layout, saveLayout } = useCanvasStore()

  // Connect to WebSocket for real-time updates
  useWebSocket(canvasId)

  // Convert charts Map to array
  const chartArray = useMemo(() => Array.from(charts.values()), [charts])

  // Handle layout change
  const handleLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      const layoutItems: LayoutItem[] = newLayout.map((item) => ({
        i: item.i,
        x: item.x,
        y: item.y,
        w: item.w,
        h: item.h,
        minW: item.minW,
        minH: item.minH,
      }))

      saveLayout(layoutItems)
    },
    [saveLayout]
  )

  // Empty state
  if (chartArray.length === 0) {
    return (
      <div className="canvas-empty">
        <div className="empty-state">
          <EmptyIcon />
          <h2>No charts yet</h2>
          <p>
            Ask Sophia to create visualizations and they will appear here
            automatically.
          </p>
          <p className="empty-hint">
            Try: "Show me GDP growth over the last 5 years"
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="canvas">
      <AutoWidthGridLayout
        className="canvas-grid"
        layout={layout}
        cols={GRID_COLS}
        rowHeight={ROW_HEIGHT}
        margin={MARGIN}
        onLayoutChange={handleLayoutChange}
        draggableHandle=".chart-card-header"
        isResizable={true}
        isDraggable={true}
        compactType="vertical"
        preventCollision={false}
      >
        {chartArray.map((chart) => (
          <div key={chart.id} className="grid-item">
            <ChartCard chart={chart} />
          </div>
        ))}
      </AutoWidthGridLayout>
    </div>
  )
}

function EmptyIcon() {
  return (
    <svg
      width="64"
      height="64"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      className="empty-icon"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="9" y1="21" x2="9" y2="9" />
    </svg>
  )
}
