import { create } from 'zustand'
import type { Canvas, Chart, LayoutItem } from '../types/canvas'
import * as api from '../services/api'

interface CanvasState {
  // State
  canvasId: string | null
  canvasName: string
  charts: Map<string, Chart>
  layout: LayoutItem[]
  isConnected: boolean
  isLoading: boolean
  error: string | null

  // Actions
  setCanvasId: (id: string | null) => void
  setCanvasName: (name: string) => void
  setConnected: (connected: boolean) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  // Chart actions
  addChart: (chart: Chart) => void
  updateChart: (chartId: string, updates: Partial<Chart>) => void
  removeChart: (chartId: string) => void
  setCharts: (charts: Chart[]) => void

  // Layout actions
  updateLayout: (layout: LayoutItem[]) => void

  // API actions
  createCanvas: (sessionId: string, name?: string) => Promise<void>
  fetchCanvas: (canvasId: string) => Promise<void>
  saveLayout: (layout: LayoutItem[]) => Promise<void>
  deleteChartApi: (chartId: string) => Promise<void>
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  // Initial state
  canvasId: null,
  canvasName: 'Dashboard',
  charts: new Map(),
  layout: [],
  isConnected: false,
  isLoading: false,
  error: null,

  // Basic setters
  setCanvasId: (id) => set({ canvasId: id }),
  setCanvasName: (name) => set({ canvasName: name }),
  setConnected: (connected) => set({ isConnected: connected }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),

  // Chart actions
  addChart: (chart) =>
    set((state) => {
      const newCharts = new Map(state.charts)
      newCharts.set(chart.id, chart)

      // Add to layout
      const newLayout = [
        ...state.layout,
        {
          i: chart.id,
          x: chart.position.x,
          y: chart.position.y,
          w: chart.position.w,
          h: chart.position.h,
          minW: 3,
          minH: 2,
        },
      ]

      return { charts: newCharts, layout: newLayout }
    }),

  updateChart: (chartId, updates) =>
    set((state) => {
      const chart = state.charts.get(chartId)
      if (!chart) return state

      const newCharts = new Map(state.charts)
      newCharts.set(chartId, { ...chart, ...updates })

      // Update layout if position changed
      let newLayout = state.layout
      if (updates.position) {
        newLayout = state.layout.map((item) =>
          item.i === chartId
            ? {
                ...item,
                x: updates.position!.x,
                y: updates.position!.y,
                w: updates.position!.w,
                h: updates.position!.h,
              }
            : item
        )
      }

      return { charts: newCharts, layout: newLayout }
    }),

  removeChart: (chartId) =>
    set((state) => {
      const newCharts = new Map(state.charts)
      newCharts.delete(chartId)

      const newLayout = state.layout.filter((item) => item.i !== chartId)

      return { charts: newCharts, layout: newLayout }
    }),

  setCharts: (charts) =>
    set(() => {
      const chartMap = new Map<string, Chart>()
      const layout: LayoutItem[] = []

      charts.forEach((chart) => {
        chartMap.set(chart.id, chart)
        layout.push({
          i: chart.id,
          x: chart.position.x,
          y: chart.position.y,
          w: chart.position.w,
          h: chart.position.h,
          minW: 3,
          minH: 2,
        })
      })

      return { charts: chartMap, layout }
    }),

  // Layout actions
  updateLayout: (layout) => set({ layout }),

  // API actions
  createCanvas: async (sessionId, name = 'Analysis Dashboard') => {
    set({ isLoading: true, error: null })
    try {
      const canvas = await api.createCanvas({ session_id: sessionId, name })
      set({
        canvasId: canvas.id,
        canvasName: canvas.name,
        isLoading: false,
      })

      // Update URL with canvas ID
      const url = new URL(window.location.href)
      url.searchParams.set('canvas', canvas.id)
      window.history.replaceState({}, '', url.toString())
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to create canvas',
        isLoading: false,
      })
    }
  },

  fetchCanvas: async (canvasId) => {
    set({ isLoading: true, error: null })
    try {
      const canvas = await api.getCanvas(canvasId)
      const { setCharts } = get()

      set({
        canvasId: canvas.id,
        canvasName: canvas.name,
        isLoading: false,
      })

      setCharts(canvas.charts)
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch canvas',
        isLoading: false,
      })
    }
  },

  saveLayout: async (layout) => {
    const { canvasId } = get()
    if (!canvasId) return

    try {
      const layoutData = layout.map((item) => ({
        chart_id: item.i,
        x: item.x,
        y: item.y,
        w: item.w,
        h: item.h,
      }))

      await api.updateLayout(canvasId, { layout: layoutData })
      set({ layout })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to save layout',
      })
    }
  },

  deleteChartApi: async (chartId) => {
    const { canvasId, removeChart } = get()
    if (!canvasId) return

    try {
      await api.deleteChart(canvasId, chartId)
      removeChart(chartId)
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to delete chart',
      })
    }
  },
}))
