export type NavigationRoute = 'analysis' | 'agent-ops'

interface SidebarProps {
  activeRoute: NavigationRoute
  onSelect: (route: NavigationRoute) => void
}

const NAV_ITEMS: Array<{
  route: NavigationRoute
  label: string
  description: string
}> = [
  {
    route: 'analysis',
    label: 'Economic Analysis',
    description: 'Canvas, charts, and live dashboard state',
  },
  {
    route: 'agent-ops',
    label: 'Agent Ops',
    description: 'Run traces, rendered output, and policy tuning',
  },
]

export function Sidebar({ activeRoute, onSelect }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-mark">S</div>
        <div>
          <div className="sidebar-brand-title">Dashboard</div>
          <p className="sidebar-brand-copy">Operator surfaces for Sophia services.</p>
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="Dashboard sections">
        {NAV_ITEMS.map((item) => {
          const isActive = item.route === activeRoute
          return (
            <button
              key={item.route}
              type="button"
              className={`sidebar-link ${isActive ? 'is-active' : ''}`}
              onClick={() => onSelect(item.route)}
            >
              <span className="sidebar-link-label">{item.label}</span>
              <span className="sidebar-link-description">{item.description}</span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
