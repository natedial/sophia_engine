import { useEffect, useMemo, useState } from 'react'
import { AgentDashboard } from './components/AgentDashboard/AgentDashboard'
import { Canvas } from './components/Canvas/Canvas'
import { Header } from './components/Layout/Header'
import {
  Sidebar,
  type NavigationRoute,
} from './components/Layout/Sidebar'
import { ProtectedRoute } from './components/Auth'
import { useCanvasStore } from './store/canvasStore'
import { useAuthStore } from './store/authStore'
import './styles/App.css'

function AnalysisView() {
  const { canvasId, createCanvas, fetchCanvas } = useCanvasStore()
  const { isAuthenticated } = useAuthStore()

  useEffect(() => {
    // Only initialize canvas when authenticated
    if (!isAuthenticated) return

    const initCanvas = async () => {
      if (!canvasId) {
        // Check URL for canvas ID or create new
        const urlParams = new URLSearchParams(window.location.search)
        const urlCanvasId = urlParams.get('canvas')

        if (urlCanvasId) {
          await fetchCanvas(urlCanvasId)
        } else {
          // Create a new canvas for demo
          const sessionId = `session-${Date.now()}`
          await createCanvas(sessionId, 'Analysis Dashboard')
        }
      }
    }

    initCanvas()
  }, [canvasId, createCanvas, fetchCanvas, isAuthenticated])

  return (
    <div className="surface-page">
      {canvasId ? (
        <Canvas />
      ) : (
        <div className="loading">
          <p>Initializing dashboard...</p>
        </div>
      )}
    </div>
  )
}

function DashboardShell() {
  const { canvasName, canvasId, isConnected } = useCanvasStore()
  const route = useHashRoute()

  const headerProps = useMemo(() => {
    if (route === 'analysis') {
      return {
        sectionTitle: 'Economic Analysis',
        sectionSubtitle: canvasName,
        statusLabel: isConnected ? 'Canvas live' : 'Canvas connecting',
        statusTone: isConnected ? ('live' as const) : ('neutral' as const),
        metaLabel: canvasId ? `Canvas ${canvasId.slice(0, 8)}...` : null,
      }
    }

    return {
      sectionTitle: 'Agent Ops',
      sectionSubtitle: 'Trace runs, inspect rendered output, and tune delivery policy',
      statusLabel: 'Gateway admin',
      statusTone: 'neutral' as const,
      metaLabel: 'Presentation + runtime',
    }
  }, [canvasId, canvasName, isConnected, route])

  return (
    <div className="app-shell">
      <Sidebar activeRoute={route} onSelect={setHashRoute} />
      <div className="app-main">
        <Header {...headerProps} />
        <main className="main-content">
          {route === 'analysis' ? <AnalysisView /> : <AgentDashboard />}
        </main>
      </div>
    </div>
  )
}

function App() {
  return (
    <ProtectedRoute>
      <DashboardShell />
    </ProtectedRoute>
  )
}

export default App

function useHashRoute(): NavigationRoute {
  const [route, setRoute] = useState<NavigationRoute>(() => readHashRoute())

  useEffect(() => {
    const handleHashChange = () => setRoute(readHashRoute())
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  return route
}

function setHashRoute(route: NavigationRoute) {
  window.location.hash = route === 'analysis' ? '#/analysis' : '#/agent-ops'
}

function readHashRoute(): NavigationRoute {
  const normalizedHash = window.location.hash.replace(/^#\/?/, '').trim()
  if (normalizedHash === 'agent-ops') {
    return 'agent-ops'
  }
  return 'analysis'
}
