import asyncio
import logging
import time
from urllib.parse import quote

import httpx

from app.database.repository import AnonymizationRepository
from app.services.cleaner import TextCleaner
from app.services.crypto_service import CryptoService
from app.config import get_settings


logger = logging.getLogger(__name__)
class AnonymizationWorker:
    def __init__(self, repo: AnonymizationRepository, crypto: CryptoService):
        self.repo = repo
        self.crypto = crypto
        self.settings = get_settings()
        self.cleaner = TextCleaner()
        self.subscribers = self.settings.subscribers()
        self.http_client = httpx.AsyncClient(timeout=self.settings.callback_timeout_seconds)

    def clean_payload(self, payload: dict) -> tuple[str, dict]:
        cleaned_text = self.cleaner.clean(self.crypto.decrypt(payload["text"]))
        utterances = payload.get("utterances") or []
        for utterance in utterances:
            for field in ("text", "normalized_text"):
                value = utterance.get(field)
                if isinstance(value, str):
                    utterance[field] = self.cleaner.clean(self.crypto.decrypt(value))
            for word in utterance.get("word_alignments") or []:
                if isinstance(word.get("word"), str):
                    word["word"] = self.cleaner.clean(self.crypto.decrypt(word["word"]))
        return cleaned_text, utterances

    def _body(self, contract: str, payload: dict, cleaned_text: str, utterances: list[dict]) -> dict:
        if contract == "call_summarization":
            return {"call_id": payload["call_id"], "cleaned_text": cleaned_text}
        if contract == "ai_mentor_insight":
            return {"text": cleaned_text}
        if contract != "ai_q_score":
            raise ValueError(f"Unknown contract: {contract}")
        required = ("manager_id", "client_epk", "duration_seconds")
        missing = [field for field in required if payload.get(field) in (None, "")]
        if missing:
            raise ValueError(f"AI Q Score fields missing: {', '.join(missing)}")
        return {
            "call_id": payload["call_id"],
            "manager_id": payload["manager_id"],
            "client_epk": payload["client_epk"],
            "client_fio": payload.get("client_fio"),
            "client_fio_encrypted": payload.get("client_fio_encrypted", False),
            "duration_seconds": payload["duration_seconds"],
            "occurred_at": payload.get("occurred_at"),
            "channel": payload.get("channel"),
            "cleaned_text": cleaned_text,
            "utterances": utterances,
            "source_metadata": payload.get("source_metadata") or {},
        }

    def _target_subscribers(self, payload: dict) -> list[dict]:
        callback_url = payload.get("callback_url")
        if not callback_url:
            result = []
            for subscriber in self.subscribers:
                if subscriber["contract"] != "ai_mentor_insight":
                    result.append(subscriber)
            return result
        for subscriber in self.subscribers:
            if subscriber["contract"] != "ai_mentor_insight":
                continue
            target = dict(subscriber)
            target["url"] = callback_url.rstrip("/")
            if target.get("append_call_id"):
                target["url"] += "/" + quote(payload["call_id"], safe="")
            return [target]
        raise ValueError("AI Mentor Insight callback is disabled")

    async def process_one(self) -> bool:
        claimed = await self.repo.claim_task()
        if claimed is None:
            return False
        task_id, call_id, payload, _ = claimed
        try:
            cleaned_text, utterances = self.clean_payload(payload)
            deliveries = []
            for subscriber in self._target_subscribers(payload):
                deliveries.append({
                    "name": subscriber["name"],
                    "url": subscriber["url"],
                    "body": self._body(subscriber["contract"], payload, cleaned_text, utterances),
                })
            await self.repo.finish_cleaning(task_id, deliveries)
            logger.info("Dialog cleaned call_id=%s deliveries=%s", call_id, len(deliveries))
        except Exception as exc:
            logger.exception("Cleaning failed call_id=%s", call_id)
            await self.repo.fail_cleaning(task_id, str(exc))
        return True

    async def deliver_one(self) -> bool:
        claimed = await self.repo.claim_delivery()
        if claimed is None:
            return False
        delivery_id, call_id, name, url, body, _ = claimed
        error = None
        try:
            response = await self.http_client.post(url, json=body)
            response.raise_for_status()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("Callback failed call_id=%s subscriber=%s error=%s", call_id, name, error)
        discarded = await self.repo.finish_delivery(
            delivery_id, error, self.settings.callback_max_attempts,
            self.settings.callback_retry_seconds,
        )
        if discarded:
            logger.error("Callback exhausted retries call_id=%s subscriber=%s", call_id, name)
        return True

    async def run(self):
        next_maintenance = 0.0
        while True:
            try:
                if time.monotonic() >= next_maintenance:
                    await self.repo.recover_stale(self.settings.worker_stale_seconds)
                    await self.repo.cleanup_expired()
                    next_maintenance = time.monotonic() + 60
                cleaned = await self.process_one()
                delivered = await self.deliver_one()
                if not cleaned and not delivered:
                    await asyncio.sleep(self.settings.worker_poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker loop failed")
                await asyncio.sleep(self.settings.worker_poll_seconds)
