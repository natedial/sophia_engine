import { useCanvasStore } from '../../store/canvasStore'
import { UserMenu } from '../Auth'

export function Header() {
  const { canvasName, canvasId, isConnected } = useCanvasStore()

  return (
    <header className="header">
      <div className="header-left">
        <h1 className="header-title">Sophia</h1>
        <span className="header-subtitle">{canvasName}</span>
      </div>
      <div className="header-right">
        <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
          <span className="status-dot" />
          <span className="status-text">
            {isConnected ? 'Live' : 'Connecting...'}
          </span>
        </div>
        {canvasId && (
          <span className="canvas-id" title={canvasId}>
            ID: {canvasId.slice(0, 8)}...
          </span>
        )}
        <UserMenu />
      </div>
    </header>
  )
}
