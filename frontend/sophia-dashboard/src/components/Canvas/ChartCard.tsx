import { useCallback, useRef, useState } from 'react'
import { VegaChart, VegaChartHandle } from '../Charts/VegaChart'
import { ChartToolbar } from '../Charts/ChartToolbar'
import { ChartModal } from './ChartModal'
import { useCanvasStore } from '../../store/canvasStore'
import type { Chart } from '../../types/canvas'

interface ChartCardProps {
  chart: Chart
}

export function ChartCard({ chart }: ChartCardProps) {
  const { deleteChartApi } = useCanvasStore()
  const chartRef = useRef<VegaChartHandle>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleDelete = useCallback(() => {
    if (window.confirm('Are you sure you want to delete this chart?')) {
      deleteChartApi(chart.id)
    }
  }, [chart.id, deleteChartApi])

  const handleExport = useCallback(async (format: 'png' | 'svg') => {
    if (!chartRef.current) return

    const data = await chartRef.current.exportImage(format)
    if (!data) return

    // Create download link
    const link = document.createElement('a')
    const filename = `${chart.title || 'chart'}-${chart.id.slice(0, 8)}.${format}`

    if (format === 'svg') {
      const blob = new Blob([data], { type: 'image/svg+xml' })
      link.href = URL.createObjectURL(blob)
    } else {
      link.href = data
    }

    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    if (format === 'svg') {
      URL.revokeObjectURL(link.href)
    }
  }, [chart.id, chart.title])

  const handleRefresh = useCallback(async () => {
    // TODO: Implement actual data refresh via API
    setIsRefreshing(true)
    // Simulate refresh delay
    await new Promise(resolve => setTimeout(resolve, 1000))
    setIsRefreshing(false)
  }, [])

  const handleError = useCallback((err: Error) => {
    setError(err.message)
  }, [])

  return (
    <>
      <div className="chart-card">
        <div className="chart-card-header">
          <h3 className="chart-title">{chart.title || 'Untitled Chart'}</h3>
          <ChartToolbar
            chartId={chart.id}
            onDelete={handleDelete}
            onExport={handleExport}
            onRefresh={chart.data_query ? handleRefresh : undefined}
            onExpand={() => setIsExpanded(true)}
            isRefreshing={isRefreshing}
          />
        </div>
        <div className="chart-card-body">
          {error ? (
            <div className="chart-error">
              <ErrorIcon />
              <p>Failed to render chart</p>
              <small>{error}</small>
            </div>
          ) : (
            <VegaChart ref={chartRef} spec={chart.spec} onError={handleError} />
          )}
        </div>
        <div className="chart-card-footer">
          <span className="chart-type-badge">{chart.chart_type}</span>
          {chart.updated_at && (
            <span className="chart-updated">
              {new Date(chart.updated_at).toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {isExpanded && (
        <ChartModal
          chart={chart}
          onClose={() => setIsExpanded(false)}
          onExport={handleExport}
        />
      )}
    </>
  )
}

function ErrorIcon() {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}
