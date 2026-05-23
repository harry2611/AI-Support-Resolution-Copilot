from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from app.config import Settings


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class ExternalDocument:
    connector: str
    external_id: str
    title: str
    source_url: str
    content: str
    updated_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class BaseConnector:
    name: str = "unknown"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_enabled(self) -> bool:  # pragma: no cover - simple config gate
        raise NotImplementedError

    def fetch_documents(self) -> list[ExternalDocument]:
        raise NotImplementedError


class ConfluenceConnector(BaseConnector):
    name = "confluence"

    def is_enabled(self) -> bool:
        return bool(
            self.settings.confluence_enabled
            and self.settings.confluence_base_url
            and self.settings.confluence_email
            and self.settings.confluence_api_token
        )

    def fetch_documents(self) -> list[ExternalDocument]:
        if not self.is_enabled():
            return []

        base_url = self.settings.confluence_base_url.rstrip("/")
        if base_url.endswith("/wiki"):
            api_root = f"{base_url}/rest/api"
        else:
            api_root = f"{base_url}/wiki/rest/api"

        space_keys = self.settings.confluence_space_key_list()
        space_filter = ""
        if space_keys:
            quoted = ",".join(f'"{key}"' for key in space_keys)
            space_filter = f" AND space in ({quoted})"
        cql = f"type=page{space_filter} ORDER BY lastmodified DESC"

        response = requests.get(
            f"{api_root}/content/search",
            auth=(self.settings.confluence_email, self.settings.confluence_api_token),
            params={
                "cql": cql,
                "expand": "body.storage,version,space",
                "limit": self.settings.confluence_page_limit,
            },
            timeout=self.settings.connector_request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        docs: list[ExternalDocument] = []
        for item in payload.get("results", []):
            page_id = str(item.get("id", "")).strip()
            title = (item.get("title") or "").strip()
            html_content = item.get("body", {}).get("storage", {}).get("value", "")
            text_content = _strip_html(html_content)
            if not page_id or not title or not text_content:
                continue

            webui = item.get("_links", {}).get("webui", "")
            source_url = f"{base_url}{webui}" if webui else f"{base_url}/wiki/spaces"
            updated_at = _parse_iso_datetime(item.get("version", {}).get("when"))
            space_key = item.get("space", {}).get("key")

            docs.append(
                ExternalDocument(
                    connector=self.name,
                    external_id=page_id,
                    title=title[:255],
                    source_url=source_url,
                    content=text_content,
                    updated_at=updated_at,
                    tags=[tag for tag in [space_key, "confluence"] if tag],
                    metadata={"space_key": space_key},
                )
            )
        return docs


class NotionConnector(BaseConnector):
    name = "notion"

    def is_enabled(self) -> bool:
        return bool(self.settings.notion_enabled and self.settings.notion_api_token)

    def fetch_documents(self) -> list[ExternalDocument]:
        if not self.is_enabled():
            return []

        headers = {
            "Authorization": f"Bearer {self.settings.notion_api_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        docs: list[ExternalDocument] = []
        database_ids = self.settings.notion_database_id_list()
        if database_ids:
            for database_id in database_ids:
                docs.extend(self._fetch_database_pages(database_id, headers))
        else:
            docs.extend(self._fetch_search_pages(headers))

        return docs

    def _fetch_search_pages(self, headers: dict[str, str]) -> list[ExternalDocument]:
        response = requests.post(
            "https://api.notion.com/v1/search",
            headers=headers,
            json={
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": self.settings.notion_page_limit,
            },
            timeout=self.settings.connector_request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return self._map_notion_pages(payload.get("results", []), headers)

    def _fetch_database_pages(self, database_id: str, headers: dict[str, str]) -> list[ExternalDocument]:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=headers,
            json={"page_size": self.settings.notion_page_limit},
            timeout=self.settings.connector_request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        docs = self._map_notion_pages(payload.get("results", []), headers)
        for doc in docs:
            doc.tags = [*doc.tags, database_id]
            doc.metadata["database_id"] = database_id
        return docs

    def _map_notion_pages(self, pages: list[dict], headers: dict[str, str]) -> list[ExternalDocument]:
        docs: list[ExternalDocument] = []
        for page in pages:
            page_id = str(page.get("id", "")).strip()
            if not page_id:
                continue

            title = self._extract_title(page.get("properties", {}))
            if not title:
                title = f"Notion Page {page_id[:8]}"

            content = self._fetch_page_content(page_id, headers)
            if not content:
                continue

            docs.append(
                ExternalDocument(
                    connector=self.name,
                    external_id=page_id,
                    title=title[:255],
                    source_url=page.get("url", "https://www.notion.so"),
                    content=content,
                    updated_at=_parse_iso_datetime(page.get("last_edited_time")),
                    tags=["notion"],
                    metadata={},
                )
            )
        return docs

    def _fetch_page_content(self, page_id: str, headers: dict[str, str]) -> str:
        response = requests.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            params={"page_size": 100},
            timeout=self.settings.connector_request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        lines: list[str] = []
        for block in payload.get("results", []):
            block_type = block.get("type")
            block_payload = block.get(block_type, {}) if block_type else {}
            rich_text = block_payload.get("rich_text", [])
            text = "".join(fragment.get("plain_text", "") for fragment in rich_text).strip()
            if text:
                lines.append(text)
        return "\n".join(lines).strip()

    def _extract_title(self, properties: dict) -> str:
        for _, prop in properties.items():
            if prop.get("type") != "title":
                continue
            title_fragments = prop.get("title", [])
            title = "".join(fragment.get("plain_text", "") for fragment in title_fragments).strip()
            if title:
                return title
        return ""
