import { useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from 'react'
import embed, { Result } from 'vega-embed'

interface VegaChartProps {
  spec: Record<string, unknown>
  className?: string
  onError?: (error: Error) => void
}

export interface VegaChartHandle {
  exportImage: (format: 'png' | 'svg') => Promise<string | null>
  getView: () => any
}

export const VegaChart = forwardRef<VegaChartHandle, VegaChartProps>(
  ({ spec, className = '', onError }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const resultRef = useRef<Result | null>(null)

    // Expose methods to parent via ref
    useImperativeHandle(ref, () => ({
      exportImage: async (format: 'png' | 'svg') => {
        if (!resultRef.current) return null
        try {
          const view = resultRef.current.view
          if (format === 'svg') {
            return await view.toSVG()
          } else {
            const canvas = await view.toCanvas()
            return canvas.toDataURL('image/png')
          }
        } catch (err) {
          console.error('Export failed:', err)
          return null
        }
      },
      getView: () => resultRef.current?.view,
    }))

    useEffect(() => {
      if (!containerRef.current || !spec) return

      // Configure Vega-Embed options
      const options = {
        actions: false, // We'll handle actions ourselves
        theme: 'quartz' as const,
        renderer: 'svg' as const,
        width: 'container' as const,
        height: 'container' as const,
      }

      // Ensure width/height are set for responsiveness
      const responsiveSpec = {
        ...spec,
        width: 'container',
        height: 'container',
        autosize: {
          type: 'fit',
          contains: 'padding',
        },
        config: {
          ...(spec.config as object || {}),
          background: 'transparent',
          axis: {
            labelColor: '#a0aec0',
            titleColor: '#e2e8f0',
            gridColor: '#2d3748',
            domainColor: '#4a5568',
          },
          legend: {
            labelColor: '#a0aec0',
            titleColor: '#e2e8f0',
          },
          title: {
            color: '#e2e8f0',
          },
          view: {
            stroke: 'transparent',
          },
        },
      }

      embed(containerRef.current, responsiveSpec as any, options)
        .then((result) => {
          resultRef.current = result
        })
        .catch((error) => {
          console.error('Vega-Embed error:', error)
          onError?.(error)
        })

      // Cleanup
      return () => {
        if (resultRef.current) {
          resultRef.current.view.finalize()
          resultRef.current = null
        }
      }
    }, [spec, onError])

    return <div ref={containerRef} className={`vega-chart ${className}`} />
  }
)

VegaChart.displayName = 'VegaChart'
