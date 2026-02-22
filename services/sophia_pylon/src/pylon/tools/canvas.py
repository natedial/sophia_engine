"""Tool definitions for Sophia Canvas visualization service."""

import json
from datetime import datetime, timedelta
from typing import Any

import httpx

from pylon.clients.canvas import CanvasClient
from pylon.clients.scrivener import ScrivenerClient
from pylon.tools.base import (
    ErrorType,
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolResult,
)


def _classify_http_error(status_code: int, response_text: str) -> tuple[ErrorType, str]:
    """Classify an HTTP error by status code."""
    if status_code == 404:
        return ErrorType.NOT_FOUND, f"Resource not found: {response_text}"
    elif status_code == 400:
        return ErrorType.INVALID_INPUT, f"Invalid request: {response_text}"
    elif status_code == 401:
        return ErrorType.UNAUTHORIZED, "Authentication required"
    elif status_code == 403:
        return ErrorType.UNAUTHORIZED, "Access forbidden"
    elif status_code == 429:
        return ErrorType.RATE_LIMITED, "Rate limit exceeded"
    elif status_code == 503:
        return ErrorType.SERVICE_UNAVAILABLE, "Service temporarily unavailable"
    elif status_code >= 500:
        return ErrorType.SERVICE_UNAVAILABLE, f"Server error ({status_code}): {response_text}"
    else:
        return ErrorType.UNKNOWN, f"HTTP error {status_code}: {response_text}"


def _classify_request_error(error: httpx.RequestError) -> tuple[ErrorType, str]:
    """Classify a request-level error."""
    if isinstance(error, httpx.TimeoutException):
        return ErrorType.TIMEOUT, f"Request timed out: {error}"
    elif isinstance(error, httpx.ConnectError):
        return ErrorType.SERVICE_UNAVAILABLE, f"Could not connect to service: {error}"
    else:
        return ErrorType.SERVICE_UNAVAILABLE, f"Request failed: {error}"


def _period_to_days(period: str) -> int:
    """Convert period string to number of days."""
    periods = {
        "1M": 30,
        "3M": 90,
        "6M": 180,
        "1Y": 365,
        "2Y": 730,
        "5Y": 1825,
        "10Y": 3650,
        "YTD": (datetime.now() - datetime(datetime.now().year, 1, 1)).days,
        "MAX": 7300,  # 20 years
    }
    return periods.get(period.upper(), 365)


# ----- Vega-Lite Chart Builders -----


def build_timeseries_spec(
    data: list[dict[str, Any]],
    series_names: list[str],
    title: str | None = None,
    normalize: bool = False,
) -> dict[str, Any]:
    """Build a Vega-Lite spec for time series chart."""
    # Transform data for Vega-Lite
    vega_data = []
    for series_name, series_data in zip(series_names, data):
        base_value = series_data[0]["value"] if normalize and series_data else 1
        for obs in series_data:
            value = obs["value"]
            if normalize and base_value:
                value = (value / base_value) * 100
            vega_data.append({
                "date": obs["date"],
                "value": value,
                "series": series_name,
            })

    spec: dict[str, Any] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": vega_data},
        "mark": {"type": "line", "point": False},
        "encoding": {
            "x": {
                "field": "date",
                "type": "temporal",
                "title": "Date",
                "axis": {"format": "%b %Y"},
            },
            "y": {
                "field": "value",
                "type": "quantitative",
                "title": "Index (100)" if normalize else "Value",
            },
            "color": {
                "field": "series",
                "type": "nominal",
                "title": "Series",
            },
        },
        "width": "container",
        "height": 300,
    }

    if title:
        spec["title"] = title

    # If single series, remove color encoding
    if len(series_names) == 1:
        del spec["encoding"]["color"]

    return spec


def build_comparison_bar_spec(
    data: list[dict[str, Any]],
    title: str | None = None,
) -> dict[str, Any]:
    """Build a Vega-Lite spec for comparison bar chart."""
    spec: dict[str, Any] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": data},
        "mark": {"type": "bar"},
        "encoding": {
            "x": {
                "field": "series",
                "type": "nominal",
                "title": "Series",
                "axis": {"labelAngle": -45},
            },
            "y": {
                "field": "value",
                "type": "quantitative",
                "title": "Value",
            },
            "color": {
                "field": "series",
                "type": "nominal",
                "legend": None,
            },
        },
        "width": "container",
        "height": 300,
    }

    if title:
        spec["title"] = title

    return spec


