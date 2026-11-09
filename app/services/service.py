from app.database.repository import AnonymizationRepository
from app.schemas.anonym import AnonymizationRequest
from app.services.crypto_service import CryptoService
from app.config import get_settings
from urllib.parse import urlparse


class DataCleanerService:
    def __init__(self, repo: AnonymizationRepository, crypto: CryptoService):
        self.repo = repo
        self.crypto = crypto
        self.settings = get_settings()

    async def save_dialog(self, request: AnonymizationRequest) -> bool:
        if request.callback_url:
            parsed_url = urlparse(request.callback_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise ValueError("callback_url must be a full HTTP or HTTPS URL")
            if not self.settings.ai_mentor_insight_callback_enabled:
                raise ValueError("AI Mentor Insight callback is disabled")
        else:
            for subscriber in self.settings.subscribers():
                if subscriber["contract"] == "ai_q_score":
                    if not request.manager_id or not request.client_epk or request.duration_seconds is None:
                        raise ValueError("AI Q Score requires manager_id, client_epk and duration_seconds")
        payload = request.model_dump(mode="json")
        raw_text = self.crypto.decrypt(request.text) if request.is_encrypted else request.text
        payload["text"] = self.crypto.encrypt(raw_text)
        payload["is_encrypted"] = True

        if request.client_fio:
            if self.settings.encrypt_client_fio:
                payload["client_fio"] = self.crypto.encrypt(request.client_fio)
            payload["client_fio_encrypted"] = self.settings.encrypt_client_fio
        else:
            payload["client_fio_encrypted"] = False

        for utterance in payload["utterances"]:
            for field in ("text", "normalized_text"):
                if isinstance(utterance.get(field), str):
                    utterance[field] = self.crypto.encrypt(utterance[field])
            for word in utterance.get("word_alignments") or []:
                if isinstance(word.get("word"), str):
                    word["word"] = self.crypto.encrypt(word["word"])

        return await self.repo.save_task(request.call_id, payload, self.settings.data_ttl_days)
