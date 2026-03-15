import axios from 'axios'
import type {
  Canvas,
  Chart,
  CreateCanvasRequest,
  CreateChartRequest,
  UpdateLayoutRequest,
} from '../types/canvas'
import type {
  CatalystRadarRequest,
  GatewayAgentDescriptor,
  GatewayRunRecord,
  RiskLensRequest,
  TradeIdeasRequest,
} from '../types/gateway'
import { useAuthStore } from '../store/authStore'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth token to all requests
api.interceptors.request.use(async (config) => {
  const { getIdToken } = useAuthStore.getState()
  const token = await getIdToken()

  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})

// Canvas API
export async function createCanvas(data: CreateCanvasRequest): Promise<Canvas> {
  const response = await api.post<Canvas>('/canvases', data)
  return response.data
}

export async function getCanvas(canvasId: string): Promise<Canvas> {
  const response = await api.get<Canvas>(`/canvases/${canvasId}`)
  return response.data
}

export async function deleteCanvas(canvasId: string): Promise<void> {
  await api.delete(`/canvases/${canvasId}`)
}

export async function updateLayout(
  canvasId: string,
  data: UpdateLayoutRequest
): Promise<Canvas> {
  const response = await api.patch<Canvas>(`/canvases/${canvasId}/layout`, data)
  return response.data
}

// Chart API
export async function createChart(
  canvasId: string,
  data: CreateChartRequest
): Promise<Chart> {
  const response = await api.post<Chart>(`/canvases/${canvasId}/charts`, data)
  return response.data
}

export async function getChart(canvasId: string, chartId: string): Promise<Chart> {
  const response = await api.get<Chart>(`/canvases/${canvasId}/charts/${chartId}`)
  return response.data
}

export async function updateChart(
  canvasId: string,
  chartId: string,
  data: Partial<CreateChartRequest>
): Promise<Chart> {
  const response = await api.patch<Chart>(
    `/canvases/${canvasId}/charts/${chartId}`,
    data
  )
  return response.data
}

export async function deleteChart(canvasId: string, chartId: string): Promise<void> {
  await api.delete(`/canvases/${canvasId}/charts/${chartId}`)
}

export async function listAgents(): Promise<GatewayAgentDescriptor[]> {
  const response = await api.get<{ agents: GatewayAgentDescriptor[] }>('/v1/agents')
  return response.data.agents
}

export async function getRun(runId: string): Promise<GatewayRunRecord> {
  const response = await api.get<GatewayRunRecord>(`/v1/runs/${runId}`)
  return response.data
}

export async function runCatalystRadar(
  data: CatalystRadarRequest
): Promise<Record<string, unknown>> {
  const response = await api.post<Record<string, unknown>>(
    '/v1/skills/catalyst-radar/run',
    data
  )
  return response.data
}

export async function generateTradeIdeas(
  data: TradeIdeasRequest
): Promise<Record<string, unknown>> {
  const response = await api.post<Record<string, unknown>>(
    '/v1/skills/trade-ideas/generate',
    data
  )
  return response.data
}

export async function analyzeRiskLens(
  data: RiskLensRequest
): Promise<Record<string, unknown>> {
  const response = await api.post<Record<string, unknown>>(
    '/v1/skills/risk-lens/analyze',
    data
  )
  return response.data
}

export default api
