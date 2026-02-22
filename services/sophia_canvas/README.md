# Sophia Canvas

Visualization and charting service for the Sophia ecosystem.

## Overview

Sophia Canvas provides a backend for managing visualization dashboards that the Sophia agent can dynamically populate with charts. It supports:

- **Canvas management**: Create/read/update/delete dashboards
- **Chart CRUD**: Create and manage Vega-Lite chart specifications
- **WebSocket updates**: Real-time push notifications when charts change
- **Grid layouts**: Position charts in a dashboard grid

## Running Locally

```bash
# Install dependencies
pip install -e .

# Set environment variables
export CANVAS_DATABASE_URL="postgresql://user:pass@localhost:5432/sophia"

# Run the service
python -m sophia_canvas.main
```

Or use the entry point:

```bash
sophia-canvas
```

## API Endpoints

### Canvases

- `POST /canvases` - Create a new canvas
- `GET /canvases/{id}` - Get canvas with charts
- `GET /canvases` - List canvases (filterable)
- `PATCH /canvases/{id}` - Update canvas metadata
- `DELETE /canvases/{id}` - Delete canvas
- `PATCH /canvases/{id}/layout` - Update chart positions

### Charts

- `POST /canvases/{id}/charts` - Create chart
- `GET /canvases/{id}/charts/{chart_id}` - Get chart
- `PATCH /canvases/{id}/charts/{chart_id}` - Update chart
- `DELETE /canvases/{id}/charts/{chart_id}` - Delete chart

### WebSocket

- `WS /ws/{canvas_id}` - Connect for real-time updates

## Configuration

Environment variables (prefix with `CANVAS_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8003` | Server port |
| `DEBUG` | `false` | Enable debug mode |
| `DATABASE_URL` | - | PostgreSQL connection string |
| `AUTH_ENABLED` | `false` | Enable JWT auth |
| `COGNITO_USER_POOL_ID` | - | AWS Cognito user pool |
| `COGNITO_CLIENT_ID` | - | AWS Cognito client ID |

## Database Setup

Run the migration to create tables:

```sql
-- See db/models.py for schema
-- Tables: canvases, charts
```
