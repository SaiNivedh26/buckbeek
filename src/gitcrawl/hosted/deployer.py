"""Create and resolve immutable tagged Cloud Run revisions through the v2 API."""

from __future__ import annotations

import hashlib
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from gitcrawl.hosted.contracts import DeploymentTarget


def revision_tag(agent_id: str, eval_hash: str, image_digest: str) -> str:
    image_hash = hashlib.sha256(image_digest.encode()).hexdigest()
    # Cloud Run limits service-name + tag to 46 characters. With the default
    # 14-character service name this 29-character tag leaves safe headroom;
    # the full identity is collision-checked in the durable tag binding.
    return f"a-{agent_id.replace('-', '')[:8]}-{eval_hash[:8]}-{image_hash[:8]}"


class CloudRunRevisionDeployer:
    def __init__(
        self,
        *,
        project: str,
        region: str,
        service: str,
        image_digest: str,
        bucket: str,
        timeout_seconds: int = 600,
        session=None,
        active_tags_provider=None,
    ):
        self.project = project
        self.region = region
        self.service = service
        self.image_digest = image_digest
        self.bucket = bucket
        self.timeout_seconds = timeout_seconds
        self.active_tags_provider = active_tags_provider or self._active_tags
        if session is None:
            import google.auth
            from google.auth import impersonated_credentials
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            deployer_identity = __import__("os").getenv("CLOUD_RUN_DEPLOYER_SERVICE_ACCOUNT")
            if deployer_identity:
                credentials = impersonated_credentials.Credentials(
                    source_credentials=credentials,
                    target_principal=deployer_identity,
                    target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    lifetime=900,
                )
            session = AuthorizedSession(credentials)
        self.session = session

    def _active_tags(self) -> set[str]:
        import json

        from google.cloud import storage

        active: set[str] = set()
        bucket = storage.Client().bucket(self.bucket)
        for blob in bucket.list_blobs(prefix="agents/"):
            if blob.name.endswith("/active.json"):
                value = json.loads(blob.download_as_text())
                if value.get("revision_tag"):
                    active.add(value["revision_tag"])
        return active

    def _prune_traffic(self, traffic: list[dict]) -> list[dict]:
        if len(traffic) < 900:
            return traffic
        active = self.active_tags_provider()
        removable = [
            item
            for item in traffic
            if item.get("tag") and item.get("tag") not in active and int(item.get("percent", 0)) == 0
        ]
        remove_count = min(len(removable), len(traffic) - 850)
        remove_ids = {id(item) for item in removable[:remove_count]}
        return [item for item in traffic if id(item) not in remove_ids]

    @property
    def service_url(self) -> str:
        return (
            "https://run.googleapis.com/v2/projects/"
            f"{self.project}/locations/{self.region}/services/{self.service}"
        )

    @staticmethod
    def _env(name: str, value: str) -> dict[str, Any]:
        return {"name": name, "value": value}

    @staticmethod
    def _tag_url(service_uri: str, tag: str) -> str:
        parts = urlsplit(service_uri)
        return urlunsplit((parts.scheme, f"{tag}---{parts.netloc}", "", "", ""))

    @staticmethod
    def _traffic_status(service: dict, tag: str) -> dict | None:
        for target in service.get("trafficStatuses", []):
            if target.get("tag") == tag:
                return target
        for target in service.get("traffic", []):
            if target.get("tag") == tag and target.get("revision"):
                return target
        return None

    @staticmethod
    def _resolved_revision(service: dict, target: dict) -> str:
        revision = target.get("revision", "")
        if not revision and target.get("type") == "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST":
            revision = service.get("latestReadyRevision", "")
        return revision.rsplit("/", 1)[-1]

    @staticmethod
    def _pin_existing_traffic(service: dict) -> list[dict]:
        statuses = {item.get("tag", ""): item for item in service.get("trafficStatuses", [])}
        latest_ready = service.get("latestReadyRevision", "").rsplit("/", 1)[-1]
        traffic: list[dict] = []
        for item in service.get("traffic", []):
            target = dict(item)
            if target.get("type") == "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST":
                resolved = statuses.get(target.get("tag", ""), {}).get("revision") or latest_ready
                if not resolved:
                    raise RuntimeError("cannot pin existing latest traffic without a ready revision")
                target["type"] = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
                target["revision"] = resolved.rsplit("/", 1)[-1]
            traffic.append(target)
        return traffic

    def _get_service(self) -> dict:
        response = self.session.get(self.service_url, timeout=30)
        response.raise_for_status()
        return response.json()

    def _pin_tag(self, tag: str, revision: str, deadline: float) -> DeploymentTarget:
        """Replace a temporary LATEST tag with an immutable revision target."""
        while time.monotonic() < deadline:
            service = self._get_service()
            traffic = [item for item in self._pin_existing_traffic(service) if item.get("tag") != tag]
            traffic = self._prune_traffic(traffic)
            traffic.append(
                {
                    "type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION",
                    "revision": revision,
                    "percent": 0,
                    "tag": tag,
                }
            )
            body: dict[str, Any] = {"traffic": traffic}
            if service.get("etag"):
                body["etag"] = service["etag"]
            response = self.session.patch(
                self.service_url,
                params={"updateMask": "traffic"},
                json=body,
                timeout=30,
            )
            if getattr(response, "status_code", 200) in {409, 412}:
                time.sleep(0.5)
                continue
            if not getattr(response, "ok", True):
                raise RuntimeError(
                    f"Cloud Run tag pin returned HTTP {response.status_code}: {response.text}"
                )
            return DeploymentTarget(
                revision=revision,
                tag=tag,
                url=self._tag_url(service["uri"], tag),
                created=True,
            )
        raise TimeoutError("Cloud Run traffic tag could not be pinned before the timeout")

    def deploy(
        self,
        *,
        agent_id: str,
        repository_key: str,
        eval_hash: str,
        plan_hash: str,
    ) -> DeploymentTarget:
        tag = revision_tag(agent_id, eval_hash, self.image_digest)
        deadline = time.monotonic() + self.timeout_seconds

        while time.monotonic() < deadline:
            service = self._get_service()
            existing_target = self._traffic_status(service, tag)
            if existing_target:
                revision = self._resolved_revision(service, existing_target)
                if revision:
                    if existing_target.get("type") == "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST":
                        return self._pin_tag(tag, revision, deadline).model_copy(update={"created": False})
                    return DeploymentTarget(
                        revision=revision,
                        tag=tag,
                        url=existing_target.get("uri")
                        or existing_target.get("url")
                        or self._tag_url(service["uri"], tag),
                        created=False,
                    )

            containers = service["template"]["containers"]
            containers[0]["image"] = self.image_digest
            existing_env = {entry["name"]: entry for entry in containers[0].get("env", [])}
            for name, value in {
                "SUBMISSIONS_BUCKET": self.bucket,
                "GITCRAWL_AGENT_ID": agent_id,
                "GITCRAWL_REPOSITORY_KEY": repository_key,
                "GITCRAWL_EVAL_HASH": eval_hash,
                "GITCRAWL_PLAN_HASH": plan_hash,
                "GITCRAWL_IMAGE_DIGEST": self.image_digest,
                "GITCRAWL_REVISION_TAG": tag,
            }.items():
                existing_env[name] = self._env(name, value)
            containers[0]["env"] = list(existing_env.values())

            traffic = [item for item in self._pin_existing_traffic(service) if item.get("tag") != tag]
            traffic = self._prune_traffic(traffic)
            traffic.append(
                {"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 0, "tag": tag}
            )
            body = {"template": service["template"], "traffic": traffic}
            if service.get("etag"):
                body["etag"] = service["etag"]
            response = self.session.patch(
                self.service_url,
                params={"updateMask": "template,traffic"},
                json=body,
                timeout=30,
            )
            if getattr(response, "status_code", 200) in {409, 412}:
                time.sleep(0.5)
                continue
            if not getattr(response, "ok", True):
                raise RuntimeError(
                    f"Cloud Run update returned HTTP {response.status_code}: {response.text}"
                )

            while time.monotonic() < deadline:
                deployed = self._get_service()
                target = self._traffic_status(deployed, tag)
                if target and (revision := self._resolved_revision(deployed, target)):
                    return self._pin_tag(tag, revision, deadline)
                terminal = deployed.get("terminalCondition", {})
                if terminal.get("state") == "CONDITION_FAILED":
                    raise RuntimeError(f"Cloud Run deployment failed: {terminal}")
                time.sleep(2)

        raise TimeoutError("tagged Cloud Run revision did not become ready before the timeout")
