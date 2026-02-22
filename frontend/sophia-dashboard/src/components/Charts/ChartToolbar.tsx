import { useState, useRef, useEffect } from 'react'

interface ChartToolbarProps {
  chartId: string
  onDelete: () => void
  onRefresh?: () => void
  onExport?: (format: 'png' | 'svg') => void
  onExpand?: () => void
  isRefreshing?: boolean
}

export function ChartToolbar({
  chartId,
  onDelete,
  onRefresh,
  onExport,
  onExpand,
  isRefreshing = false,
}: ChartToolbarProps) {
  const [showMenu, setShowMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="chart-toolbar">
      {onRefresh && (
        <button
          className={`toolbar-button ${isRefreshing ? 'is-loading' : ''}`}
          onClick={onRefresh}
          disabled={isRefreshing}
          title="Refresh data"
        >
          <RefreshIcon />
        </button>
      )}

      {onExpand && (
        <button
          className="toolbar-button"
          onClick={onExpand}
          title="Expand chart"
        >
          <ExpandIcon />
        </button>
      )}

      <div className="toolbar-menu-container" ref={menuRef}>
        <button
          className="toolbar-button"
          onClick={() => setShowMenu(!showMenu)}
          title="More options"
        >
          <MoreIcon />
        </button>

        {showMenu && (
          <div className="toolbar-menu">
            {onExport && (
              <>
                <button
                  className="toolbar-menu-item"
                  onClick={() => {
                    onExport('png')
                    setShowMenu(false)
                  }}
                >
                  <DownloadIcon />
                  Export as PNG
                </button>
                <button
                  className="toolbar-menu-item"
                  onClick={() => {
                    onExport('svg')
                    setShowMenu(false)
                  }}
                >
                  <DownloadIcon />
                  Export as SVG
                </button>
                <div className="toolbar-menu-divider" />
              </>
            )}
            <button
              className="toolbar-menu-item toolbar-menu-item-danger"
              onClick={() => {
                onDelete()
                setShowMenu(false)
              }}
            >
              <DeleteIcon />
              Delete chart
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function RefreshIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <path d="M23 4v6h-6" />
      <path d="M1 20v-6h6" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  )
}

function ExpandIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <polyline points="15 3 21 3 21 9" />
      <polyline points="9 21 3 21 3 15" />
      <line x1="21" y1="3" x2="14" y2="10" />
      <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
  )
}

function MoreIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <circle cx="12" cy="12" r="1" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="12" cy="19" r="1" />
    </svg>
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

function DeleteIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  )
}