def build_scatter_spec(
    data: list[dict[str, Any]],
    x_label: str,
    y_label: str,
    title: str | None = None,
    show_regression: bool = True,
) -> dict[str, Any]:
    """Build a Vega-Lite spec for scatter plot."""
    layers: list[dict[str, Any]] = [
        {
            "mark": {"type": "circle", "opacity": 0.7},
            "encoding": {
                "x": {
                    "field": "x",
                    "type": "quantitative",
                    "title": x_label,
                },
                "y": {
                    "field": "y",
                    "type": "quantitative",
                    "title": y_label,
                },
                "tooltip": [
                    {"field": "date", "type": "temporal", "title": "Date"},
                    {"field": "x", "type": "quantitative", "title": x_label},
                    {"field": "y", "type": "quantitative", "title": y_label},
                ],
            },
        }
    ]

    if show_regression:
        layers.append({
            "mark": {"type": "line", "color": "firebrick"},
            "transform": [{"regression": "y", "on": "x"}],
            "encoding": {
                "x": {"field": "x", "type": "quantitative"},
                "y": {"field": "y", "type": "quantitative"},
            },
        })

    spec: dict[str, Any] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": data},
        "layer": layers,
        "width": "container",
        "height": 300,
    }

    if title:
        spec["title"] = title

    return spec


def build_yield_curve_spec(
    data: list[dict[str, Any]],
    title: str | None = None,
) -> dict[str, Any]:
    """Build a Vega-Lite spec for yield curve chart."""
    spec: dict[str, Any] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": data},
        "mark": {"type": "line", "point": True},
        "encoding": {
            "x": {
                "field": "maturity",
                "type": "ordinal",
                "title": "Maturity",
                "sort": ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"],
            },
            "y": {
                "field": "yield",
                "type": "quantitative",
                "title": "Yield (%)",
            },
            "color": {
                "field": "date",
                "type": "nominal",
                "title": "Date",
            },
        },
        "width": "container",
        "height": 300,
    }

    if title:
        spec["title"] = title

    return spec


# ----- Tool Definitions -----


