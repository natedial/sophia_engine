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
  CommunicationPreferences,
  ForgePromotionDetail,
  ForgePromotionRunSummary,
  GatewayAgentDescriptor,
  GatewayComponentInventoryItem,
  GatewayRunRecord,
  GatewayRunSummary,
  LLMCatalog,
  PresentationChannelConfig,
  PresentationConfig,
  PresentationRenderTheme,
  RiskLensRequest,
  SelfEditProposal,
  SelfEditProposalStatus,
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

export async function listComponentInventory(): Promise<GatewayComponentInventoryItem[]> {
  const response = await api.get<{ components: GatewayComponentInventoryItem[] }>(
    '/v1/dashboard/components'
  )
  return response.data.components
}

export async function getLLMCatalog(): Promise<LLMCatalog> {
  const response = await api.get<LLMCatalog>('/v1/dashboard/llm/catalog')
  return response.data
}

export async function updateLLMSelection(modelSpec: string): Promise<LLMCatalog> {
  const response = await api.put<LLMCatalog>('/v1/dashboard/llm/selection', {
    model_spec: modelSpec,
  })
  return response.data
}

export async function getRun(runId: string): Promise<GatewayRunRecord> {
  const response = await api.get<GatewayRunRecord>(`/v1/runs/${runId}`)
  return response.data
}

export async function listRuns(params?: {
  limit?: number
  agentId?: string
  status?: string
}): Promise<GatewayRunSummary[]> {
  const response = await api.get<{ runs: GatewayRunSummary[] }>('/v1/dashboard/runs', {
    params: {
      limit: params?.limit,
      agent_id: params?.agentId,
      status: params?.status,
    },
  })
  return response.data.runs
}

export async function getPresentationConfig(): Promise<PresentationConfig> {
  const response = await api.get<PresentationConfig>('/v1/dashboard/presentation')
  return response.data
}

export async function updatePresentationCore(content: string): Promise<string> {
  const response = await api.put<{ core_guidance: string }>(
    '/v1/dashboard/presentation/core',
    { content }
  )
  return response.data.core_guidance
}

export async function updatePresentationChannel(
  channel: string,
  data: Omit<PresentationChannelConfig, 'channel'>
): Promise<PresentationChannelConfig> {
  const response = await api.put<{ channel_config: PresentationChannelConfig }>(
    `/v1/dashboard/presentation/channels/${channel}`,
    data
  )
  return response.data.channel_config
}

export async function updatePresentationTheme(
  data: PresentationRenderTheme
): Promise<PresentationRenderTheme> {
  const response = await api.put<{ render_theme: PresentationRenderTheme }>(
    '/v1/dashboard/presentation/rendering/theme',
    data
  )
  return response.data.render_theme
}

export async function updateCommunicationPreferences(
  data: CommunicationPreferences
): Promise<CommunicationPreferences> {
  const response = await api.put<{ communication_preferences: CommunicationPreferences }>(
    '/v1/dashboard/presentation/preferences',
    data
  )
  return response.data.communication_preferences
}

export async function listProposals(params?: {
  status?: SelfEditProposalStatus
  limit?: number
}): Promise<SelfEditProposal[]> {
  const response = await api.get<{ proposals: SelfEditProposal[] }>(
    '/v1/dashboard/proposals',
    {
      params: {
        status: params?.status,
        limit: params?.limit,
      },
    }
  )
  return response.data.proposals
}

export async function getProposal(proposalId: string): Promise<SelfEditProposal> {
  const response = await api.get<SelfEditProposal>(
    `/v1/dashboard/proposals/${proposalId}`
  )
  return response.data
}

export async function reviewProposal(
  proposalId: string,
  data: { status: 'approved' | 'rejected'; actor?: string; reason?: string }
): Promise<SelfEditProposal> {
  const response = await api.post<SelfEditProposal>(
    `/v1/dashboard/proposals/${proposalId}/review`,
    data
  )
  return response.data
}

export async function listForgePromotions(params?: {
  limit?: number
}): Promise<ForgePromotionRunSummary[]> {
  const response = await api.get<{ runs: ForgePromotionRunSummary[] }>(
    '/v1/dashboard/forge/promotions',
    {
      params: {
        limit: params?.limit,
      },
    }
  )
  return response.data.runs
}

export async function getForgePromotion(
  runId: string
): Promise<ForgePromotionDetail> {
  const response = await api.get<ForgePromotionDetail>(
    `/v1/dashboard/forge/promotions/${runId}`
  )
  return response.data
}

export async function publishForgePromotion(
  runId: string
): Promise<Record<string, unknown>> {
  const response = await api.post<Record<string, unknown>>(
    `/v1/dashboard/forge/promotions/${runId}/publish`
  )
  return response.data
}

export function getForgePromotionArtifactContentUrl(
  runId: string,
  artifactId: string
): string {
  return `/api/v1/dashboard/forge/promotions/${runId}/artifacts/${artifactId}/content`
}

export function getArtifactContentUrl(artifactId: string): string {
  return `/api/v1/dashboard/artifacts/${artifactId}/content`
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
