import asyncio
import json
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket


class CollaborationHub:
    def __init__(self):
        self._connections: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, review_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[review_id].add(websocket)

    async def disconnect(self, review_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[review_id].discard(websocket)
            if not self._connections[review_id]:
                self._connections.pop(review_id, None)

    async def broadcast(self, review_id: int, message: dict) -> None:
        encoded = json.dumps(message, default=str)
        async with self._lock:
            clients = list(self._connections.get(review_id, set()))
        if not clients:
            return
        results = await asyncio.gather(
            *(client.send_text(encoded) for client in clients),
            return_exceptions=True,
        )
        failed = [
            client
            for client, result in zip(clients, results)
            if isinstance(result, Exception)
        ]
        for client in failed:
            await self.disconnect(review_id, client)


collaboration_hub = CollaborationHub()
