"""WebSocket connection manager for real-time updates."""

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections for canvas updates.

    Tracks active connections by canvas ID and provides broadcast
    functionality for real-time chart updates.
    """

    def __init__(self) -> None:
        # canvas_id -> list of connected WebSockets
        self.active_connections: dict[str, list[WebSocket]] = {}
        # websocket -> user_id mapping for tracking authenticated users
        self.connection_users: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self, websocket: WebSocket, canvas_id: str, user_id: str | None = None
    ) -> None:
        """Accept a new WebSocket connection for a canvas."""
        await websocket.accept()
        async with self._lock:
            if canvas_id not in self.active_connections:
                self.active_connections[canvas_id] = []
            self.active_connections[canvas_id].append(websocket)
            if user_id:
                self.connection_users[websocket] = user_id

    async def disconnect(self, websocket: WebSocket, canvas_id: str) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if canvas_id in self.active_connections:
                if websocket in self.active_connections[canvas_id]:
                    self.active_connections[canvas_id].remove(websocket)
                # Clean up empty canvas entries
                if not self.active_connections[canvas_id]:
                    del self.active_connections[canvas_id]
            # Clean up user mapping
            self.connection_users.pop(websocket, None)

    async def disconnect_all(self) -> None:
        """Disconnect all WebSocket connections (for shutdown)."""
        async with self._lock:
            for canvas_id, connections in list(self.active_connections.items()):
                for websocket in connections:
                    try:
                        await websocket.close()
                    except Exception:
                        pass  # Connection may already be closed
            self.active_connections.clear()
            self.connection_users.clear()

    async def broadcast_to_canvas(self, canvas_id: str, message: dict[str, Any]) -> None:
        """Send a message to all connections viewing a specific canvas."""
        async with self._lock:
            connections = self.active_connections.get(canvas_id, [])

        # Send outside lock to avoid blocking
        disconnected: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Connection failed - mark for removal
                disconnected.append(connection)

        # Remove failed connections
        if disconnected:
            async with self._lock:
                for ws in disconnected:
                    if canvas_id in self.active_connections:
                        if ws in self.active_connections[canvas_id]:
                            self.active_connections[canvas_id].remove(ws)

    async def send_personal(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        """Send a message to a specific connection."""
        try:
            await websocket.send_json(message)
        except Exception:
            pass  # Connection may have closed

    def get_connection_count(self, canvas_id: str) -> int:
        """Get the number of active connections for a canvas."""
        return len(self.active_connections.get(canvas_id, []))

    def get_total_connections(self) -> int:
        """Get total number of active connections across all canvases."""
        return sum(len(conns) for conns in self.active_connections.values())


# Global singleton instance
manager = ConnectionManager()
