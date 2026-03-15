export interface GatewayAgentDescriptor {
  agent_id: string
  label: string
  description: string
  tool_allowlist: string[] | null
  skills_enabled: boolean
  subagents_enabled: boolean
}

export interface GatewayRunEvent {
  sequence: number
  event_type: string
  payload: {
    type: string
    data: Record<string, unknown>
  }
  created_at: string
}

export interface GatewayRunRecord {
  run_id: string
  session_id: string
  agent_id: string
  channel: string
  account_id: string
  peer_id: string
  user_id: string | null
  message_text: string
  status: string
  final_text: string | null
  error: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  events: GatewayRunEvent[]
}

export interface CatalystRadarRequest {
  window_hours?: number
  portfolio_profile?: Record<string, unknown>
  include?: Record<string, boolean>
  max_events?: number
  as_of?: string
  session_id?: string
  run_id?: string
}

export interface TradeIdeasRequest {
  horizon?: string
  risk_budget_bps?: number
  max_ideas?: number
  catalyst_ids?: string[]
  portfolio_constraints?: Record<string, unknown>
  style?: string
  session_id?: string
  run_id?: string
}

export interface RiskLensRequest {
  portfolio_id: string
  positions: Array<Record<string, unknown>>
  upcoming_catalyst_ids?: string[]
  nav_usd: number
  session_id?: string
  run_id?: string
}
