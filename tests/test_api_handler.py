import pytest
from fastapi.testclient import TestClient


class TestApiHandler:
    @pytest.fixture
    def client(self):
        from app.api_handler import app

        return TestClient(app, raise_server_exceptions=True)

    @pytest.fixture
    def github_webhook_payload(self):
        return {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Add new feature",
                "body": "This PR adds feature X",
                "html_url": "https://github.com/owner/repo/pull/42",
                "repository": {"full_name": "owner/repo"},
            },
        }

    @pytest.fixture
    def github_pr_files_response(self):
        return [
            {
                "filename": "app/main.py",
                "status": "modified",
                "additions": 15,
                "deletions": 3,
                "patch": "@@ -1,5 +1,6 @@\n def hello():\n-    return 'old'\n+    return 'new'\n",
            },
            {
                "filename": "tests/test_main.py",
                "status": "added",
                "additions": 10,
                "deletions": 0,
                "patch": "@@ -0,0 +1,10 @@\n+def test_hello():\n+    assert True\n",
            },
        ]

    @pytest.fixture
    def github_pr_details_response(self):
        return {"head": {"sha": "abc123def456ghi789"}}

    @pytest.fixture
    def anthropic_review_response(self):
        return {
            "content": [
                {
                    "text": """```json
    [
      {
        "path": "app/main.py",
        "line": 5,
        "side": "RIGHT",
        "body": "Consider adding error handling for edge cases"
      },
      {
        "path": "app/main.py",
        "line": 8,
        "side": "RIGHT",
        "body": "This variable name could be more descriptive"
      }
    ]
    ```"""
                }
            ]
        }

    def test_health_check_success(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_check_returns_json(self, client):
        response = client.get("/health")

        assert response.headers["content-type"].startswith("application/json")
        assert isinstance(response.json(), dict)

    def test_webhook_ignores_non_pull_request_events(self, client, github_webhook_payload):
        response = client.post("/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "push"})

        assert response.status_code == 200
        assert response.json()["message"] == "Event ignored"

    def test_webhook_ignores_pull_request_closed_action(self, client, github_webhook_payload):
        github_webhook_payload["action"] = "closed"

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 200
        assert "ignored" in response.json()["message"].lower()

    def test_webhook_ignores_pull_request_edited_action(self, client, github_webhook_payload):
        github_webhook_payload["action"] = "edited"

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 200
        assert "ignored" in response.json()["message"].lower()

    def test_webhook_processes_opened_action(self, client, github_webhook_payload, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.github.com/repos/owner/repo/pulls/42/files",
            json=[
                {
                    "filename": "src/app.py",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 1,
                    "patch": "@@ -1,5 +1,5 @@\n def main():\n-    pass\n+    print('hello')\n",
                }
            ],
        )

        httpx_mock.add_response(
            method="GET", url="https://api.github.com/repos/owner/repo/pulls/42", json={"head": {"sha": "abc123"}}
        )

        httpx_mock.add_response(
            method="POST",
            url="https://api.anthropic.com/v1/messages",
            json={"content": [{"text": "```json\n[]\n```"}]},
        )

        httpx_mock.add_response(
            method="POST",
            url="https://api.github.com/repos/owner/repo/pulls/42/reviews",
            json={"id": 1, "body": "Review posted"},
        )

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pr_number"] == 42
        assert "Review posted successfully" in data["message"]
        assert data["comments_count"] == 0

    def test_webhook_processes_synchronize_action(self, client, github_webhook_payload, httpx_mock):
        github_webhook_payload["action"] = "synchronize"

        httpx_mock.add_response(
            method="GET",
            url="https://api.github.com/repos/owner/repo/pulls/42/files",
            json=[
                {
                    "filename": "main.py",
                    "status": "modified",
                    "additions": 2,
                    "deletions": 0,
                    "patch": "@@ -1 +1 @@\n-old\n+new\n",
                }
            ],
        )

        httpx_mock.add_response(
            method="GET", url="https://api.github.com/repos/owner/repo/pulls/42", json={"head": {"sha": "def456"}}
        )

        httpx_mock.add_response(
            method="POST",
            url="https://api.anthropic.com/v1/messages",
            json={"content": [{"text": "```json\n[]\n```"}]},
        )

        httpx_mock.add_response(
            method="POST", url="https://api.github.com/repos/owner/repo/pulls/42/reviews", json={"id": 2}
        )

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 200
        assert response.json()["pr_number"] == 42

    def test_webhook_posts_review_with_comments(self, client, github_webhook_payload, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.github.com/repos/owner/repo/pulls/42/files",
            json=[
                {
                    "filename": "app/main.py",
                    "status": "modified",
                    "additions": 10,
                    "deletions": 5,
                    "patch": "@@ -1,10 +1,10 @@\n def process():\n-    x = 1\n+    y = 2\n",
                }
            ],
        )

        httpx_mock.add_response(
            method="GET", url="https://api.github.com/repos/owner/repo/pulls/42", json={"head": {"sha": "xyz789"}}
        )

        httpx_mock.add_response(
            method="POST",
            url="https://api.anthropic.com/v1/messages",
            json={
                "content": [
                    {
                        "text": """```json
[
  {
    "path": "app/main.py",
    "line": 5,
    "side": "RIGHT",
    "body": "Consider adding type hints"
  }
]
```"""
                    }
                ]
            },
        )

        httpx_mock.add_response(
            method="POST", url="https://api.github.com/repos/owner/repo/pulls/42/reviews", json={"id": 3}
        )

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["comments_count"] == 1

    def test_webhook_handles_github_api_errors(self, client, github_webhook_payload, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.github.com/repos/owner/repo/pulls/42/files",
            status_code=404,
            json={"message": "Not found"},
        )

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 500
        data = response.json()
        assert "status" in data
        assert "id" in data
        assert "message" in data

    def test_webhook_handles_anthropic_api_errors(self, client, github_webhook_payload, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.github.com/repos/owner/repo/pulls/42/files",
            json=[
                {
                    "filename": "test.py",
                    "status": "added",
                    "additions": 5,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1,5 @@\n+code\n",
                }
            ],
        )

        httpx_mock.add_response(
            method="GET", url="https://api.github.com/repos/owner/repo/pulls/42", json={"head": {"sha": "aaa111"}}
        )

        httpx_mock.add_response(
            method="POST",
            url="https://api.anthropic.com/v1/messages",
            status_code=401,
            json={"error": "Unauthorized"},
        )

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 500

    def test_webhook_validation_error_on_invalid_request(self, client):
        response = client.post(
            "/webhooks/github", json={"invalid": "payload"}, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 422

    def test_webhook_limits_files_to_10(self, client, github_webhook_payload, httpx_mock):
        files = [
            {
                "filename": f"file{i}.py",
                "status": "added",
                "additions": 1,
                "deletions": 0,
                "patch": f"@@ -0,0 +1,1 @@\n+code{i}\n",
            }
            for i in range(15)
        ]

        httpx_mock.add_response(method="GET", url="https://api.github.com/repos/owner/repo/pulls/42/files", json=files)

        httpx_mock.add_response(
            method="GET", url="https://api.github.com/repos/owner/repo/pulls/42", json={"head": {"sha": "bbb222"}}
        )

        httpx_mock.add_response(
            method="POST",
            url="https://api.anthropic.com/v1/messages",
            json={"content": [{"text": "```json\n[]\n```"}]},
        )

        httpx_mock.add_response(
            method="POST", url="https://api.github.com/repos/owner/repo/pulls/42/reviews", json={"id": 4}
        )

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        assert response.status_code == 200

    def test_webhook_returns_error_id_for_debugging(self, client, github_webhook_payload, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.github.com/repos/owner/repo/pulls/42/files",
            status_code=500,
            json={"message": "Internal error"},
        )

        response = client.post(
            "/webhooks/github", json=github_webhook_payload, headers={"x-github-event": "pull_request"}
        )

        data = response.json()
        assert len(data["id"]) == 36
        assert data["id"].count("-") == 4
