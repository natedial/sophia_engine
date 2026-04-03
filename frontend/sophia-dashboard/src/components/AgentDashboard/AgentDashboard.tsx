import { useEffect, useMemo, useState } from 'react'
import {
  getForgePromotion,
  getForgePromotionArtifactContentUrl,
  getProposal,
  getArtifactContentUrl,
  getLLMCatalog,
  getPresentationConfig,
  getRun,
  listComponentInventory,
  listForgePromotions,
  listProposals,
  listAgents,
  listRuns,
  publishForgePromotion,
  reviewProposal,
  updateLLMSelection,
  updateCommunicationPreferences,
  updatePresentationChannel,
  updatePresentationCore,
  updatePresentationTheme,
} from '../../services/api'
import type {
  CommunicationPreferences,
  ForgePromotionDetail,
  ForgePromotionRunSummary,
  GatewayAgentDescriptor,
  GatewayComponentInventoryItem,
  GatewayRunRecord,
  GatewayRunSummary,
  GatewaySkillArtifact,
  LLMCatalog,
  PresentationChannelConfig,
  PresentationConfig,
  PresentationRenderTheme,
  SelfEditProposal,
} from '../../types/gateway'

type SaveTarget =
  | 'llm'
  | 'core'
  | 'channel'
  | 'theme'
  | 'preferences'
  | 'proposal_approve'
  | 'proposal_reject'
  | 'forge_publish'
  | null

const DELIVERY_KEYS = ['table', 'chart', 'long_report'] as const
const COMMUNICATION_TOGGLES: Array<{
  key: keyof CommunicationPreferences
  label: string
  description: string
  left: CommunicationPreferences[keyof CommunicationPreferences]
  right: CommunicationPreferences[keyof CommunicationPreferences]
  leftLabel: string
  rightLabel: string
}> = [
  {
    key: 'big_picture_vs_brevity',
    label: 'Scope',
    description: 'Choose whether answers should open with the whole situation or compress quickly.',
    left: 'full_picture',
    right: 'brevity',
    leftLabel: 'Full picture',
    rightLabel: 'Brevity',
  },
  {
    key: 'verbose_vs_terse',
    label: 'Length',
    description: 'Bias toward richer explanation or tighter phrasing.',
    left: 'verbose',
    right: 'terse',
    leftLabel: 'Verbose',
    rightLabel: 'Terse',
  },
  {
    key: 'precision_vs_approximation',
    label: 'Numerics',
    description: 'Prefer exact figures and caveats or fast directional estimates.',
    left: 'precision',
    right: 'approximation',
    leftLabel: 'Precision',
    rightLabel: 'Approximation',
  },
  {
    key: 'structured_vs_narrative',
    label: 'Format',
    description: 'Push toward explicit structure or more natural prose.',
    left: 'structured',
    right: 'narrative',
    leftLabel: 'Structured',
    rightLabel: 'Narrative',
  },
  {
    key: 'proactive_vs_reactive',
    label: 'Initiative',
    description: 'Decide whether the agent should volunteer next steps or wait for direction.',
    left: 'proactive',
    right: 'reactive',
    leftLabel: 'Proactive',
    rightLabel: 'Reactive',
  },
  {
    key: 'decisive_vs_caveated',
    label: 'Confidence',
    description: 'Tune between stronger recommendations and more explicit qualification.',
    left: 'decisive',
    right: 'caveated',
    leftLabel: 'Decisive',
    rightLabel: 'Caveated',
  },
]

