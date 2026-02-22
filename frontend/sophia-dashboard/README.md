# Sophia Dashboard

A React-based visualization dashboard for the Sophia economic analysis agent. This frontend displays interactive charts created by Sophia in real-time via WebSocket connections.

## Features

- **Real-time Chart Updates**: WebSocket connection to sophia_canvas service for live chart creation/updates
- **Interactive Dashboard**: Drag-and-drop chart positioning with react-grid-layout
- **Vega-Lite Visualizations**: Renders declarative chart specifications with full interactivity
- **Chart Export**: Export charts as PNG or SVG
- **AWS Cognito Authentication**: Secure access with JWT-based authentication
- **Dark Theme**: Professional dark UI optimized for data visualization

## Tech Stack

- **React 18** + TypeScript
- **Vite** - Build tool
- **Zustand** - State management
- **react-grid-layout** - Draggable/resizable grid
- **react-vega** / **vega-lite** - Chart rendering
- **AWS Amplify Auth** - Cognito integration
- **Axios** - HTTP client

## Project Structure

```
src/
├── components/
│   ├── Auth/
│   │   ├── LoginPage.tsx      # Sign in/register/confirm forms
│   │   ├── UserMenu.tsx       # Header user dropdown
│   │   ├── ProtectedRoute.tsx # Auth wrapper component
│   │   └── Auth.css           # Auth component styles
│   ├── Canvas/
│   │   ├── Canvas.tsx         # Main dashboard grid
│   │   ├── ChartCard.tsx      # Individual chart wrapper
│   │   └── ChartModal.tsx     # Fullscreen chart view
│   ├── Charts/
│   │   ├── VegaChart.tsx      # Vega-Lite renderer
│   │   └── ChartToolbar.tsx   # Chart action buttons
│   └── Layout/
│       └── Header.tsx         # App header with user menu
├── config/
│   └── amplify.ts             # AWS Amplify configuration
├── hooks/
│   └── useWebSocket.ts        # WebSocket connection hook
├── services/
│   └── api.ts                 # REST API client with auth
├── store/
│   ├── authStore.ts           # Authentication state
│   └── canvasStore.ts         # Canvas/chart state
├── styles/
│   ├── index.css              # CSS variables and base styles
│   └── App.css                # Application styles
├── types/
│   ├── canvas.ts              # Canvas/chart type definitions
│   └── websocket.ts           # WebSocket message types
├── App.tsx                    # Main application component
└── main.tsx                   # Entry point with Amplify setup
```

## Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn
- Running sophia_canvas backend service

### Installation

```bash
cd frontend/sophia-dashboard
npm install
```

### Configuration

Create a `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

#### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `VITE_COGNITO_USER_POOL_ID` | AWS Cognito User Pool ID | No* |
| `VITE_COGNITO_CLIENT_ID` | AWS Cognito App Client ID | No* |

*When not set, authentication is disabled and the app runs in development mode with a mock user.

### Development

```bash
npm run dev
```

The development server runs on `http://localhost:3000` with hot module replacement.

### Production Build

```bash
npm run build
```

Output is generated in the `dist/` directory.

## Authentication

### Overview

The dashboard uses AWS Cognito for authentication. When properly configured, users must sign in to access the dashboard. The authentication flow supports:

- Email/password sign in
- New user registration
- Email verification with confirmation code
- Session persistence (stays logged in)

### Development Mode

When Cognito environment variables are not set, authentication is bypassed:
- A mock "developer" user is automatically signed in
- All API requests work without JWT tokens (backend must also have `AUTH_ENABLED=false`)
- Useful for local development and testing

### Production Mode

With Cognito configured:
1. Users see a login page on first visit
2. After authentication, JWT tokens are stored by Amplify
3. Tokens are automatically included in:
   - All REST API requests (via Axios interceptor)
   - WebSocket connections (via query parameter)
4. Tokens are refreshed automatically by Amplify

### Auth Store (`store/authStore.ts`)

The Zustand auth store provides:

