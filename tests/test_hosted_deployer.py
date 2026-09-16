from __future__ import annotations

from gitcrawl.hosted.deployer import CloudRunRevisionDeployer, revision_tag


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class Session:
    def __init__(self, tag):
        self.tag = tag
        self.patches = []
        self.patched = False

    def get(self, url, timeout):
        service = {
            "uri": "https://agent-abc.a.run.app",
            "etag": "etag-1",
            "template": {"containers": [{"image": "old", "env": []}]},
            "latestReadyRevision": "services/agent/revisions/controller-00001",
            "traffic": [
                {"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100},
                {
                    "type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION",
                    "revision": "other-00002",
                    "percent": 0,
                    "tag": "other-agent",
                },
            ],
        }
        if self.patched:
            service["trafficStatuses"] = [
                {
                    "tag": self.tag,
                    "revision": "worker-00003",
                    "uri": f"https://{self.tag}---agent-abc.a.run.app",
                }
            ]
        return Response(service)

    def patch(self, url, params, json, timeout):
        self.patches.append(json)
        self.patched = True
        return Response({"name": "operations/not-polled"})


def test_deployer_creates_zero_traffic_tag_and_preserves_controller_and_other_tags():
    agent_id = "123e4567-e89b-42d3-a456-426614174000"
    image = "region-docker.pkg.dev/project/repo/image@sha256:abc"
    tag = revision_tag(agent_id, "e" * 64, image)
    session = Session(tag)
    deployer = CloudRunRevisionDeployer(
        project="project",
        region="region",
        service="agent",
        image_digest=image,
        bucket="bucket",
        session=session,
    )

    target = deployer.deploy(
        agent_id=agent_id,
        repository_key="host/owner/repo",
        eval_hash="e" * 64,
        plan_hash="p" * 16,
    )

    assert target.revision == "worker-00003" and target.created
    traffic = session.patches[0]["traffic"]
    assert any(item.get("revision") == "controller-00001" and item["percent"] == 100 for item in traffic)
    assert any(item.get("tag") == "other-agent" for item in traffic)
    assert any(item.get("tag") == tag and item["percent"] == 0 for item in traffic)


def test_deployer_reuses_existing_tag_without_patch():
    agent_id = "123e4567-e89b-42d3-a456-426614174000"
    image = "image@sha256:abc"
    tag = revision_tag(agent_id, "e" * 64, image)
    session = Session(tag)
    session.patched = True
    target = CloudRunRevisionDeployer(
        project="p", region="r", service="s", image_digest=image, bucket="b", session=session
    ).deploy(agent_id=agent_id, repository_key="h/o/r", eval_hash="e" * 64, plan_hash="p")
    assert not target.created
    assert session.patches == []


def test_pruning_never_removes_controller_or_active_agent_tags():
    deployer = CloudRunRevisionDeployer(
        project="p",
        region="r",
        service="s",
        image_digest="image@sha256:x",
        bucket="b",
        session=object(),
        active_tags_provider=lambda: {"active-agent"},
    )
    traffic = [{"revision": "controller", "percent": 100}]
    traffic.extend(
        {"revision": f"r-{index}", "percent": 0, "tag": f"old-{index}"} for index in range(900)
    )
    traffic.append({"revision": "active", "percent": 0, "tag": "active-agent"})
    pruned = deployer._prune_traffic(traffic)
    assert len(pruned) == 850
    assert any(item.get("revision") == "controller" for item in pruned)
    assert any(item.get("tag") == "active-agent" for item in pruned)
