"""Cloud Storage adapter. Authentication is supplied by ADC."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class GCSObjectStore:
    def __init__(self, bucket_name: str, client=None):
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.bucket = client.bucket(bucket_name)

    def read_text(self, path: str) -> str | None:
        blob = self.bucket.blob(path)
        try:
            return blob.download_as_text()
        except Exception as exc:
            from google.api_core.exceptions import NotFound

            if isinstance(exc, NotFound):
                return None
            raise

    def write_text(self, path: str, value: str, *, content_type: str = "text/plain") -> None:
        self.bucket.blob(path).upload_from_string(value, content_type=content_type)

    def read_json(self, path: str) -> dict[str, Any] | None:
        value = self.read_text(path)
        return json.loads(value) if value is not None else None

    def write_json(self, path: str, value: BaseModel | dict[str, Any]) -> None:
        payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        self.write_text(
            path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            content_type="application/json",
        )

    def create_json_if_absent(self, path: str, value: dict[str, Any]) -> bool:
        from google.api_core.exceptions import PreconditionFailed

        try:
            self.bucket.blob(path).upload_from_string(
                json.dumps(value, sort_keys=True),
                content_type="application/json",
                if_generation_match=0,
            )
            return True
        except PreconditionFailed:
            return False

    def delete(self, path: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(path).delete()
        except NotFound:
            pass
