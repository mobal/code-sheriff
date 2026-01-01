import uuid
from textwrap import dedent
from typing import Sequence, Any

import ujson
import uvicorn
from aws_lambda_powertools.logging import Logger
from aws_lambda_powertools.logging.logger import set_package_logger
from fastapi import FastAPI, Request, HTTPException, status, Header
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import UJSONResponse
import httpx
from httpx import HTTPError, TransportError

from mangum import Mangum
from starlette.middleware.gzip import GZipMiddleware

from app import settings
from app.middlewares import RateLimitingMiddleware, RequestLoggingMiddleware
from app.models import CamelModel, GitHubRequest

logger = Logger()

if settings.debug:
    set_package_logger()
    logger.setLevel("DEBUG")

app = FastAPI(debug=settings.debug)
app.add_middleware(GZipMiddleware)  # ty: ignore
app.add_middleware(RateLimitingMiddleware)  # ty: ignore
app.add_middleware(RequestLoggingMiddleware)  # ty: ignore

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


class ValidationErrorResponse(ErrorResponse):
    errors: Sequence[Any]


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, error: HTTPException) -> UJSONResponse:
    error_id = uuid.uuid4()
    logger.exception(f"Received http exception {error_id=}")
    return UJSONResponse(
        content=jsonable_encoder(ErrorResponse(status=error.status_code, id=error_id, message=error.detail)),
        status_code=error.status_code,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, error: RequestValidationError) -> UJSONResponse:
    error_id = uuid.uuid4()
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    logger.exception(f"Received request validation error {error_id=}")
    return UJSONResponse(
        content=jsonable_encoder(
            ValidationErrorResponse(
                status=status_code,
                id=error_id,
                message=str(error),
                errors=error.errors(),
            )
        ),
        status_code=status_code,
    )


@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception) -> UJSONResponse:
    error_id = uuid.uuid4()
    logger.exception(f"Received unexpected exception {error_id=}")
    return UJSONResponse(
        content=jsonable_encoder(
            ErrorResponse(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                id=error_id,
                message="Internal server error",
            )
        ),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


async def get_pr_files(repo_full_name: str, pr_number: int) -> list[dict]:
    url = f"{GITHUB_API_REPOS_BASE_URL}/{repo_full_name}/pulls/{pr_number}/files"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=GITHUB_HEADERS)
        response.raise_for_status()
        return response.json()


async def review_code_with_claude(
    files: list[dict],
    pr_title: str,
    pr_body: str,
) -> list[dict]:
    files_summary = summarize_files(files)
    prompt = build_review_prompt(pr_title, pr_body, files_summary)

    response_text = await call_claude_api(prompt)

    try:
        comments = parse_review_comments(response_text)
        valid_comments = validate_comments(comments)

        logger.info(
            "Found %s comments",
            len(valid_comments),
            extra={"comments": valid_comments},
        )
        return valid_comments

    except ujson.JSONDecodeError:
        logger.exception(
            "Failed to parse JSON response",
            extra={"response": response_text},
        )
        return []


def summarize_files(files: list[dict], limit: int = 10) -> list[dict]:
    summaries: list[dict] = []

    for f in files[:limit]:
        summaries.append(
            {
                "filename": f["filename"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": f.get("patch", "")[:3000],
            }
        )

    return summaries


def build_review_prompt(
    pr_title: str,
    pr_body: str,
    files_summary: list[dict],
) -> str:
    return dedent(
        f"""
        You are an expert code reviewer conducting a thorough pull request review.
        Analyze the code changes and provide specific, actionable feedback.

        PR Title: {pr_title}
        PR Description: {pr_body or "No description provided"}

        Files changed:
        {ujson.dumps(files_summary, indent=2)}

        REVIEW GUIDELINES:

        1. CRITICAL ISSUES:
        - Security vulnerabilities
        - Data loss risks
        - Memory or resource leaks
        - Breaking changes
        - Null handling issues
        - Concurrency problems

        2. HIGH-PRIORITY ISSUES:
        - Logic errors
        - Error handling
        - Performance issues
        - Input validation
        - Edge cases

        3. CODE QUALITY:
        - Duplication
        - Complexity
        - Naming
        - Magic numbers
        - SOLID violations

        4. BEST PRACTICES:
        - Missing tests
        - Logging issues
        - Hardcoded configuration
        - Poor organization

        Respond ONLY with a JSON array. If no issues found, return [].
        """
    ).strip()


async def call_claude_api(prompt: str) -> str:
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 8000,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            ANTHROPIC_API_MESSAGES_URL,
            headers=build_headers(),
            json=payload,
        )
        response.raise_for_status()

    data = response.json()
    return data["content"][0]["text"]


def build_headers() -> dict:
    return {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def parse_review_comments(response_text: str) -> list[dict]:
    json_block = extract_json_block(response_text)
    return ujson.loads(json_block)


def extract_json_block(text: str) -> str:
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()

    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()

    return text.strip()


def validate_comments(comments: list[dict]) -> list[dict]:
    required_keys = {"path", "line", "body"}

    return [comment for comment in comments if isinstance(comment, dict) and required_keys.issubset(comment)]


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
    request: Request,
    x_github_event: str = Header(alias="x-github-event"),
):
    if x_github_event == "pull_request":
        gh_request = GitHubRequest(**await request.json())
        try:
            files = await get_pr_files(gh_request.payload.repository.full_name, gh_request.payload.number)
            commit_sha = await get_pr_head_sha(gh_request.payload.repository.full_name, gh_request.payload.number)
            comments = await review_code_with_claude(
                files, gh_request.payload.pull_request.title, gh_request.payload.pull_request.body
            )

            await post_review_comments(
                gh_request.payload.repository.full_name,
                gh_request.payload.pull_request.number,
                commit_sha,
                comments,
            )

            return UJSONResponse(
                {
                    "message": "Review posted successfully",
                    "pr_number": gh_request.payload.pull_request.number,
                    "comments_count": len(comments),
                }
            )
        except (HTTPError, TransportError):
            logger.exception("Unexpected error processing webhook", extra={"event": x_github_event})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")
    return None


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run("app.api_handler:app", host="0.0.0.0", port=8080, reload=True, log_level="info")
