import { UserMenu } from '../Auth'

interface HeaderProps {
  sectionTitle: string
  sectionSubtitle: string
  statusLabel?: string
  statusTone?: 'live' | 'neutral'
  metaLabel?: string | null
}

export function Header({
  sectionTitle,
  sectionSubtitle,
  statusLabel,
  statusTone = 'neutral',
  metaLabel,
}: HeaderProps) {
  return (
    <header className="header">
      <div className="header-left">
        <div>
          <div className="header-eyebrow">Sophia Platform</div>
          <h1 className="header-title">{sectionTitle}</h1>
        </div>
        <span className="header-subtitle">{sectionSubtitle}</span>
      </div>
      <div className="header-right">
        {statusLabel && (
          <div className={`connection-status ${statusTone === 'live' ? 'connected' : ''}`}>
            <span className="status-dot" />
            <span className="status-text">{statusLabel}</span>
          </div>
        )}
        {metaLabel && <span className="canvas-id">{metaLabel}</span>}
        <UserMenu />
      </div>
    </header>
  )
}
