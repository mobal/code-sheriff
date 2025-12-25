import uuid

import uvicorn
from aws_lambda_powertools.logging import Logger
from aws_lambda_powertools.logging.logger import set_package_logger
from fastapi import FastAPI, Request, HTTPException, Header, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import UJSONResponse
import httpx
import json

from mangum import Mangum
from starlette.middleware.gzip import GZipMiddleware

from app import settings
from app.middlewares import RateLimitingMiddleware
from app.models import CamelModel, GitHubRequest

if settings.debug:
    set_package_logger()

logger = Logger()

app = FastAPI(debug=settings.debug)
app.add_middleware(RateLimitingMiddleware)
app.add_middleware(GZipMiddleware)

handler = Mangum(app)
handler = logger.inject_lambda_context(handler, log_event=True, clear_state=True)


ANTHROPIC_API_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
GITHUB_API_REPOS_BASE_URL = "https://api.github.com/repos"
GITHUB_HEADERS = {
    "Authorization": f"token {settings.github_token}",
    "Accept": "application/vnd.github.v3+json",
}


class ErrorResponse(CamelModel):
    status: int
    id: uuid.UUID
    message: str


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException) -> UJSONResponse:
    error_id = uuid.uuid4()
    logger.exception(f"Received http exception {error_id=}")
    return UJSONResponse(
        content=jsonable_encoder(ErrorResponse(status=error.status_code, id=error_id, message=error.detail)),
        status_code=error.status_code,
    )


async def get_pr_files(repo_full_name: str, pr_number: int) -> list[dict]:
    url = f"{GITHUB_API_REPOS_BASE_URL}/{repo_full_name}/pulls/{pr_number}/files"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=GITHUB_HEADERS)
        response.raise_for_status()
        return response.json()


async def review_code_with_claude(files: list[dict], pr_title: str, pr_body: str) -> list[dict]:
    url = ANTHROPIC_API_MESSAGES_URL
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    files_summary = []
    for f in files[:10]:
        files_summary.append(
            {
                "filename": f["filename"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": f.get("patch", "")[:3000],
            }
        )

    prompt = f"""Review this pull request and provide specific line-by-line feedback.

PR Title: {pr_title}
PR Description: {pr_body or "No description provided"}

Files changed:
{json.dumps(files_summary, indent=2)}

For each issue you find, provide:
1. The exact filename
2. The line number (from the patch context)
3. A specific, actionable comment

Respond ONLY with a JSON array of review comments in this exact format:
[
  {{
    "path": "path/to/file.py",
    "line": 42,
    "side": "RIGHT",
    "body": "Consider adding error handling here for edge cases."
  }}
]

Focus on:
- Bugs and potential errors
- Security vulnerabilities
- Performance issues
- Code quality and best practices
- Logic errors

If no issues found, return an empty array: []"""

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        review_text = data["content"][0]["text"]

        try:
            if "```json" in review_text:
                review_text = review_text.split("```json")[1].split("```")[0]
            elif "```" in review_text:
                review_text = review_text.split("```")[1].split("```")[0]

            comments = json.loads(review_text.strip())
            return comments if isinstance(comments, list) else []
        except json.JSONDecodeError:
            return []


async def get_pr_head_sha(repo_full_name: str, pr_number: int) -> str:
    url = f"{GITHUB_API_REPOS_BASE_URL}/{repo_full_name}/pulls/{pr_number}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=GITHUB_HEADERS)
        response.raise_for_status()
        data = response.json()
        return data["head"]["sha"]


async def post_review_comments(repo_full_name: str, pr_number: int, commit_sha: str, comments: list[dict]):
    url = f"{GITHUB_API_REPOS_BASE_URL}/{repo_full_name}/pulls/{pr_number}/reviews"

    if not comments:
        review_data = {
            "commit_id": commit_sha,
            "body": "🤖 **AI Code Review**: No issues found! The code looks good.",
            "event": "COMMENT",
        }
    else:
        review_data = {
            "commit_id": commit_sha,
            "body": f"🤖 **AI Code Review**: Found {len(comments)} suggestion(s) for improvement.",
            "event": "COMMENT",
            "comments": comments,
        }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=GITHUB_HEADERS, json=review_data)
        response.raise_for_status()
        return response.json()


@app.post("/webhooks/github")
async def review(
    gh_request: GitHubRequest,
    x_github_event: str | None = Header(None),
):
    if x_github_event != "pull_request":
        return UJSONResponse({"message": "Event ignored"})

    if gh_request.action not in ["opened", "synchronize"]:
        return UJSONResponse({"message": f"Action '{gh_request.action}' ignored"})

    try:
        files = await get_pr_files(gh_request.pull_request.repository.full_name, gh_request.pull_request.number)
        commit_sha = await get_pr_head_sha(gh_request.pull_request.repository.full_name, gh_request.pull_request.number)
        comments = await review_code_with_claude(files, gh_request.pull_request.title, gh_request.pull_request.body)

        await post_review_comments(
            gh_request.pull_request.repository.full_name,
            gh_request.pull_request.number,
            commit_sha,
            comments,
        )

        return UJSONResponse(
            {
                "message": "Review posted successfully",
                "pr_number": gh_request.pull_request.number,
                "comments_count": len(comments),
            }
        )

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run("app.api_handler:app", host="0.0.0.0", port=8080, reload=True, log_level="info")
