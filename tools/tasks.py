"""Google Tasks tool classes."""

import logging

from tools.base import Tool, registry
from tools.utils import get_service

logger = logging.getLogger(__name__)


def _parse_due(due_rfc: str) -> str:
    """Extract YYYY-MM-DD from a Tasks API RFC 3339 due string."""
    return due_rfc[:10] if due_rfc else ""


def _format_task(t: dict) -> str:
    """Format a task dict as a single display line."""
    title = t.get("title", "(no title)")
    due = _parse_due(t.get("due", ""))
    notes = t.get("notes", "")
    status = t.get("status", "needsAction")
    tid = t.get("id", "")

    parts = [f"• {title}"]
    if status == "completed":
        parts[0] = f"• [done] {title}"
    if due:
        parts.append(f"due {due}")
    if notes:
        parts.append(f"— {notes}")
    parts.append(f"[id: {tid}]")
    return " ".join(parts)


# ── Tool classes ─────────────────────────────────────────────────────────────


class ListTasks(Tool):
    name = "list_tasks"
    description = """\
List Google Tasks to-do items. Returns titles, due dates, notes, status, and IDs. \
By default shows only incomplete tasks; set include_completed=true to include done items."""
    parameters = {
        "include_completed": {
            "type": "boolean",
            "description": "If true, include completed tasks in the result. Defaults to false.",
        },
    }

    def execute(self, include_completed: bool = False) -> str:
        service = get_service("tasks", "v1")
        try:
            result = service.tasks().list(
                tasklist="@default",
                showCompleted=include_completed,
                showHidden=include_completed,
                maxResults=100,
            ).execute()
        except Exception as e:
            return f"Failed to list tasks: {e}"
        items = result.get("items", [])
        if not items:
            return "No tasks found."
        return "\n".join(_format_task(t) for t in items)


class CreateTask(Tool):
    name = "create_task"
    description = """\
Create a Google Tasks to-do item. Use this for tasks without a specific time \
(e.g. 'remind me to call X', 'buy groceries by Friday'). \
For time-blocked items with a specific start/end time, use create_event instead."""
    parameters = {
        "title": {
            "type": "string",
            "description": "The task title.",
        },
        "due_date": {
            "type": "string",
            "description": "Optional due date in YYYY-MM-DD format (e.g. '2025-03-25').",
        },
        "notes": {
            "type": "string",
            "description": "Optional notes or details for the task.",
        },
    }
    required = ["title"]

    def execute(
        self,
        title: str,
        due_date: str = "",
        notes: str = "",
    ) -> str:
        service = get_service("tasks", "v1")
        body: dict = {"title": title}
        if notes:
            body["notes"] = notes
        if due_date:
            body["due"] = f"{due_date}T00:00:00.000Z"
        try:
            created = service.tasks().insert(tasklist="@default", body=body).execute()
        except Exception as e:
            return f"Failed to create task: {e}"
        due_str = f", due {due_date}" if due_date else ""
        return f"Task '{title}' created{due_str}. ID: {created.get('id')}"


class UpdateTask(Tool):
    name = "update_task"
    description = """\
Update an existing Google Tasks item. Only provided fields are changed. \
Use list_tasks first to get the task ID. \
To mark a task as done, set status='completed'."""
    parameters = {
        "task_id": {
            "type": "string",
            "description": "The task ID from list_tasks.",
        },
        "title": {
            "type": "string",
            "description": "New task title.",
        },
        "due_date": {
            "type": "string",
            "description": "New due date in YYYY-MM-DD format. Pass an empty string to clear the due date.",
        },
        "notes": {
            "type": "string",
            "description": "New notes for the task.",
        },
        "status": {
            "type": "string",
            "description": "'completed' to mark done, 'needsAction' to reopen.",
        },
    }
    required = ["task_id"]

    def execute(
        self,
        task_id: str,
        title: str = None,
        due_date: str = None,
        notes: str = None,
        status: str = None,
    ) -> str:
        service = get_service("tasks", "v1")
        patch: dict = {}
        if title is not None:
            patch["title"] = title
        if notes is not None:
            patch["notes"] = notes
        if due_date is not None:
            patch["due"] = f"{due_date}T00:00:00.000Z" if due_date else None
        if status is not None:
            patch["status"] = status
            if status == "needsAction":
                patch["completed"] = None  # clear completion timestamp
        if not patch:
            return "No fields provided to update."
        try:
            updated = service.tasks().patch(
                tasklist="@default", task=task_id, body=patch
            ).execute()
        except Exception as e:
            return f"Failed to update task: {e}"
        return f"Task updated: '{updated.get('title', task_id)}'."


class DeleteTask(Tool):
    name = "delete_task"
    description = """\
Permanently delete a Google Tasks item. Use list_tasks first to get the task ID. \
This action cannot be undone."""
    parameters = {
        "task_id": {
            "type": "string",
            "description": "The task ID from list_tasks.",
        },
    }
    required = ["task_id"]

    def execute(self, task_id: str) -> str:
        service = get_service("tasks", "v1")
        try:
            service.tasks().delete(tasklist="@default", task=task_id).execute()
        except Exception as e:
            return f"Failed to delete task: {e}"
        return f"Task '{task_id}' deleted."


# ── Register all task tools ──────────────────────────────────────────────────

registry.register(ListTasks())
registry.register(CreateTask())
registry.register(UpdateTask())
registry.register(DeleteTask())
