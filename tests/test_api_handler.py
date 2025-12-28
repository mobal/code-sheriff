import asyncio
import pytest
from fastapi.testclient import TestClient
import httpx


@pytest.fixture
def client():
    from app.api_handler import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def github_payload():
    return {
        "payload": {
            "action": "opened",
            "number": 42,
            "pull_request": {
                "id": 1001,
                "number": 42,
                "state": "open",
                "title": "Add new feature",
                "body": "Test body",
                "html_url": "https://github.com/owner/repo/pull/42",
                "diff_url": "x",
                "patch_url": "x",
                "issue_url": "x",
                "user": {"login": "owner", "id": 1, "html_url": "x"},
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
                "draft": False,
                "head": {
                    "label": "owner:branch",
                    "ref": "branch",
                    "sha": "abc",
                },
                "base": {
                    "label": "owner:main",
                    "ref": "main",
                    "sha": "def",
                },
                "merged": False,
                "comments": 0,
                "review_comments": 0,
                "commits": 1,
                "additions": 1,
                "deletions": 0,
                "changed_files": 1,
            },
            "repository": {
                "id": 1,
                "full_name": "owner/repo",
                "html_url": "x",
                "default_branch": "main",
                "visibility": "public",
            },
            "sender": {"login": "owner", "id": 1, "html_url": "x"},
        }
    }


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({}, 422),
        ({"x-github-event": "push"}, 200),
        ({"x-github-event": "issues"}, 200),
        ({"x-github-event": ""}, 200),
    ],
)
def test_webhook_basic(client, github_payload, headers, expected):
    r = client.post("/webhooks/github", json=github_payload, headers=headers)
    assert r.status_code == expected


@pytest.mark.parametrize(
    "payload",
    [{}, {"payload": {}}, {"payload": None}, []],
)
def test_webhook_invalid_payloads(client, payload):
    r = client.post(
        "/webhooks/github",
        json=payload,
        headers={"x-github-event": "pull_request"},
    )
    assert r.status_code >= 400


def test_pull_request_success(monkeypatch, client, github_payload):
    import app.api_handler as api

    async def fake_get_pr_files(*_):
        return [{"filename": "a.py"}]

    async def fake_get_pr_head_sha(*_):
        return "deadbeef"

    async def fake_review_code_with_claude(*_):
        return []

    async def fake_post_review_comments(*_):
        return {"id": 1}

    monkeypatch.setattr(api, "get_pr_files", fake_get_pr_files)
    monkeypatch.setattr(api, "get_pr_head_sha", fake_get_pr_head_sha)
    monkeypatch.setattr(api, "review_code_with_claude", fake_review_code_with_claude)
    monkeypatch.setattr(api, "post_review_comments", fake_post_review_comments)

    r = client.post(
        "/webhooks/github",
        json=github_payload,
        headers={"x-github-event": "pull_request"},
    )

    assert r.status_code == 200
    assert r.json()["comments_count"] == 0


@pytest.mark.parametrize(
    "exception",
    [httpx.HTTPError("boom"), httpx.TransportError("boom")],
)
def test_webhook_httpx_errors(monkeypatch, client, github_payload, exception):
    async def bad(*_):
        raise exception

    import app.api_handler as api

    monkeypatch.setattr(api, "get_pr_files", bad)

    r = client.post(
        "/webhooks/github",
        json=github_payload,
        headers={"x-github-event": "pull_request"},
    )

    assert r.status_code == 500
    assert "id" in r.json()


@pytest.mark.parametrize(
    "text, expected_len",
    [
        ('[{"path":"a.py","line":1,"side":"RIGHT","body":"x"}]', 1),
        ('```json\n[{"path":"a.py","line":1,"side":"RIGHT","body":"x"}]\n```', 1),
        ("not json", 0),
        ('{"not":"list"}', 0),
    ],
)
def test_review_code_with_claude(httpx_mock, text, expected_len):
    from app.api_handler import review_code_with_claude

    httpx_mock.add_response(
        method="POST",
        json={"content": [{"text": text}]},
        status_code=200,
    )

    result = asyncio.run(
        review_code_with_claude(
            [{"filename": "a.py", "status": "modified", "additions": 1, "deletions": 0}],
            "title",
            "body",
        )
    )

    assert isinstance(result, list)
    assert len(result) == expected_len
