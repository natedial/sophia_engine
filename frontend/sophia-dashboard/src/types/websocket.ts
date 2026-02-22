import type { Chart, ChartPosition } from './canvas'

// Server -> Client messages
export type ServerMessage =
  | ConnectionAckMessage
  | ChartCreatedMessage
  | ChartUpdatedMessage
  | ChartDeletedMessage
  | LayoutUpdatedMessage
  | ErrorMessage
  | PongMessage

export interface ConnectionAckMessage {
  type: 'connection_ack'
  canvas_id: string
  charts: Chart[]
}

export interface ChartCreatedMessage {
  type: 'chart_created'
  chart: Chart
}

export interface ChartUpdatedMessage {
  type: 'chart_updated'
  chart_id: string
  updates: Partial<Chart>
}

export interface ChartDeletedMessage {
  type: 'chart_deleted'
  chart_id: string
}

export interface LayoutUpdatedMessage {
  type: 'layout_updated'
  layout: Array<{
    chart_id: string
    x: number
    y: number
    w: number
    h: number
  }>
}

export interface ErrorMessage {
  type: 'error'
  message: string
  code?: string
}

export interface PongMessage {
  type: 'pong'
}

// Client -> Server messages
export type ClientMessage = LayoutChangedMessage | PingMessage

export interface LayoutChangedMessage {
  type: 'layout_changed'
  layout: Array<{
    chart_id: string
    x: number
    y: number
    w: number
    h: number
  }>
}

export interface PingMessage {
  type: 'ping'
}
