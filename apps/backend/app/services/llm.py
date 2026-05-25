from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Iterable

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import OpenAI

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class WebReference:
    title: str
    url: str
    snippet: str


class LLMService:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.embedding_client = (
            OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
            if settings.openai_api_key
            else None
        )
        self.chat_client = (
            ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0.2)
            if settings.openai_api_key
            else None
        )

    def embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        text_list = list(texts)
        if not text_list:
            return []

        if self.embedding_client:
            try:
                return self.embedding_client.embed_documents(text_list)
            except Exception:
                return [self._hash_embedding(text) for text in text_list]

        if not self.client:
            return [self._hash_embedding(text) for text in text_list]

        try:
            response = self.client.embeddings.create(
                model=settings.embedding_model,
                input=text_list,
            )
            return [item.embedding for item in response.data]
        except Exception:
            # Fallback keeps local development unblocked when API is unavailable.
            return [self._hash_embedding(text) for text in text_list]

    def generate_answer(self, question: str, context_blocks: list[str]) -> str:
        if not context_blocks:
            return (
                "I could not find a grounded answer in the indexed knowledge base. "
                "Please ingest more support docs or rephrase the question."
            )

        context = "\n\n".join(context_blocks)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an AI support assistant. Answer using only the provided context. "
                    "If context is insufficient, explicitly say what is missing. "
                    "Keep answers concise and include actionable next steps.",
                ),
                (
                    "human",
                    "Question:\n{question}\n\nContext:\n{context}",
                ),
            ]
        )

        if self.chat_client:
            try:
                response = self.chat_client.invoke(prompt.format_messages(question=question, context=context))
                if response.content:
                    return str(response.content).strip()
            except Exception:
                pass

        if not self.client:
            return self._fallback_context_answer(question, context_blocks)

        try:
            response = self.client.responses.create(
                model=settings.chat_model,
                input=[
                    {
                        "role": "system",
                        "content": "You are an AI support assistant. Answer using provided context only.",
                    },
                    {"role": "user", "content": f"Question:\n{question}\n\nContext:\n{context}"},
                ],
                temperature=0.2,
            )
            output_text = getattr(response, "output_text", None)
            if output_text:
                return output_text.strip()

            # Defensive extraction for SDK response shape changes.
            parts: list[str] = []
            for item in getattr(response, "output", []):
                for content in getattr(item, "content", []):
                    text = getattr(content, "text", None)
                    if text:
                        parts.append(text)
            return "\n".join(parts).strip() or self._fallback_context_answer(question, context_blocks)
        except Exception:
            return self._fallback_context_answer(question, context_blocks)

    def generate_answer_with_web_fallback(
        self,
        question: str,
        context_blocks: list[str],
    ) -> tuple[str, list[WebReference], bool, str | None]:
        if not self.client:
            return self.generate_answer(question, context_blocks), [], False, "OpenAI client not configured"

        context = "\n\n".join(context_blocks) if context_blocks else "No internal context available."
        last_exception: Exception | None = None
        tool_attempts: list[dict] = [
            {"type": "web_search_preview"},
            {
                "type": "web_search_preview",
                "user_location": {
                    "type": "approximate",
                    "country": "US",
                    "timezone": "America/Los_Angeles",
                },
            },
            {"type": "web_search"},
            {
                "type": "web_search",
                "user_location": {
                    "type": "approximate",
                    "country": "US",
                    "timezone": "America/Los_Angeles",
                },
            },
        ]

        for tool_config in tool_attempts:
            try:
                response = self.client.responses.create(
                    model=settings.chat_model,
                    tools=[tool_config],
                    tool_choice="auto",
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "You are an AI support assistant. Prefer internal context when available, then use web "
                                "search to fill missing pieces. Clearly state uncertainty."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Question:\n{question}\n\n"
                                f"Internal context:\n{context}\n\n"
                                "Use web search for up-to-date or missing details and produce a concise answer."
                            ),
                        },
                    ],
                    temperature=0.2,
                )
                answer = self._extract_output_text(response) or self.generate_answer(question, context_blocks)
                web_references = self._extract_web_references(response)
                if not web_references:
                    web_references = self._extract_web_sources(response)
                return answer, web_references[: settings.web_fallback_max_references], True, None
            except Exception as exc:
                last_exception = exc
                logger.warning("Web fallback attempt failed for tool '%s': %s", tool_config.get("type"), exc)

        if last_exception:
            logger.warning("All web fallback attempts failed: %s", last_exception)
            return self.generate_answer(question, context_blocks), [], False, str(last_exception)
        return self.generate_answer(question, context_blocks), [], False, "Unknown web fallback failure"

    def generate_ticket_draft(self, customer_message: str, context_blocks: list[str]) -> str:
        context = "\n\n".join(context_blocks)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a senior support engineer writing a customer-facing response. "
                    "Be empathetic, precise, and propose concrete troubleshooting steps. "
                    "Do not invent policies or features not present in context.",
                ),
                (
                    "human",
                    "Customer message:\n{customer_message}\n\nRelevant context:\n{context}",
                ),
            ]
        )

        if self.chat_client:
            try:
                response = self.chat_client.invoke(
                    prompt.format_messages(
                        customer_message=customer_message,
                        context=context if context else "No context found.",
                    )
                )
                if response.content:
                    return str(response.content).strip()
            except Exception:
                pass

        if not self.client:
            return self._fallback_ticket_draft(customer_message, context_blocks)

        try:
            response = self.client.responses.create(
                model=settings.chat_model,
                input=[
                    {"role": "system", "content": "Draft a customer support response using provided context."},
                    {
                        "role": "user",
                        "content": (
                            f"Customer message:\n{customer_message}\n\n"
                            f"Relevant context:\n{context if context else 'No context found.'}"
                        ),
                    },
                ],
                temperature=0.3,
            )
            output_text = getattr(response, "output_text", None)
            return output_text.strip() if output_text else self._fallback_ticket_draft(customer_message, context_blocks)
        except Exception:
            return self._fallback_ticket_draft(customer_message, context_blocks)

    def clean_display_text(self, text: str) -> str:
        return self._clean_display_text(text)

    def _hash_embedding(self, text: str) -> list[float]:
        dim = settings.embedding_dimensions
        vector = [0.0] * dim
        tokens = re.findall(r"\w+", text.lower())

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] % 3) * 0.25
            vector[idx] += sign * weight

        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]

    def _fallback_context_answer(self, question: str, context_blocks: list[str]) -> str:
        top_points = "\n\n".join(self._format_context_block(block) for block in context_blocks[:3])
        return (
            f"Here are the closest grounded matches I found for: \"{question}\"\n\n"
            f"{top_points}\n\n"
            "Suggested next step: narrow the question or apply a source filter if you want a more precise answer."
        )

    def _fallback_ticket_draft(self, customer_message: str, context_blocks: list[str]) -> str:
        context_hint = (
            self._clean_display_text(self._extract_context_content(context_blocks[0]))[:280]
            if context_blocks
            else "No matching runbook was retrieved."
        )
        return (
            "Hi,\n\n"
            "Thanks for reporting this issue. I understand the impact and I’m here to help.\n\n"
            f"From our internal guidance: {context_hint}\n\n"
            "Could you please share the exact timestamp, affected account ID, and the last action before failure? "
            "Once we have that, we can validate logs and provide a targeted fix.\n\n"
            "Best,\nSupport Team"
        )

    def _extract_output_text(self, response: object) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            contents = getattr(item, "content", None)
            if contents is None and isinstance(item, dict):
                contents = item.get("content", [])
            for content in contents or []:
                text = getattr(content, "text", None)
                if text is None and isinstance(content, dict):
                    text = content.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()

    def _extract_web_references(self, response: object) -> list[WebReference]:
        refs: list[WebReference] = []
        seen: set[str] = set()

        for item in getattr(response, "output", []) or []:
            contents = getattr(item, "content", None)
            if contents is None and isinstance(item, dict):
                contents = item.get("content", [])

            for content in contents or []:
                annotations = getattr(content, "annotations", None)
                if annotations is None and isinstance(content, dict):
                    annotations = content.get("annotations", [])

                for annotation in annotations or []:
                    url = getattr(annotation, "url", None)
                    if url is None and isinstance(annotation, dict):
                        url = annotation.get("url")
                    if not url or url in seen:
                        continue

                    title = getattr(annotation, "title", None)
                    snippet = getattr(annotation, "text", None)
                    if isinstance(annotation, dict):
                        title = title or annotation.get("title")
                        snippet = snippet or annotation.get("text")

                    refs.append(
                        WebReference(
                            title=(title or "Web result").strip(),
                            url=str(url),
                            snippet=(snippet or "Used during web fallback retrieval.").strip()[:220],
                        )
                    )
                    seen.add(str(url))

        return refs

    def _extract_web_sources(self, response: object) -> list[WebReference]:
        refs: list[WebReference] = []
        seen: set[str] = set()

        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None)
            if item_type is None and isinstance(item, dict):
                item_type = item.get("type")

            if item_type != "web_search_call":
                continue

            action = getattr(item, "action", None)
            if action is None and isinstance(item, dict):
                action = item.get("action", {})

            sources = getattr(action, "sources", None)
            if sources is None and isinstance(action, dict):
                sources = action.get("sources", [])

            for source in sources or []:
                url = getattr(source, "url", None)
                title = getattr(source, "title", None)
                snippet = getattr(source, "snippet", None)
                if isinstance(source, dict):
                    url = url or source.get("url")
                    title = title or source.get("title")
                    snippet = snippet or source.get("snippet")

                if not url or str(url) in seen:
                    continue

                refs.append(
                    WebReference(
                        title=(title or "Web result").strip(),
                        url=str(url),
                        snippet=(snippet or "Used during web fallback retrieval.").strip()[:220],
                    )
                )
                seen.add(str(url))

        return refs

    def _format_context_block(self, block: str) -> str:
        header, content = self._split_context_block(block)
        title, source = self._parse_context_header(header)
        summary = self._clean_display_text(content)[:260]
        if len(content) > 260:
            summary = summary.rstrip() + "..."
        return f"- {title} ({source})\n  {summary}"

    def _split_context_block(self, block: str) -> tuple[str, str]:
        if "\n" not in block:
            return block, block
        header, content = block.split("\n", 1)
        return header, content

    def _parse_context_header(self, header: str) -> tuple[str, str]:
        cleaned = header.strip().strip("[]")
        parts = [part.strip() for part in cleaned.split("|")]
        title = parts[0] if parts else "Indexed source"
        source = parts[1] if len(parts) > 1 else "Knowledge base"
        return title, source

    def _extract_context_content(self, block: str) -> str:
        _, content = self._split_context_block(block)
        return content

    def _clean_display_text(self, text: str) -> str:
        cleaned = text.replace("\u2022", "\n- ").replace("•", "\n- ").replace("\u00a0", " ")
        cleaned = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cleaned)
        cleaned = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", cleaned)
        cleaned = re.sub(r"(?<=[a-zA-Z])(?=\d)", " ", cleaned)
        cleaned = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", cleaned)
        cleaned = re.sub(r"([.,;:!?])(?=[A-Za-z])", r"\1 ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()
