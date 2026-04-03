export interface GatewayAgentDescriptor {
  agent_id: string
  label: string
  description: string
  tool_allowlist: string[] | null
  skills_enabled: boolean
  subagents_enabled: boolean
}

export interface GatewayComponentInventoryItem {
  component_id: string
  label: string
  scope: 'agent' | 'memory' | 'tool_service'
  category: 'llm' | 'embedding' | 'non_model' | 'model_registry' | 'unknown'
  provider: string | null
  model_name: string | null
  target: string | null
  tools: string[]
  healthy: boolean | null
  latency_ms: number | null
  error: string | null
  notes: string | null
}

export interface LLMCatalogModelOption {
  model_spec: string
  provider: string
  wire_model: string
  label: string
  description: string
  supports_tool_calls: boolean
  tools: string[]
  selected: boolean
}

export interface LLMCatalog {
  current_model_spec: string
  current_provider: string
  current_wire_model: string
  default_agent_id: string
  models: LLMCatalogModelOption[]
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

export interface GatewaySkillArtifact {
  artifact_id: string
  skill_name: string
  run_id: string | null
  session_id: string | null
  agent_id: string
  payload: Record<string, unknown>
  created_at: string
}

export interface GatewayDeliveryArtifact {
  artifact_id: string
  kind: string
  mime_type: string
  path: string
  caption: string | null
}

export interface GatewayOutboundMessage {
  text: string
  session_id: string
  agent_id: string
  channel: string
  account_id: string
  peer_id: string
  run_id: string | null
  delivery_mode: string
  artifacts: GatewayDeliveryArtifact[]
}

export interface GatewayRunSummary {
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
  failure_stage: string | null
  provider_name: string | null
  tool_name: string | null
  service_name: string | null
  outbound_text_len: number | null
  event_count: number
  skill_artifact_count: number
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
  skill_artifacts: GatewaySkillArtifact[]
  acquisition_jobs?: Array<Record<string, unknown>>
  acquisition_artifacts?: Array<Record<string, unknown>>
  failure_stage?: string | null
  provider_name?: string | null
  tool_name?: string | null
  service_name?: string | null
  outbound_text_len?: number | null
}

export interface PresentationChannelConfig {
  channel: string
  supports_markdown_tables: boolean
  supports_image_attachments: boolean
  supports_document_attachments: boolean
  max_text_chars: number
  preferred_structured_delivery: Record<string, string>
}

export interface PresentationRenderTheme {
  font_family: string
  title_font_size: number
  body_font_size: number
  line_height: number
  margin: number
  char_width: number
  corner_radius: number
  background_start: string
  background_end: string
  panel_fill: string
  panel_stroke: string
  accent: string
  title_color: string
  header_color: string
  text_color: string
  divider_color: string
  shadow_color: string
  header_fill: string
}

export interface CommunicationPreferences {
  big_picture_vs_brevity: 'full_picture' | 'brevity'
  verbose_vs_terse: 'verbose' | 'terse'
  precision_vs_approximation: 'precision' | 'approximation'
  structured_vs_narrative: 'structured' | 'narrative'
  proactive_vs_reactive: 'proactive' | 'reactive'
  decisive_vs_caveated: 'decisive' | 'caveated'
}

export type SelfEditProposalStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'promoted'

export interface SelfEditProposalChange {
  target_path: string
  summary: string
  existed_before: boolean
  current_content_sha256: string
  proposed_content_sha256: string
  current_content: string
  proposed_content: string
}

export interface SelfEditProposal {
  proposal_id: string
  title: string
  rationale: string
  status: SelfEditProposalStatus
  status_reason: string | null
  created_at: string
  updated_at: string
  source_agent_id: string | null
  source_run_id: string | null
  source_session_id: string | null
  review_actor: string | null
  review_timestamp: string | null
  promotion_branch: string | null
  promotion_commit: string | null
  patch_path: string
  changes: SelfEditProposalChange[]
  change_count: number
  patch_text?: string
}

export interface ForgePromotionRunSummary {
  run_id: string
  client_name: string
  status: string
  task: string
  backend: string
  workspace_root: string
  summary: string
  error: string | null
  artifact_ids: string[]
  created_at: string
  updated_at: string
  completed_at: string | null
  promotion_mode: string | null
}

export interface ForgePromotionArtifact {
  artifact_id: string
  run_id: string
  artifact_type: string
  content_type: string
  path: string | null
  payload: Record<string, unknown> | null
  created_at: string
}

export interface ForgePromotionDetail {
  run: {
    run_id: string
    status: string
    summary: string
    error: string | null
    changed_files?: string[]
    artifact_ids?: string[]
  }
  artifacts: ForgePromotionArtifact[]
  content: {
    promotion_status?: Record<string, unknown>
    pr_request?: Record<string, unknown>
    patch?: string
  }
}

export interface PresentationConfig {
  core_guidance: string
  channels: PresentationChannelConfig[]
  render_theme: PresentationRenderTheme
  communication_preferences: CommunicationPreferences
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
