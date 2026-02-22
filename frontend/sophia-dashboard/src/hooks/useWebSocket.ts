import { useEffect, useRef, useCallback } from 'react'
import { useCanvasStore } from '../store/canvasStore'
import { useAuthStore } from '../store/authStore'
import type { ServerMessage } from '../types/websocket'

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]
const PING_INTERVAL = 30000

export function useWebSocket(canvasId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptRef = useRef(0)
  const pingIntervalRef = useRef<number | null>(null)

  const {
    setConnected,
    addChart,
    updateChart,
    removeChart,
    updateLayout,
    setCharts,
  } = useCanvasStore()

  const { getIdToken, isAuthenticated } = useAuthStore()

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const message: ServerMessage = JSON.parse(event.data)

        switch (message.type) {
          case 'connection_ack':
            console.log('WebSocket connected to canvas:', message.canvas_id)
            if (message.charts && message.charts.length > 0) {
              setCharts(message.charts)
            }
            break

          case 'chart_created':
            console.log('Chart created:', message.chart.id)
            addChart(message.chart)
            break

          case 'chart_updated':
            console.log('Chart updated:', message.chart_id)
            updateChart(message.chart_id, message.updates)
            break

          case 'chart_deleted':
            console.log('Chart deleted:', message.chart_id)
            removeChart(message.chart_id)
            break

          case 'layout_updated':
            console.log('Layout updated')
            const newLayout = message.layout.map((item) => ({
              i: item.chart_id,
              x: item.x,
              y: item.y,
              w: item.w,
              h: item.h,
              minW: 3,
              minH: 2,
            }))
            updateLayout(newLayout)
            break

          case 'error':
            console.error('WebSocket error:', message.message)
            break

          case 'pong':
            // Heartbeat response
            break

          default:
            console.warn('Unknown message type:', message)
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err)
      }
    },
    [addChart, updateChart, removeChart, updateLayout, setCharts]
  )

  const connect = useCallback(async () => {
    if (!canvasId) return

    // Get auth token for WebSocket connection
    const token = await getIdToken()

    // Determine WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    let wsUrl = `${protocol}//${host}/ws/${canvasId}`

    // Add token as query parameter if available
    if (token) {
      wsUrl += `?token=${encodeURIComponent(token)}`
    }

    console.log('Connecting to WebSocket:', wsUrl.replace(/token=.*/, 'token=[REDACTED]'))

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('WebSocket connected')
      setConnected(true)
      reconnectAttemptRef.current = 0

      // Start ping interval
      pingIntervalRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL)
    }

    ws.onmessage = handleMessage

    ws.onclose = (event) => {
      console.log('WebSocket closed:', event.code, event.reason)
      setConnected(false)

      // Clear ping interval
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = null
      }

      // Attempt reconnection with exponential backoff
      if (reconnectAttemptRef.current < RECONNECT_DELAYS.length) {
        const delay = RECONNECT_DELAYS[reconnectAttemptRef.current]
        console.log(`Reconnecting in ${delay}ms...`)
        setTimeout(() => {
          reconnectAttemptRef.current++
          connect()
        }, delay)
      } else {
        console.error('Max reconnection attempts reached')
      }
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }, [canvasId, handleMessage, setConnected, getIdToken])

  const disconnect = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    if (canvasId && isAuthenticated) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [canvasId, isAuthenticated, connect, disconnect])

  return {
    isConnected: wsRef.current?.readyState === WebSocket.OPEN,
    disconnect,
    reconnect: connect,
  }
}
