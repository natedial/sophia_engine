import { useEffect } from 'react'
import { Canvas } from './components/Canvas/Canvas'
import { Header } from './components/Layout/Header'
import { ProtectedRoute } from './components/Auth'
import { useCanvasStore } from './store/canvasStore'
import { useAuthStore } from './store/authStore'
import './styles/App.css'

function Dashboard() {
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
    <div className="app">
      <Header />
      <main className="main-content">
        {canvasId ? (
          <Canvas />
        ) : (
          <div className="loading">
            <p>Initializing dashboard...</p>
          </div>
        )}
      </main>
    </div>
  )
}

function App() {
  return (
    <ProtectedRoute>
      <Dashboard />
    </ProtectedRoute>
  )
}

export default App