export function AgentDashboard() {
  const [runs, setRuns] = useState<GatewayRunSummary[]>([])
  const [agents, setAgents] = useState<GatewayAgentDescriptor[]>([])
  const [components, setComponents] = useState<GatewayComponentInventoryItem[]>([])
  const [llmCatalog, setLLMCatalog] = useState<LLMCatalog | null>(null)
  const [selectedModelSpec, setSelectedModelSpec] = useState<string>('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedRun, setSelectedRun] = useState<GatewayRunRecord | null>(null)
  const [forgePromotions, setForgePromotions] = useState<ForgePromotionRunSummary[]>([])
  const [selectedForgeRunId, setSelectedForgeRunId] = useState<string | null>(null)
  const [selectedForgePromotion, setSelectedForgePromotion] =
    useState<ForgePromotionDetail | null>(null)
  const [proposals, setProposals] = useState<SelfEditProposal[]>([])
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null)
  const [selectedProposal, setSelectedProposal] = useState<SelfEditProposal | null>(null)
  const [presentation, setPresentation] = useState<PresentationConfig | null>(null)
  const [selectedChannel, setSelectedChannel] = useState<string>('web')
  const [channelDrafts, setChannelDrafts] = useState<
    Record<string, PresentationChannelConfig>
  >({})
  const [coreDraft, setCoreDraft] = useState('')
  const [themeDraft, setThemeDraft] = useState('')
  const [preferencesDraft, setPreferencesDraft] = useState<CommunicationPreferences | null>(
    null
  )
  const [proposalReviewReason, setProposalReviewReason] = useState('')
  const [activeArtifactId, setActiveArtifactId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshingRun, setIsRefreshingRun] = useState(false)
  const [isRefreshingForgePromotion, setIsRefreshingForgePromotion] = useState(false)
  const [isRefreshingProposal, setIsRefreshingProposal] = useState(false)
  const [saveTarget, setSaveTarget] = useState<SaveTarget>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadDashboard()
  }, [])

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null)
      return
    }
    void loadRun(selectedRunId)
  }, [selectedRunId])

  useEffect(() => {
    if (!selectedProposalId) {
      setSelectedProposal(null)
      return
    }
    void loadProposal(selectedProposalId)
  }, [selectedProposalId])

  useEffect(() => {
    if (!selectedForgeRunId) {
      setSelectedForgePromotion(null)
      return
    }
    void loadForgePromotion(selectedForgeRunId)
  }, [selectedForgeRunId])

  useEffect(() => {
    if (!selectedRun?.skill_artifacts.length) {
      setActiveArtifactId(null)
      return
    }

    const hasActiveArtifact = selectedRun.skill_artifacts.some(
      (artifact) => artifact.artifact_id === activeArtifactId
    )
    if (!hasActiveArtifact) {
      setActiveArtifactId(selectedRun.skill_artifacts[0].artifact_id)
    }
  }, [activeArtifactId, selectedRun])

  const activeArtifact = useMemo(
    () =>
      selectedRun?.skill_artifacts.find(
        (artifact) => artifact.artifact_id === activeArtifactId
      ) ?? null,
    [activeArtifactId, selectedRun]
  )

  const selectedModelOption = useMemo(
    () =>
      llmCatalog?.models.find((model) => model.model_spec === selectedModelSpec) ??
      llmCatalog?.models.find((model) => model.selected) ??
      null,
    [llmCatalog, selectedModelSpec]
  )

  const parsedTheme = useMemo(() => {
    if (!themeDraft.trim()) return null
    try {
      return JSON.parse(themeDraft) as PresentationRenderTheme
    } catch {
      return null
    }
  }, [themeDraft])

  const currentChannelDraft = selectedChannel
    ? channelDrafts[selectedChannel]
    : undefined

  async function loadDashboard() {
    setIsLoading(true)
    setError(null)
    setStatusMessage(null)

    try {
      const [
        runList,
        agentList,
        componentInventory,
        llmModelCatalog,
        presentationConfig,
        proposalList,
        forgePromotionList,
      ] =
        await Promise.all([
        listRuns({ limit: 30 }),
        listAgents(),
        listComponentInventory(),
        getLLMCatalog(),
        getPresentationConfig(),
        listProposals({ limit: 30 }),
        listForgePromotions({ limit: 20 }),
      ])

      setRuns(runList)
      setAgents(agentList)
      setComponents(componentInventory)
      setLLMCatalog(llmModelCatalog)
      setSelectedModelSpec(llmModelCatalog.current_model_spec)
      setProposals(proposalList)
      setForgePromotions(forgePromotionList)
      applyPresentationConfig(presentationConfig)

      const nextRunId = runList[0]?.run_id ?? null
      setSelectedRunId(nextRunId)
      if (nextRunId) {
        await loadRun(nextRunId, false)
      }

      const nextProposalId =
        proposalList.find((proposal) => proposal.status === 'pending')?.proposal_id ??
        proposalList[0]?.proposal_id ??
        null
      setSelectedProposalId(nextProposalId)
      if (nextProposalId) {
        await loadProposal(nextProposalId, false)
      }

      const nextForgeRunId = forgePromotionList[0]?.run_id ?? null
      setSelectedForgeRunId(nextForgeRunId)
      if (nextForgeRunId) {
        await loadForgePromotion(nextForgeRunId, false)
      }
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsLoading(false)
    }
  }

  async function handleSaveLLMSelection() {
    if (!selectedModelSpec || selectedModelSpec === llmCatalog?.current_model_spec) return
    setSaveTarget('llm')
    setError(null)
    try {
      const updatedCatalog = await updateLLMSelection(selectedModelSpec)
      const updatedComponents = await listComponentInventory()
      setLLMCatalog(updatedCatalog)
      setSelectedModelSpec(updatedCatalog.current_model_spec)
      setComponents(updatedComponents)
      setStatusMessage('LLM selection updated. Gateway runtime restarted with the new model.')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaveTarget(null)
    }
  }

  async function loadRun(runId: string, showSpinner = true) {
    if (showSpinner) {
      setIsRefreshingRun(true)
    }
    try {
      const run = await getRun(runId)
      setSelectedRun(run)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      if (showSpinner) {
        setIsRefreshingRun(false)
      }
    }
  }

  async function loadProposal(proposalId: string, showSpinner = true) {
    if (showSpinner) {
      setIsRefreshingProposal(true)
    }
    try {
      const proposal = await getProposal(proposalId)
      setSelectedProposal(proposal)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      if (showSpinner) {
        setIsRefreshingProposal(false)
      }
    }
  }

  async function loadForgePromotion(runId: string, showSpinner = true) {
    if (showSpinner) {
      setIsRefreshingForgePromotion(true)
    }
    try {
      const promotion = await getForgePromotion(runId)
      setSelectedForgePromotion(promotion)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      if (showSpinner) {
        setIsRefreshingForgePromotion(false)
      }
    }
  }

  function applyPresentationConfig(config: PresentationConfig) {
    setPresentation(config)
    setCoreDraft(config.core_guidance)
    setThemeDraft(JSON.stringify(config.render_theme, null, 2))
    setPreferencesDraft(config.communication_preferences)
    setChannelDrafts(
      Object.fromEntries(config.channels.map((channel) => [channel.channel, channel]))
    )
    setSelectedChannel(config.channels[0]?.channel ?? 'web')
  }

  function patchChannelDraft(
    channel: string,
    patch: Partial<PresentationChannelConfig>
  ) {
    setChannelDrafts((current) => {
      const existing = current[channel]
      if (!existing) return current
      return {
        ...current,
        [channel]: {
          ...existing,
          ...patch,
          preferred_structured_delivery: {
            ...existing.preferred_structured_delivery,
            ...patch.preferred_structured_delivery,
          },
        },
      }
    })
  }

  async function handleSaveCore() {
    setSaveTarget('core')
    setError(null)
    try {
      const nextCore = await updatePresentationCore(coreDraft)
      setCoreDraft(nextCore)
      setPresentation((current) =>
        current ? { ...current, core_guidance: nextCore } : current
      )
      setStatusMessage('Core guidance updated.')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaveTarget(null)
    }
  }

  async function handleSaveChannel() {
    if (!currentChannelDraft) return
    setSaveTarget('channel')
    setError(null)
    try {
      const savedChannel = await updatePresentationChannel(currentChannelDraft.channel, {
        supports_markdown_tables: currentChannelDraft.supports_markdown_tables,
        supports_image_attachments: currentChannelDraft.supports_image_attachments,
        supports_document_attachments: currentChannelDraft.supports_document_attachments,
        max_text_chars: currentChannelDraft.max_text_chars,
        preferred_structured_delivery: currentChannelDraft.preferred_structured_delivery,
      })
      patchChannelDraft(savedChannel.channel, savedChannel)
      setPresentation((current) =>
        current
          ? {
              ...current,
              channels: current.channels.map((channel) =>
                channel.channel === savedChannel.channel ? savedChannel : channel
              ),
            }
          : current
      )
      setStatusMessage(`${savedChannel.channel} channel policy updated.`)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaveTarget(null)
    }
  }

  async function handleSaveTheme() {
    if (!parsedTheme) {
      setError('Theme JSON is invalid.')
      return
    }
    setSaveTarget('theme')
    setError(null)
    try {
      const savedTheme = await updatePresentationTheme(parsedTheme)
      setThemeDraft(JSON.stringify(savedTheme, null, 2))
      setPresentation((current) =>
        current ? { ...current, render_theme: savedTheme } : current
      )
      setStatusMessage('Render theme updated.')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaveTarget(null)
    }
  }

  async function handleSavePreferences() {
    if (!preferencesDraft) return
    setSaveTarget('preferences')
    setError(null)
    try {
      const savedPreferences = await updateCommunicationPreferences(preferencesDraft)
      setPreferencesDraft(savedPreferences)
      setPresentation((current) =>
        current ? { ...current, communication_preferences: savedPreferences } : current
      )
      setStatusMessage('Communication preferences updated.')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaveTarget(null)
    }
  }

  async function handleReviewProposal(status: 'approved' | 'rejected') {
    if (!selectedProposal) return
    setSaveTarget(status === 'approved' ? 'proposal_approve' : 'proposal_reject')
    setError(null)
    try {
      const reviewed = await reviewProposal(selectedProposal.proposal_id, {
        status,
        actor: 'dashboard',
        reason: proposalReviewReason.trim(),
      })
      setSelectedProposal(reviewed)
      setProposals((current) =>
        current.map((proposal) =>
          proposal.proposal_id === reviewed.proposal_id
            ? { ...proposal, ...reviewed }
            : proposal
        )
      )
      setProposalReviewReason('')
      setStatusMessage(
        status === 'approved'
          ? 'Proposal approved and marked ready for promotion.'
          : 'Proposal rejected.'
      )
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaveTarget(null)
    }
  }

  async function handlePublishForgePromotion() {
    if (!selectedForgePromotion) return
    setSaveTarget('forge_publish')
    setError(null)
    try {
      await publishForgePromotion(selectedForgePromotion.run.run_id)
      await loadForgePromotion(selectedForgePromotion.run.run_id, false)
      const updatedPromotions = await listForgePromotions({ limit: 20 })
      setForgePromotions(updatedPromotions)
      setStatusMessage('Forge promotion publish request completed.')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaveTarget(null)
    }
  }

  if (isLoading) {
    return (
      <div className="panel loading-panel">
        <p>Loading agent dashboard...</p>
      </div>
    )
  }

  return (
    <div className="agent-dashboard">
      <section className="surface-hero">
        <div className="surface-hero-copy">
          <p className="section-kicker">Agent Ops</p>
          <h2>Trace runtime behavior and tune delivery policy in one surface.</h2>
          <p>
            Inspect persisted runs, verify structured attachments, and update the
            presentation layer without leaving the dashboard.
          </p>
        </div>
        <div className="hero-metrics">
          <MetricCard label="Recent runs" value={String(runs.length)} />
          <MetricCard label="Registered agents" value={String(agents.length)} />
          <MetricCard
            label="Channels configured"
            value={String(presentation?.channels.length ?? 0)}
          />
          <MetricCard
            label="Pending proposals"
            value={String(proposals.filter((proposal) => proposal.status === 'pending').length)}
          />
          <MetricCard
            label="Forge promotions"
            value={String(forgePromotions.length)}
          />
        </div>
      </section>

      {error && <div className="banner banner-error">{error}</div>}
      {statusMessage && <div className="banner banner-success">{statusMessage}</div>}

      <div className="agent-grid">
        <section className="panel llm-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">LLM Control</p>
              <h3>Manual model selection</h3>
            </div>
            <button
              type="button"
              className="primary-button"
              onClick={() => void handleSaveLLMSelection()}
              disabled={
                saveTarget === 'llm' ||
                !llmCatalog ||
                !selectedModelSpec ||
                selectedModelSpec === llmCatalog.current_model_spec
              }
            >
              {saveTarget === 'llm' ? 'Applying...' : 'Apply model'}
            </button>
          </div>

          {llmCatalog ? (
            <>
              <div className="detail-summary">
                <SummaryChip label="Current" value={llmCatalog.current_model_spec} />
                <SummaryChip label="Provider" value={llmCatalog.current_provider} />
                <SummaryChip label="Wire model" value={llmCatalog.current_wire_model} />
                <SummaryChip
                  label="Agent tool count"
                  value={String(selectedModelOption?.tools.length ?? 0)}
                />
              </div>

              <div className="field-stack llm-select-stack">
                <label htmlFor="llm-model-select">Gateway model</label>
                <select
                  id="llm-model-select"
                  value={selectedModelSpec}
                  onChange={(event) => setSelectedModelSpec(event.target.value)}
                >
                  {llmCatalog.models.map((model) => (
                    <option key={model.model_spec} value={model.model_spec}>
                      {model.label} · {model.provider}
                    </option>
                  ))}
                </select>
                <p className="component-notes">
                  Switching the gateway model applies to all agents that share the primary
                  completion provider.
                </p>
              </div>

              {selectedModelOption && (
                <div className="llm-model-card">
                  <div className="component-card-header">
                    <div>
                      <strong>{selectedModelOption.label}</strong>
                      <p className="component-meta">
                        {selectedModelOption.provider} · {selectedModelOption.wire_model}
                      </p>
                    </div>
                    <span
                      className={`status-pill status-${
                        selectedModelOption.supports_tool_calls ? 'completed' : 'neutral'
                      }`}
                    >
                      {selectedModelOption.supports_tool_calls ? 'tool ready' : 'basic'}
                    </span>
                  </div>
                  <p className="component-notes">{selectedModelOption.description}</p>
                  <div className="preference-summary">
                    {selectedModelOption.tools.map((tool) => (
                      <span className="summary-tag" key={tool}>
                        {tool}
                      </span>
                    ))}
                    {selectedModelOption.tools.length === 0 && (
                      <span className="summary-tag">No tool metadata available</span>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : (
            <EmptyPanelMessage text="Model catalog unavailable." />
          )}
        </section>

        <section className="panel inventory-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Component Inventory</p>
              <h3>Models and tool services</h3>
            </div>
          </div>
          <div className="component-grid">
            {components.map((component) => (
              <article key={component.component_id} className="component-card">
                <div className="component-card-header">
                  <div>
                    <strong>{component.label}</strong>
                    <p className="component-meta">
                      {component.scope.replace('_', ' ')} · {component.category.replace('_', ' ')}
                    </p>
                  </div>
                  <span
                    className={`status-pill status-${
                      component.healthy === true
                        ? 'completed'
                        : component.healthy === false
                          ? 'failed'
                          : 'neutral'
                    }`}
                  >
                    {component.healthy === true
                      ? 'healthy'
                      : component.healthy === false
                        ? 'unhealthy'
                        : 'unknown'}
                  </span>
                </div>
                <div className="component-facts">
                  <SummaryChip label="Provider" value={component.provider ?? 'n/a'} />
                  <SummaryChip label="Model" value={component.model_name ?? 'n/a'} />
                  <SummaryChip label="Tools" value={String(component.tools.length)} />
                  <SummaryChip
                    label="Latency"
                    value={
                      component.latency_ms != null
                        ? `${Math.round(component.latency_ms)} ms`
                        : 'n/a'
                    }
                  />
                </div>
                {component.target && (
                  <p className="component-target">
                    <span>Target</span>
                    <code>{component.target}</code>
                  </p>
                )}
                {component.notes && <p className="component-notes">{component.notes}</p>}
                {component.tools.length > 0 && (
                  <div className="preference-summary">
                    {component.tools.map((tool) => (
                      <span className="summary-tag" key={tool}>
                        {tool}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
            {components.length === 0 && (
              <EmptyPanelMessage text="Component inventory unavailable." />
            )}
          </div>
        </section>

        <section className="panel runs-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Run Index</p>
              <h3>Recent executions</h3>
            </div>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void loadDashboard()}
            >
              Refresh
            </button>
          </div>
          <div className="run-list">
            {runs.map((run) => {
              const isActive = run.run_id === selectedRunId
              return (
                <button
                  key={run.run_id}
                  type="button"
                  className={`run-list-item ${isActive ? 'is-active' : ''}`}
                  onClick={() => setSelectedRunId(run.run_id)}
                >
                  <div className="run-list-meta">
                    <span className={`status-pill status-${run.status}`}>
                      {run.status}
                    </span>
                    <span>{formatTimestamp(run.created_at)}</span>
                  </div>
                  <strong>{run.agent_id}</strong>
                  <p>{truncate(run.message_text, 90)}</p>
                  <div className="run-list-footer">
                    <span>{run.channel}</span>
                    <span>{run.event_count} events</span>
                    <span>{run.skill_artifact_count} artifacts</span>
                  </div>
                </button>
              )
            })}
            {runs.length === 0 && <EmptyPanelMessage text="No persisted runs yet." />}
          </div>
        </section>

        <section className="panel trace-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Trace</p>
              <h3>{selectedRun ? selectedRun.run_id : 'Run detail'}</h3>
            </div>
            {isRefreshingRun && <span className="panel-note">Refreshing...</span>}
          </div>

          {selectedRun ? (
            <>
              <div className="detail-summary">
                <SummaryChip label="Agent" value={selectedRun.agent_id} />
                <SummaryChip label="Channel" value={selectedRun.channel} />
                <SummaryChip
                  label="Latency"
                  value={formatDurationBetween(selectedRun.created_at, selectedRun.completed_at)}
                />
                <SummaryChip
                  label="Provider"
                  value={selectedRun.provider_name ?? 'n/a'}
                />
                <SummaryChip
                  label="Last tool"
                  value={selectedRun.tool_name ?? 'n/a'}
                />
              </div>
              <div className="event-stream">
                {selectedRun.events.map((event, index) => (
                  <article key={event.sequence} className="event-card">
                    <div className="event-card-header">
                      <strong>{getEventLabel(event)}</strong>
                      <span>
                        {formatTimestamp(event.created_at)}
                        {' · '}
                        {formatEventDelta(
                          index === 0 ? null : selectedRun.events[index - 1]?.created_at ?? null,
                          event.created_at
                        )}
                      </span>
                    </div>
                    <pre>{JSON.stringify(event.payload.data, null, 2)}</pre>
                  </article>
                ))}
                {selectedRun.events.length === 0 && (
                  <EmptyPanelMessage text="No trace events captured for this run." />
                )}
              </div>
            </>
          ) : (
            <EmptyPanelMessage text="Select a run to inspect its trace." />
          )}
        </section>

        <section className="panel output-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Rendered Output</p>
              <h3>Final message and attachments</h3>
            </div>
          </div>

          {selectedRun ? (
            <div className="output-layout">
              <div className="output-copy">
                <label className="panel-label">Final text</label>
                <pre className="output-block">
                  {selectedRun.final_text ?? '(no final text)'}
                </pre>
              </div>
              <div className="artifact-column">
                <div className="artifact-tabs">
                  {selectedRun.skill_artifacts.map((artifact) => (
                    <button
                      key={artifact.artifact_id}
                      type="button"
                      className={`artifact-tab ${
                        artifact.artifact_id === activeArtifactId ? 'is-active' : ''
                      }`}
                      onClick={() => setActiveArtifactId(artifact.artifact_id)}
                    >
                      {artifact.skill_name}
                    </button>
                  ))}
                </div>
                {activeArtifact ? (
                  <ArtifactPreview artifact={activeArtifact} />
                ) : (
                  <EmptyPanelMessage text="This run has no persisted artifacts." />
                )}
              </div>
            </div>
          ) : (
            <EmptyPanelMessage text="Select a run to inspect its output." />
          )}
        </section>

        <section className="panel guidelines-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Presentation Core</p>
              <h3>Global output guidance</h3>
            </div>
            <button
              type="button"
              className="primary-button"
              onClick={() => void handleSaveCore()}
              disabled={saveTarget === 'core'}
            >
              {saveTarget === 'core' ? 'Saving...' : 'Save core'}
            </button>
          </div>
          <textarea
            className="policy-textarea"
            value={coreDraft}
            onChange={(event) => setCoreDraft(event.target.value)}
            spellCheck={false}
          />
        </section>

        <section className="panel communication-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Communication Preferences</p>
              <h3>Binary response controls</h3>
            </div>
            <button
              type="button"
              className="primary-button"
              onClick={() => void handleSavePreferences()}
              disabled={saveTarget === 'preferences' || !preferencesDraft}
            >
              {saveTarget === 'preferences' ? 'Saving...' : 'Save preferences'}
            </button>
          </div>

          {preferencesDraft ? (
            <>
              <div className="preference-grid">
                {COMMUNICATION_TOGGLES.map((toggle) => (
                  <article className="preference-card" key={toggle.key}>
                    <div className="preference-copy">
                      <h4>{toggle.label}</h4>
                      <p>{toggle.description}</p>
                    </div>
                    <div className="preference-segment">
                      <button
                        type="button"
                        className={`segment-button ${
                          preferencesDraft[toggle.key] === toggle.left ? 'is-active' : ''
                        }`}
                        onClick={() =>
                          setPreferencesDraft((current) =>
                            current ? { ...current, [toggle.key]: toggle.left } : current
                          )
                        }
                      >
                        {toggle.leftLabel}
                      </button>
                      <button
                        type="button"
                        className={`segment-button ${
                          preferencesDraft[toggle.key] === toggle.right ? 'is-active' : ''
                        }`}
                        onClick={() =>
                          setPreferencesDraft((current) =>
                            current ? { ...current, [toggle.key]: toggle.right } : current
                          )
                        }
                      >
                        {toggle.rightLabel}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
              <div className="preference-summary">
                {COMMUNICATION_TOGGLES.map((toggle) => (
                  <span className="summary-tag" key={toggle.key}>
                    {toggle.label}: {preferencesDraft[toggle.key].replace('_', ' ')}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <EmptyPanelMessage text="Communication preferences unavailable." />
          )}
        </section>

        <section className="panel proposals-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Proposal Review</p>
              <h3>Pending self-edit changes</h3>
            </div>
            {isRefreshingProposal && <span className="panel-note">Refreshing...</span>}
          </div>

          <div className="proposal-layout">
            <div className="proposal-list">
              {proposals.map((proposal) => (
                <button
                  key={proposal.proposal_id}
                  type="button"
                  className={`run-list-item ${
                    proposal.proposal_id === selectedProposalId ? 'is-active' : ''
                  }`}
                  onClick={() => setSelectedProposalId(proposal.proposal_id)}
                >
                  <div className="run-list-meta">
                    <span className={`status-pill status-${proposal.status}`}>
                      {proposal.status}
                    </span>
                    <span>{formatTimestamp(proposal.updated_at)}</span>
                  </div>
                  <strong>{proposal.title}</strong>
                  <p>{truncate(proposal.rationale, 96)}</p>
                  <div className="run-list-footer">
                    <span>{proposal.change_count} changes</span>
                    <span>{proposal.source_agent_id ?? 'unknown agent'}</span>
                  </div>
                </button>
              ))}
              {proposals.length === 0 && (
                <EmptyPanelMessage text="No reviewable proposals found." />
              )}
            </div>

            <div className="proposal-detail">
              {selectedProposal ? (
                <>
                  <div className="detail-summary">
                    <SummaryChip label="Status" value={selectedProposal.status} />
                    <SummaryChip
                      label="Source run"
                      value={selectedProposal.source_run_id ?? 'n/a'}
                    />
                    <SummaryChip
                      label="Reviewer"
                      value={selectedProposal.review_actor ?? 'unreviewed'}
                    />
                    <SummaryChip
                      label="Updated"
                      value={formatTimestamp(selectedProposal.updated_at)}
                    />
                  </div>

                  <div className="proposal-copy">
                    <h4>{selectedProposal.title}</h4>
                    <p>{selectedProposal.rationale}</p>
                  </div>

                  <div className="proposal-changes">
                    {selectedProposal.changes.map((change) => (
                      <article className="proposal-change-card" key={change.target_path}>
                        <div className="event-card-header">
                          <strong>{change.target_path}</strong>
                          <span>{change.existed_before ? 'update' : 'new file'}</span>
                        </div>
                        <p>{change.summary || 'No summary provided.'}</p>
                        <div className="proposal-change-columns">
                          <div>
                            <label className="panel-label">Current</label>
                            <pre className="output-block">
                              {change.current_content || '(empty file)'}
                            </pre>
                          </div>
                          <div>
                            <label className="panel-label">Proposed</label>
                            <pre className="output-block">{change.proposed_content}</pre>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>

                  <div>
                    <label className="panel-label">Unified patch</label>
                    <pre className="output-block proposal-patch">
                      {selectedProposal.patch_text ?? '(patch unavailable)'}
                    </pre>
                  </div>

                  <div className="proposal-review-box">
                    <label className="field-stack proposal-reason">
                      <span>Review note</span>
                      <textarea
                        className="policy-textarea proposal-textarea"
                        value={proposalReviewReason}
                        onChange={(event) => setProposalReviewReason(event.target.value)}
                        placeholder="Optional acceptance or rejection note"
                        spellCheck={false}
                      />
                    </label>
                    <div className="proposal-actions">
                      <button
                        type="button"
                        className="primary-button"
                        onClick={() => void handleReviewProposal('approved')}
                        disabled={
                          selectedProposal.status !== 'pending' ||
                          saveTarget === 'proposal_approve'
                        }
                      >
                        {saveTarget === 'proposal_approve' ? 'Approving...' : 'Accept proposal'}
                      </button>
                      <button
                        type="button"
                        className="secondary-button danger-button"
                        onClick={() => void handleReviewProposal('rejected')}
                        disabled={
                          selectedProposal.status !== 'pending' ||
                          saveTarget === 'proposal_reject'
                        }
                      >
                        {saveTarget === 'proposal_reject' ? 'Rejecting...' : 'Reject proposal'}
                      </button>
                    </div>
                    {selectedProposal.status !== 'pending' && (
                      <p className="panel-note">
                        Review completed. Promotion remains a separate git-side action.
                      </p>
                    )}
                  </div>
                </>
              ) : (
                <EmptyPanelMessage text="Select a proposal to review its patch." />
              )}
            </div>
          </div>
        </section>

        <section className="panel forge-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Forge Promotions</p>
              <h3>Patch and draft PR outputs</h3>
            </div>
            <div className="forge-panel-actions">
              {isRefreshingForgePromotion && <span className="panel-note">Refreshing...</span>}
              <button
                type="button"
                className="primary-button"
                onClick={() => void handlePublishForgePromotion()}
                disabled={
                  !selectedForgePromotion?.content.pr_request ||
                  String(
                    selectedForgePromotion.content.pr_request.publish_status ?? ''
                  ) === 'published' ||
                  saveTarget === 'forge_publish'
                }
              >
                {saveTarget === 'forge_publish' ? 'Publishing...' : 'Publish PR'}
              </button>
            </div>
          </div>

          <div className="proposal-layout">
            <div className="proposal-list">
              {forgePromotions.map((promotion) => (
                <button
                  key={promotion.run_id}
                  type="button"
                  className={`run-list-item ${
                    promotion.run_id === selectedForgeRunId ? 'is-active' : ''
                  }`}
                  onClick={() => setSelectedForgeRunId(promotion.run_id)}
                >
                  <div className="run-list-meta">
                    <span className={`status-pill status-${promotion.status}`}>
                      {promotion.status}
                    </span>
                    <span>{promotion.promotion_mode ?? 'no mode'}</span>
                  </div>
                  <strong>{promotion.run_id}</strong>
                  <p>{truncate(promotion.task, 96)}</p>
                  <div className="run-list-footer">
                    <span>{promotion.backend}</span>
                    <span>{formatTimestamp(promotion.updated_at)}</span>
                  </div>
                </button>
              ))}
              {forgePromotions.length === 0 && (
                <EmptyPanelMessage text="No Forge patch or draft PR promotions found." />
              )}
            </div>

            <div className="proposal-detail">
              {selectedForgePromotion ? (
                <>
                  <div className="detail-summary">
                    <SummaryChip
                      label="Run"
                      value={selectedForgePromotion.run.run_id}
                    />
                    <SummaryChip
                      label="Status"
                      value={selectedForgePromotion.run.status}
                    />
                    <SummaryChip
                      label="Promotion"
                      value={String(
                        selectedForgePromotion.content.promotion_status?.mode ?? 'n/a'
                      )}
                    />
                    <SummaryChip
                      label="PR state"
                      value={String(
                        selectedForgePromotion.content.pr_request?.publish_status ?? 'n/a'
                      )}
                    />
                  </div>

                  <div className="proposal-copy">
                    <h4>{selectedForgePromotion.run.summary || 'Forge promotion run'}</h4>
                    <p>{selectedForgePromotion.run.error ?? 'Promotion artifacts ready for review.'}</p>
                  </div>

                  {selectedForgePromotion.content.pr_request && (
                    <article className="proposal-change-card">
                      <div className="event-card-header">
                        <strong>Draft PR request</strong>
                        <span>
                          {String(
                            selectedForgePromotion.content.pr_request.publish_status ?? 'unknown'
                          )}
                        </span>
                      </div>
                      <div className="forge-meta-grid">
                        <SummaryChip
                          label="Base branch"
                          value={String(
                            selectedForgePromotion.content.pr_request.base_branch ?? 'n/a'
                          )}
                        />
                        <SummaryChip
                          label="Branch"
                          value={String(
                            selectedForgePromotion.content.pr_request.branch_name ?? 'n/a'
                          )}
                        />
                        <SummaryChip
                          label="Title"
                          value={String(
                            selectedForgePromotion.content.pr_request.pr_title ?? 'n/a'
                          )}
                        />
                        <SummaryChip
                          label="Commit"
                          value={String(
                            selectedForgePromotion.content.pr_request.commit_sha ?? 'n/a'
                          )}
                        />
                      </div>
                    </article>
                  )}

                  {selectedForgePromotion.content.promotion_status && (
                    <article className="proposal-change-card">
                      <div className="event-card-header">
                        <strong>Promotion status</strong>
                        <span>
                          {String(
                            selectedForgePromotion.content.promotion_status.status ?? 'unknown'
                          )}
                        </span>
                      </div>
                      <pre className="output-block">
                        {JSON.stringify(
                          selectedForgePromotion.content.promotion_status,
                          null,
                          2
                        )}
                      </pre>
                    </article>
                  )}

                  {selectedForgePromotion.content.patch && (
                    <div>
                      <label className="panel-label">Patch</label>
                      <pre className="output-block proposal-patch">
                        {selectedForgePromotion.content.patch}
                      </pre>
                    </div>
                  )}

                  <div className="artifact-links">
                    {selectedForgePromotion.artifacts.map((artifact) => (
                      <a
                        key={artifact.artifact_id}
                        href={getForgePromotionArtifactContentUrl(
                          selectedForgePromotion.run.run_id,
                          artifact.artifact_id
                        )}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {artifact.artifact_type}
                      </a>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyPanelMessage text="Select a Forge promotion to inspect its artifacts." />
              )}
            </div>
          </div>
        </section>

        <section className="panel channel-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Channel Policy</p>
              <h3>Per-surface delivery constraints</h3>
            </div>
            <button
              type="button"
              className="primary-button"
              onClick={() => void handleSaveChannel()}
              disabled={saveTarget === 'channel' || !currentChannelDraft}
            >
              {saveTarget === 'channel' ? 'Saving...' : 'Save channel'}
            </button>
          </div>

          {presentation?.channels.length ? (
            <>
              <div className="channel-tabs">
                {presentation.channels.map((channel) => (
                  <button
                    key={channel.channel}
                    type="button"
                    className={`artifact-tab ${
                      channel.channel === selectedChannel ? 'is-active' : ''
                    }`}
                    onClick={() => setSelectedChannel(channel.channel)}
                  >
                    {channel.channel}
                  </button>
                ))}
              </div>

              {currentChannelDraft && (
                <div className="form-grid">
                  <label className="toggle-row">
                    <input
                      type="checkbox"
                      checked={currentChannelDraft.supports_markdown_tables}
                      onChange={(event) =>
                        patchChannelDraft(currentChannelDraft.channel, {
                          supports_markdown_tables: event.target.checked,
                        })
                      }
                    />
                    Markdown tables render cleanly
                  </label>
                  <label className="toggle-row">
                    <input
                      type="checkbox"
                      checked={currentChannelDraft.supports_image_attachments}
                      onChange={(event) =>
                        patchChannelDraft(currentChannelDraft.channel, {
                          supports_image_attachments: event.target.checked,
                        })
                      }
                    />
                    Image attachments supported
                  </label>
                  <label className="toggle-row">
                    <input
                      type="checkbox"
                      checked={currentChannelDraft.supports_document_attachments}
                      onChange={(event) =>
                        patchChannelDraft(currentChannelDraft.channel, {
                          supports_document_attachments: event.target.checked,
                        })
                      }
                    />
                    Document attachments supported
                  </label>
                  <label className="field-stack">
                    <span>Max text chars</span>
                    <input
                      type="number"
                      value={currentChannelDraft.max_text_chars}
                      onChange={(event) =>
                        patchChannelDraft(currentChannelDraft.channel, {
                          max_text_chars: Number(event.target.value) || 1,
                        })
                      }
                    />
                  </label>
                  {DELIVERY_KEYS.map((key) => (
                    <label className="field-stack" key={key}>
                      <span>{key.replace('_', ' ')}</span>
                      <select
                        value={currentChannelDraft.preferred_structured_delivery[key] ?? 'text'}
                        onChange={(event) =>
                          patchChannelDraft(currentChannelDraft.channel, {
                            preferred_structured_delivery: {
                              [key]: event.target.value,
                            },
                          })
                        }
                      >
                        <option value="text">text</option>
                        <option value="image">image</option>
                        <option value="document">document</option>
                      </select>
                    </label>
                  ))}
                </div>
              )}
            </>
          ) : (
            <EmptyPanelMessage text="No channel policies found." />
          )}
        </section>

        <section className="panel theme-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">Render Theme</p>
              <h3>Structured attachment styling</h3>
            </div>
            <button
              type="button"
              className="primary-button"
              onClick={() => void handleSaveTheme()}
              disabled={saveTarget === 'theme'}
            >
              {saveTarget === 'theme' ? 'Saving...' : 'Save theme'}
            </button>
          </div>
          <div className="theme-preview">
            <span
              className="theme-swatch"
              style={{
                background: `linear-gradient(135deg, ${
                  parsedTheme?.background_start ?? '#0b1020'
                }, ${parsedTheme?.background_end ?? '#172033'})`,
              }}
            />
            <div>
              <strong>{parsedTheme?.font_family ?? 'Theme draft'}</strong>
              <p>
                Accent {parsedTheme?.accent ?? 'n/a'} · Panel{' '}
                {parsedTheme?.panel_fill ?? 'n/a'}
              </p>
            </div>
          </div>
          <textarea
            className="policy-textarea theme-textarea"
            value={themeDraft}
            onChange={(event) => setThemeDraft(event.target.value)}
            spellCheck={false}
          />
          {!parsedTheme && themeDraft.trim() && (
            <p className="panel-note error-note">Theme JSON must be valid before saving.</p>
          )}
        </section>
      </div>
    </div>
  )
}

function ArtifactPreview({ artifact }: { artifact: GatewaySkillArtifact }) {
  const mimeType = String(artifact.payload.mime_type ?? '')
  const rawPath = String(artifact.payload.path ?? '')
  const contentUrl = getArtifactContentUrl(artifact.artifact_id)
  const isImageArtifact = mimeType.startsWith('image/')

  return (
    <div className="artifact-preview">
      <div className="artifact-meta">
        <span className="status-pill status-neutral">{String(artifact.payload.kind ?? 'artifact')}</span>
        <span>{mimeType || 'unknown mime'}</span>
      </div>
      {isImageArtifact ? (
        <div className="artifact-canvas">
          <img src={contentUrl} alt={artifact.skill_name} />
        </div>
      ) : (
        <div className="output-block">
          <p>Artifact preview unavailable for this mime type.</p>
        </div>
      )}
      <div className="artifact-links">
        <a href={contentUrl} target="_blank" rel="noreferrer">
          Open artifact
        </a>
        {rawPath && <span>{truncate(rawPath, 72)}</span>}
      </div>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function SummaryChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="summary-chip">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function EmptyPanelMessage({ text }: { text: string }) {
  return <p className="empty-panel-message">{text}</p>
}

function formatTimestamp(value: string | null) {
  if (!value) return 'n/a'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatDurationBetween(start: string | null, end: string | null) {
  if (!start || !end) return 'n/a'
  const deltaMs = new Date(end).getTime() - new Date(start).getTime()
  return formatMilliseconds(deltaMs)
}

function formatEventDelta(previous: string | null, current: string | null) {
  if (!current) return 'n/a'
  if (!previous) return '+0 ms'
  const deltaMs = new Date(current).getTime() - new Date(previous).getTime()
  return `+${formatMilliseconds(deltaMs)}`
}

function formatMilliseconds(value: number) {
  if (!Number.isFinite(value) || value < 0) return 'n/a'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(2)} s`
}

function getEventLabel(event: GatewayRunRecord['events'][number]) {
  const payload = event.payload.data
  if (event.event_type === 'trace' && typeof payload.stage === 'string') {
    return `${event.event_type} · ${payload.stage}`
  }
  return event.event_type
}

function truncate(value: string, maxLength: number) {
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 1)}…`
}

function getErrorMessage(error: unknown) {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail ===
      'string'
  ) {
    return String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail)
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Request failed'
}