```typescript
interface AuthState {
  user: AuthUser | null        // Current user info
  isAuthenticated: boolean     // Auth status
  isLoading: boolean           // Loading state
  isAuthEnabled: boolean       // Whether Cognito is configured
  error: string | null         // Error message

  initialize(): Promise<void>  // Check existing session
  login(email, password): Promise<void>
  logout(): Promise<void>
  register(email, password): Promise<{ requiresConfirmation: boolean }>
  confirmRegistration(email, code): Promise<void>
  getIdToken(): Promise<string | null>  // Get JWT for API calls
}
```

### Auth Components

#### LoginPage (`components/Auth/LoginPage.tsx`)

Full-featured authentication form with three modes:
- **Sign In**: Email/password login
- **Register**: Create new account
- **Confirm**: Enter verification code sent to email

#### UserMenu (`components/Auth/UserMenu.tsx`)

Header dropdown component showing:
- User avatar (first letter of email)
- User email address
- Sign out button

#### ProtectedRoute (`components/Auth/ProtectedRoute.tsx`)

Wrapper component that:
- Shows loading spinner during auth initialization
- Renders `LoginPage` if not authenticated
- Renders children if authenticated or auth is disabled

## WebSocket Connection

### Connection Flow

1. User authenticates (or dev mode activates)
2. Canvas is created or fetched via REST API
3. WebSocket connects to `/ws/{canvas_id}?token={jwt}`
4. Server sends `connection_ack` with canvas info
5. Real-time updates flow as agent creates charts

### Message Types

**Server → Client:**

| Event | Description |
|-------|-------------|
| `connection_ack` | Connection established with canvas ID and user info |
| `chart_created` | New chart added by agent |
| `chart_updated` | Chart spec or position changed |
| `chart_deleted` | Chart removed |
| `layout_updated` | Dashboard layout changed |
| `pong` | Heartbeat response |

**Client → Server:**

| Event | Description |
|-------|-------------|
| `ping` | Heartbeat (sent every 30 seconds) |
| `layout_changed` | User moved/resized charts |

### Reconnection

The WebSocket hook (`hooks/useWebSocket.ts`) implements exponential backoff reconnection:
- Delays: 1s, 2s, 4s, 8s, 16s, 30s
- Automatically reconnects on disconnect
- Resets attempt counter on successful connection
- Only connects when authenticated

## Canvas Store (`store/canvasStore.ts`)

Manages dashboard state with Zustand:

```typescript
interface CanvasState {
  canvasId: string | null
  canvasName: string
  charts: Map<string, Chart>
  layout: LayoutItem[]
  isConnected: boolean
  isLoading: boolean
  error: string | null

  // Chart actions
  addChart(chart): void
  updateChart(chartId, updates): void
  removeChart(chartId): void
  setCharts(charts): void

  // API actions
  createCanvas(sessionId, name): Promise<void>
  fetchCanvas(canvasId): Promise<void>
  saveLayout(layout): Promise<void>
  deleteChartApi(chartId): Promise<void>
}
```

## Chart Components

### VegaChart (`components/Charts/VegaChart.tsx`)

Renders Vega-Lite specifications with:
- Automatic resizing to container
- Dark theme integration
- Export methods (PNG/SVG) via ref
- Error handling for invalid specs

```tsx
const chartRef = useRef<VegaChartHandle>(null)

<VegaChart
  ref={chartRef}
  spec={vegaLiteSpec}
  onError={(error) => console.error(error)}
/>

// Export via ref
const pngData = await chartRef.current.exportImage('png')
const svgData = await chartRef.current.exportImage('svg')
```

### ChartCard (`components/Canvas/ChartCard.tsx`)

Wraps each chart in the dashboard grid with:
- Draggable header (for react-grid-layout)
- Toolbar with actions:
  - Expand to fullscreen modal
  - Refresh chart data
  - Export as PNG/SVG
  - Delete chart
- Chart type badge
- Last updated timestamp

### ChartModal (`components/Canvas/ChartModal.tsx`)

Fullscreen chart view with:
- Larger rendering area for detailed analysis
- Export buttons (PNG/SVG)
- Keyboard support (Escape to close)
- Click outside to close
- Data query display in footer

## Styling

### CSS Variables

The app uses CSS custom properties for theming (defined in `styles/index.css`):

