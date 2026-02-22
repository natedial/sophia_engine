// Chart types
export interface Chart {
  id: string
  canvas_id: string
  chart_type: string
  title: string | null
  spec: Record<string, unknown>
  data_query: Record<string, unknown> | null
  position: ChartPosition
  created_at: string | null
  updated_at: string | null
}

export interface ChartPosition {
  x: number
  y: number
  w: number
  h: number
}

// Canvas types
export interface Canvas {
  id: string
  session_id: string
  user_id: string | null
  name: string
  layout: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
  charts: Chart[]
}

// Layout item for react-grid-layout
export interface LayoutItem {
  i: string // chart id
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
}

// API request/response types
export interface CreateCanvasRequest {
  session_id: string
  user_id?: string
  name?: string
}

export interface CreateChartRequest {
  chart_type: string
  title?: string
  spec: Record<string, unknown>
  data_query?: Record<string, unknown>
  position?: ChartPosition
}

export interface UpdateLayoutRequest {
  layout: Array<{
    chart_id: string
    x: number
    y: number
    w: number
    h: number
  }>
}