CANVAS_TOOLS = [
    ToolDefinition(
        name="create_timeseries_chart",
        description="Create a time series chart showing one or more economic indicators over time. Use this for visualizing trends in GDP, inflation, interest rates, etc. The chart will be added to the current visualization canvas.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID to add the chart to",
                required=True,
            ),
            ToolParameter(
                name="series",
                type=ToolParameterType.ARRAY,
                description="List of series IDs to plot (e.g., ['GDP', 'GDPC1'])",
                required=True,
            ),
            ToolParameter(
                name="period",
                type=ToolParameterType.STRING,
                description="Time period: '1M', '3M', '6M', '1Y', '2Y', '5Y', '10Y', 'YTD', 'MAX'",
                required=False,
                default="5Y",
            ),
            ToolParameter(
                name="title",
                type=ToolParameterType.STRING,
                description="Chart title",
                required=False,
            ),
            ToolParameter(
                name="normalize",
                type=ToolParameterType.BOOLEAN,
                description="Normalize series to 100 at start for comparison",
                required=False,
                default=False,
            ),
        ],
    ),
    ToolDefinition(
        name="create_comparison_chart",
        description="Create a bar chart comparing current values across multiple series. Use for comparing metrics like current GDP growth vs inflation rate.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID to add the chart to",
                required=True,
            ),
            ToolParameter(
                name="series",
                type=ToolParameterType.ARRAY,
                description="List of series IDs to compare",
                required=True,
            ),
            ToolParameter(
                name="comparison_type",
                type=ToolParameterType.STRING,
                description="Type of comparison",
                required=False,
                enum=["current", "yoy_change", "mom_change"],
                default="current",
            ),
            ToolParameter(
                name="title",
                type=ToolParameterType.STRING,
                description="Chart title",
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="create_scatter_chart",
        description="Create a scatter plot showing relationship between two economic series. Optionally includes a linear regression line.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID to add the chart to",
                required=True,
            ),
            ToolParameter(
                name="x_series",
                type=ToolParameterType.STRING,
                description="Series ID for x-axis",
                required=True,
            ),
            ToolParameter(
                name="y_series",
                type=ToolParameterType.STRING,
                description="Series ID for y-axis",
                required=True,
            ),
            ToolParameter(
                name="period",
                type=ToolParameterType.STRING,
                description="Time period for data",
                required=False,
                default="5Y",
            ),
            ToolParameter(
                name="title",
                type=ToolParameterType.STRING,
                description="Chart title",
                required=False,
            ),
            ToolParameter(
                name="show_regression",
                type=ToolParameterType.BOOLEAN,
                description="Show linear regression line",
                required=False,
                default=True,
            ),
        ],
    ),
    ToolDefinition(
        name="create_yield_curve_chart",
        description="Create a yield curve visualization showing Treasury yields across maturities. Can compare current curve to a historical date.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID to add the chart to",
                required=True,
            ),
            ToolParameter(
                name="compare_date",
                type=ToolParameterType.STRING,
                description="Optional historical date (YYYY-MM-DD) to compare against current curve",
                required=False,
            ),
            ToolParameter(
                name="title",
                type=ToolParameterType.STRING,
                description="Chart title",
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="create_custom_chart",
        description="Create a custom chart using a Vega-Lite specification. Use this for complex visualizations not covered by semantic tools.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID to add the chart to",
                required=True,
            ),
            ToolParameter(
                name="spec",
                type=ToolParameterType.OBJECT,
                description="Vega-Lite specification object",
                required=True,
            ),
            ToolParameter(
                name="title",
                type=ToolParameterType.STRING,
                description="Chart title",
                required=False,
            ),
        ],
    ),
    ToolDefinition(
        name="update_canvas_layout",
        description="Rearrange charts on the canvas. Use this to organize the dashboard layout.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID to update",
                required=True,
            ),
            ToolParameter(
                name="layout",
                type=ToolParameterType.ARRAY,
                description="Array of {chart_id, x, y, w, h} position objects",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="remove_chart",
        description="Remove a chart from the canvas.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID",
                required=True,
            ),
            ToolParameter(
                name="chart_id",
                type=ToolParameterType.STRING,
                description="ID of the chart to remove",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="get_canvas",
        description="Get the current state of a visualization canvas including all charts.",
        parameters=[
            ToolParameter(
                name="canvas_id",
                type=ToolParameterType.STRING,
                description="The canvas ID to retrieve",
                required=True,
            ),
        ],
    ),
    ToolDefinition(
        name="create_canvas",
        description="Create a new visualization canvas/dashboard for the current session.",
        parameters=[
            ToolParameter(
                name="session_id",
                type=ToolParameterType.STRING,
                description="The agent session ID",
                required=True,
            ),
            ToolParameter(
                name="name",
                type=ToolParameterType.STRING,
                description="Name for the dashboard",
                required=False,
                default="Analysis Dashboard",
            ),
        ],
    ),
]