```css
:root {
  /* Colors */
  --color-bg: #0a0a0f;
  --color-bg-secondary: #12121a;
  --color-bg-card: #16161f;
  --color-border: #27272a;
  --color-primary: #6366f1;
  --color-primary-hover: #818cf8;
  --color-success: #22c55e;
  --color-danger: #ef4444;
  --color-text: #e4e4e7;
  --color-text-secondary: #a1a1aa;
  --color-text-muted: #71717a;

  /* Spacing */
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;

  /* Typography */
  --font-sans: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* Effects */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.4);
}
```

## API Integration

### REST Endpoints

The API client (`services/api.ts`) communicates with sophia_canvas:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/canvases` | Create new canvas |
| GET | `/api/canvases/{id}` | Get canvas with charts |
| DELETE | `/api/canvases/{id}` | Delete canvas |
| PATCH | `/api/canvases/{id}/layout` | Update chart positions |
| POST | `/api/canvases/{id}/charts` | Create chart |
| GET | `/api/canvases/{id}/charts/{chartId}` | Get single chart |
| PATCH | `/api/canvases/{id}/charts/{chartId}` | Update chart |
| DELETE | `/api/canvases/{id}/charts/{chartId}` | Delete chart |

### Authentication Header

All requests automatically include the JWT token via Axios interceptor:

```typescript
api.interceptors.request.use(async (config) => {
  const { getIdToken } = useAuthStore.getState()
  const token = await getIdToken()

  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})
```

## Deployment

### Docker

Build and serve via nginx:

```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_COGNITO_USER_POOL_ID
ARG VITE_COGNITO_CLIENT_ID
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

Build with environment variables:

```bash
docker build \
  --build-arg VITE_COGNITO_USER_POOL_ID=us-east-1_xxxxx \
  --build-arg VITE_COGNITO_CLIENT_ID=xxxxx \
  -t sophia-dashboard .
```

### AWS (S3 + CloudFront)

1. Build the production bundle:
   ```bash
   VITE_COGNITO_USER_POOL_ID=xxx VITE_COGNITO_CLIENT_ID=xxx npm run build
   ```

2. Upload `dist/` contents to S3 bucket

3. Configure CloudFront distribution:
   - Origin: S3 bucket
   - Default root object: `index.html`
   - Error pages: Redirect 403/404 to `/index.html` with 200 status (for SPA routing)

4. Set up HTTPS with ACM certificate

### Vite Proxy (Development)

The Vite dev server proxies API requests to the backend. Configure in `vite.config.ts`:

```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8003',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/ws': {
        target: 'ws://localhost:8003',
        ws: true,
      },
    },
  },
})
```

## Usage

1. Start the sophia_canvas backend service on port 8003
2. Run the dashboard: `npm run dev`
3. Open http://localhost:3000
4. Sign in (or auto-signed in as dev user if auth disabled)
5. A new canvas will be created automatically
6. Ask Sophia to create charts - they appear in real-time!

Example Sophia commands that create charts:
- "Show me GDP growth over the last 5 years"
- "Create a comparison of CPI and PPI"
- "Display the current yield curve"
- "Plot unemployment vs inflation as a scatter chart"

## Troubleshooting

### WebSocket Connection Issues

1. Check that sophia_canvas is running on port 8003
2. Verify Vite proxy configuration for `/ws` endpoint
3. Check browser console for connection errors
4. Ensure JWT token is valid (not expired)
5. Look for close code 4001 (authentication required)

### Authentication Issues

1. Verify Cognito User Pool ID and Client ID are correct
2. Check that the Cognito App Client has proper settings:
   - Auth flows: `ALLOW_USER_PASSWORD_AUTH`
   - No client secret (required for browser apps)
3. Check browser console for Amplify errors
4. Clear browser storage and retry

### Charts Not Rendering

1. Verify Vega-Lite spec is valid JSON
2. Check browser console for Vega parsing errors
3. Ensure chart container has non-zero dimensions
4. Try the spec in the [Vega Editor](https://vega.github.io/editor/)

### Layout Not Saving

1. Check network tab for failed PATCH requests
2. Verify canvas ID is valid
3. Check for 401/403 errors (auth issues)
4. Ensure WebSocket is connected (changes broadcast to other clients)

## License

Internal use only - Sophia Project
