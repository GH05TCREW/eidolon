from __future__ import annotations

from typing import Any

from eidolon.runtime.tools.base import Tool


class TodoTool(Tool):
    name = "todo"
    description = "Manage a task list during a session."
    sandbox_execution = False

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self._next_id = 1

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["set", "complete", "skip", "list"],
                    "description": (
                        "Action: 'set' to initialize list once, 'complete'/'skip' to update "
                        "status, 'list' to view"
                    ),
                },
                "item": {
                    "type": "string",
                    "description": "Single task item (for add/set)",
                },
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple task items (for add/set)",
                },
                "id": {
                    "type": "integer",
                    "description": "Task id to complete or remove",
                },
                "result": {
                    "type": "string",
                    "description": "Optional completion result or note",
                },
            },
            "required": ["action"],
        }

    def has_pending(self) -> bool:
        return any(item.get("status") == "pending" for item in self.items)

    def _normalize_items(self, payload: dict[str, Any]) -> list[str]:
        items = payload.get("items")
        if isinstance(items, list):
            return [str(item).strip() for item in items if str(item).strip()]
        item = payload.get("item")
        if isinstance(item, str) and item.strip():
            return [item.strip()]
        return []

    def _add_item(self, text: str) -> dict[str, Any]:
        item = {"id": self._next_id, "text": text, "status": "pending"}
        self.items.append(item)
        self._next_id += 1
        return item

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "list")).lower()

        if action == "add":
            for item in self._normalize_items(payload):
                self._add_item(item)
            return {"items": list(self.items)}

        if action == "set":
            self.items = []
            self._next_id = 1
            for item in self._normalize_items(payload):
                self._add_item(item)
            return {"items": list(self.items)}

        if action == "complete":
            item_id = payload.get("id")
            if item_id is None:
                return {"error": "id is required for complete"}
            try:
                item_id = int(item_id)
            except (TypeError, ValueError):
                return {"error": "id must be an integer"}
            target = next((item for item in self.items if item["id"] == item_id), None)
            if not target:
                return {"error": f"task id {item_id} not found"}
            target["status"] = "complete"
            result = payload.get("result")
            if isinstance(result, str) and result.strip():
                target["result"] = result.strip()
            return {"items": list(self.items), "completed": target}

        if action == "skip":
            item_id = payload.get("id")
            if item_id is None:
                return {"error": "id is required for skip"}
            try:
                item_id = int(item_id)
            except (TypeError, ValueError):
                return {"error": "id must be an integer"}
            target = next((item for item in self.items if item["id"] == item_id), None)
            if not target:
                return {"error": f"task id {item_id} not found"}
            target["status"] = "skipped"
            result = payload.get("result")
            if isinstance(result, str) and result.strip():
                target["result"] = result.strip()
            return {"items": list(self.items), "skipped": target}

        if action == "remove":
            item_id = payload.get("id")
            if item_id is None:
                return {"error": "id is required for remove"}
            try:
                item_id = int(item_id)
            except (TypeError, ValueError):
                return {"error": "id must be an integer"}
            self.items = [item for item in self.items if item["id"] != item_id]
            return {"items": list(self.items)}

        if action == "clear":
            self.items = []
            self._next_id = 1
            return {"items": []}

        if action == "list":
            return {"items": list(self.items)}

        return {"error": f"unsupported action {action}"}
