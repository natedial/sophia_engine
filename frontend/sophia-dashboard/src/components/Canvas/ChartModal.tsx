import { useEffect, useCallback, useRef } from 'react'
import { VegaChart, VegaChartHandle } from '../Charts/VegaChart'
import type { Chart } from '../../types/canvas'

interface ChartModalProps {
  chart: Chart
  onClose: () => void
  onExport?: (format: 'png' | 'svg') => void
}

export function ChartModal({ chart, onClose, onExport }: ChartModalProps) {
  const chartRef = useRef<VegaChartHandle>(null)

  // Close on escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  // Prevent body scroll when modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [])

  const handleExport = useCallback(async (format: 'png' | 'svg') => {
    if (!chartRef.current) return

    const data = await chartRef.current.exportImage(format)
    if (!data) return

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

    onExport?.(format)
  }, [chart.id, chart.title, onExport])

  return (
    <div className="chart-modal-overlay" onClick={onClose}>
      <div className="chart-modal" onClick={(e) => e.stopPropagation()}>
        <div className="chart-modal-header">
          <h2>{chart.title || 'Untitled Chart'}</h2>
          <div className="chart-modal-actions">
            <button
              className="modal-action-button"
              onClick={() => handleExport('png')}
              title="Export as PNG"
            >
              <DownloadIcon />
              PNG
            </button>
            <button
              className="modal-action-button"
              onClick={() => handleExport('svg')}
              title="Export as SVG"
            >
              <DownloadIcon />
              SVG
            </button>
            <button
              className="modal-close-button"
              onClick={onClose}
              title="Close"
            >
              <CloseIcon />
            </button>
          </div>
        </div>
        <div className="chart-modal-body">
          <VegaChart ref={chartRef} spec={chart.spec} />
        </div>
        <div className="chart-modal-footer">
          <span className="chart-type-badge">{chart.chart_type}</span>
          {chart.data_query && (
            <span className="chart-query">
              {JSON.stringify(chart.data_query)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function DownloadIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}
