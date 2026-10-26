import asyncio
import json
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket


class CollaborationHub:
    def __init__(self):
        self._connections: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._user_connections: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._connection_reviews: Dict[WebSocket, int] = {}
        self._connection_users: Dict[WebSocket, int] = {}
        self._lock = asyncio.Lock()

    async def connect(self, review_id: int, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[review_id].add(websocket)
            self._user_connections[user_id].add(websocket)
            self._connection_reviews[websocket] = review_id
            self._connection_users[websocket] = user_id

    async def disconnect(self, review_id: int, websocket: WebSocket, user_id: int) -> None:
        async with self._lock:
            self._connections[review_id].discard(websocket)
            if not self._connections[review_id]:
                self._connections.pop(review_id, None)
            self._user_connections[user_id].discard(websocket)
            if not self._user_connections[user_id]:
                self._user_connections.pop(user_id, None)
            self._connection_reviews.pop(websocket, None)
            self._connection_users.pop(websocket, None)

    async def disconnect_user(self, user_id: int) -> None:
        async with self._lock:
            clients = list(self._user_connections.pop(user_id, set()))
            for client in clients:
                review_id = self._connection_reviews.pop(client, None)
                self._connection_users.pop(client, None)
                if review_id is not None:
                    self._connections[review_id].discard(client)
                    if not self._connections[review_id]:
                        self._connections.pop(review_id, None)
        if clients:
            await asyncio.gather(
                *(client.close(code=4401, reason="Workspace access changed.") for client in clients),
                return_exceptions=True,
            )

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
            async with self._lock:
                user_id = self._connection_users.get(client)
            if user_id is not None:
                await self.disconnect(review_id, client, user_id)


collaboration_hub = CollaborationHub()