class CanvasToolExecutor:
    """Executes visualization tools against the Canvas and Scrivener clients."""

    def __init__(self, canvas_client: CanvasClient, scrivener_client: ScrivenerClient) -> None:
        self.canvas = canvas_client
        self.scrivener = scrivener_client

    def get_tools(self) -> list[ToolDefinition]:
        """Get all tool definitions for Canvas."""
        return CANVAS_TOOLS

    async def execute(self, tool_name: str, parameters: dict[str, Any], on_update=None) -> ToolResult:
        """Execute a Canvas tool."""
        try:
            match tool_name:
                case "create_canvas":
                    data = await self.canvas.create_canvas(
                        session_id=parameters["session_id"],
                        name=parameters.get("name", "Analysis Dashboard"),
                    )
                    return ToolResult.ok(json.dumps(data, indent=2))

                case "get_canvas":
                    data = await self.canvas.get_canvas(parameters["canvas_id"])
                    return ToolResult.ok(json.dumps(data, indent=2))

                case "create_timeseries_chart":
                    return await self._create_timeseries_chart(parameters)

                case "create_comparison_chart":
                    return await self._create_comparison_chart(parameters)

                case "create_scatter_chart":
                    return await self._create_scatter_chart(parameters)

                case "create_yield_curve_chart":
                    return await self._create_yield_curve_chart(parameters)

                case "create_custom_chart":
                    return await self._create_custom_chart(parameters)

                case "update_canvas_layout":
                    data = await self.canvas.update_layout(
                        parameters["canvas_id"],
                        parameters["layout"],
                    )
                    return ToolResult.ok(json.dumps(data, indent=2))

                case "remove_chart":
                    data = await self.canvas.delete_chart(
                        parameters["canvas_id"],
                        parameters["chart_id"],
                    )
                    return ToolResult.ok(json.dumps(data, indent=2))

                case _:
                    return ToolResult.fail(
                        f"Unknown tool: {tool_name}",
                        ErrorType.INVALID_INPUT,
                    )

        except httpx.HTTPStatusError as e:
            error_type, message = _classify_http_error(
                e.response.status_code, e.response.text
            )
            return ToolResult.fail(message, error_type)

        except httpx.RequestError as e:
            error_type, message = _classify_request_error(e)
            return ToolResult.fail(message, error_type)

        except KeyError as e:
            return ToolResult.fail(
                f"Missing required parameter: {e}",
                ErrorType.INVALID_INPUT,
            )

        except Exception as e:
            return ToolResult.fail(str(e), ErrorType.UNKNOWN)

    async def _create_timeseries_chart(self, params: dict[str, Any]) -> ToolResult:
        """Create a time series chart by fetching data and building spec."""
        series_ids = params["series"]
        period = params.get("period", "5Y")
        title = params.get("title")
        normalize = params.get("normalize", False)
        canvas_id = params["canvas_id"]

        # Fetch data for each series
        days = _period_to_days(period)
        all_data = []
        for series_id in series_ids:
            obs = await self.scrivener.get_observations(series_id, days)
            all_data.append(obs.get("observations", []))

        if not any(all_data):
            return ToolResult.fail("No data found for specified series", ErrorType.NOT_FOUND)

        # Build Vega-Lite spec
        spec = build_timeseries_spec(all_data, series_ids, title, normalize)

        # Create chart in canvas
        chart_title = title or f"{', '.join(series_ids)} - {period}"
        data_query = {"series": series_ids, "period": period, "normalize": normalize}

        result = await self.canvas.create_chart(
            canvas_id=canvas_id,
            chart_type="timeseries",
            spec=spec,
            title=chart_title,
            data_query=data_query,
        )

        return ToolResult.ok(json.dumps({
            "message": f"Created timeseries chart for {', '.join(series_ids)}",
            "chart_id": result["id"],
            "canvas_id": canvas_id,
        }, indent=2))

    async def _create_comparison_chart(self, params: dict[str, Any]) -> ToolResult:
        """Create a comparison bar chart."""
        series_ids = params["series"]
        comparison_type = params.get("comparison_type", "current")
        title = params.get("title")
        canvas_id = params["canvas_id"]

        # Fetch current or change values for each series
        chart_data = []
        for series_id in series_ids:
            if comparison_type == "current":
                result = await self.scrivener.get_latest_value(series_id)
                value = result.get("value", 0)
            else:
                periods = 12 if comparison_type == "yoy_change" else 1
                result = await self.scrivener.get_series_change(series_id, periods)
                value = result.get("percent_change", 0)

            chart_data.append({"series": series_id, "value": value})

        if not chart_data:
            return ToolResult.fail("No data found for specified series", ErrorType.NOT_FOUND)

        # Build spec
        spec = build_comparison_bar_spec(chart_data, title)

        # Create chart
        chart_title = title or f"Comparison: {', '.join(series_ids)}"
        data_query = {"series": series_ids, "comparison_type": comparison_type}

        result = await self.canvas.create_chart(
            canvas_id=canvas_id,
            chart_type="comparison",
            spec=spec,
            title=chart_title,
            data_query=data_query,
        )

        return ToolResult.ok(json.dumps({
            "message": f"Created comparison chart for {', '.join(series_ids)}",
            "chart_id": result["id"],
            "canvas_id": canvas_id,
        }, indent=2))

    async def _create_scatter_chart(self, params: dict[str, Any]) -> ToolResult:
        """Create a scatter plot comparing two series."""
        x_series = params["x_series"]
        y_series = params["y_series"]
        period = params.get("period", "5Y")
        title = params.get("title")
        show_regression = params.get("show_regression", True)
        canvas_id = params["canvas_id"]

        days = _period_to_days(period)

        # Fetch data for both series
        x_data = await self.scrivener.get_observations(x_series, days)
        y_data = await self.scrivener.get_observations(y_series, days)

        x_obs = {o["date"]: o["value"] for o in x_data.get("observations", [])}
        y_obs = {o["date"]: o["value"] for o in y_data.get("observations", [])}

        # Match dates
        common_dates = set(x_obs.keys()) & set(y_obs.keys())
        scatter_data = [
            {"date": d, "x": x_obs[d], "y": y_obs[d]}
            for d in sorted(common_dates)
            if x_obs[d] is not None and y_obs[d] is not None
        ]

        if not scatter_data:
            return ToolResult.fail("No overlapping data for specified series", ErrorType.NOT_FOUND)

        # Build spec
        spec = build_scatter_spec(scatter_data, x_series, y_series, title, show_regression)

        # Create chart
        chart_title = title or f"{x_series} vs {y_series}"
        data_query = {"x_series": x_series, "y_series": y_series, "period": period}

        result = await self.canvas.create_chart(
            canvas_id=canvas_id,
            chart_type="scatter",
            spec=spec,
            title=chart_title,
            data_query=data_query,
        )

        return ToolResult.ok(json.dumps({
            "message": f"Created scatter chart: {x_series} vs {y_series}",
            "chart_id": result["id"],
            "canvas_id": canvas_id,
        }, indent=2))

    async def _create_yield_curve_chart(self, params: dict[str, Any]) -> ToolResult:
        """Create a yield curve chart showing Treasury yields across maturities."""
        canvas_id = params["canvas_id"]
        compare_date = params.get("compare_date")
        title = params.get("title")

        # Treasury yield series by maturity
        yield_series = [
            ("DGS1MO", "1M"),
            ("DGS3MO", "3M"),
            ("DGS6MO", "6M"),
            ("DGS1", "1Y"),
            ("DGS2", "2Y"),
            ("DGS5", "5Y"),
            ("DGS7", "7Y"),
            ("DGS10", "10Y"),
            ("DGS20", "20Y"),
            ("DGS30", "30Y"),
        ]

        # Fetch latest value for each maturity
        curve_data = []
        today_label = "Current"

        for series_id, maturity in yield_series:
            try:
                result = await self.scrivener.get_latest_value(series_id)
                if result.get("value") is not None:
                    curve_data.append({
                        "maturity": maturity,
                        "yield": float(result["value"]),
                        "date": today_label,
                    })
            except Exception:
                continue  # Skip missing maturities

        if not curve_data:
            return ToolResult.fail("No yield data available", ErrorType.NOT_FOUND)

        # If compare_date specified, fetch historical curve
        if compare_date:
            for series_id, maturity in yield_series:
                try:
                    # Fetch observations to find the date
                    obs = await self.scrivener.get_observations(series_id, 365)
                    observations = obs.get("observations", [])

                    # Find closest date
                    for o in observations:
                        if o["date"] == compare_date and o["value"] is not None:
                            curve_data.append({
                                "maturity": maturity,
                                "yield": float(o["value"]),
                                "date": compare_date,
                            })
                            break
                except Exception:
                    continue

        # Build spec
        spec = build_yield_curve_spec(curve_data, title)

        # Create chart
        chart_title = title or "Treasury Yield Curve"
        if compare_date:
            chart_title = f"{chart_title} (vs {compare_date})"

        data_query = {"type": "yield_curve", "compare_date": compare_date}

        result = await self.canvas.create_chart(
            canvas_id=canvas_id,
            chart_type="yield_curve",
            spec=spec,
            title=chart_title,
            data_query=data_query,
        )

        return ToolResult.ok(json.dumps({
            "message": "Created yield curve chart",
            "chart_id": result["id"],
            "canvas_id": canvas_id,
            "maturities": len([d for d in curve_data if d["date"] == today_label]),
        }, indent=2))

    async def _create_custom_chart(self, params: dict[str, Any]) -> ToolResult:
        """Create a chart with a custom Vega-Lite spec."""
        canvas_id = params["canvas_id"]
        spec = params["spec"]
        title = params.get("title")

        result = await self.canvas.create_chart(
            canvas_id=canvas_id,
            chart_type="custom",
            spec=spec,
            title=title,
        )

        return ToolResult.ok(json.dumps({
            "message": "Created custom chart",
            "chart_id": result["id"],
            "canvas_id": canvas_id,
        }, indent=2))
