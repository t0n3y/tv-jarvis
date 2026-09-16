"""ToDos aus einer Notion-Datenbank (Alternative zur iCloud-Notiz).

Erwartet eine Notion-Datenbank mit mindestens einer Title-Spalte und optional
einer Checkbox-Spalte "Erledigt" (offene Eintraege werden angezeigt). Notion-
Integration unter https://www.notion.so/my-integrations anlegen, Token in .env
eintragen und die Datenbank mit der Integration teilen.
"""

from __future__ import annotations

from notion_client import Client

from app.config import Config


def get_todos(cfg: Config) -> list[str]:
    token = cfg.secrets.notion_token
    database_id = cfg.todos.notion_database_id
    if not token or not database_id:
        return []

    client = Client(auth=token)
    results = client.databases.query(database_id=database_id).get("results", [])

    todos: list[str] = []
    for page in results:
        props = page.get("properties", {})

        done = False
        title = ""
        for prop in props.values():
            if prop.get("type") == "checkbox":
                done = prop.get("checkbox", False)
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))

        if title and not done:
            todos.append(title)

    return todos
