from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class User(BaseModel):
    login: str
    id: int
    html_url: Optional[str] = None
    type: Optional[str] = None
    site_admin: Optional[bool] = None


class Repository(BaseModel):
    id: int
    full_name: str
    html_url: str
    default_branch: str
    language: Optional[str] = None
    visibility: str


class PullRequestRef(BaseModel):
    label: str
    ref: str
    sha: str


class PullRequest(BaseModel):
    id: int
    number: int
    state: str
    title: str
    html_url: str
    diff_url: str
    patch_url: str
    issue_url: str
    user: User
    body: Optional[str] = None
    created_at: str
    updated_at: str
    closed_at: Optional[str] = None
    merged_at: Optional[str] = None
    merge_commit_sha: Optional[str] = None
    draft: bool
    head: PullRequestRef
    base: PullRequestRef
    merged: bool
    mergeable: Optional[bool] = None
    rebaseable: Optional[bool] = None
    mergeable_state: Optional[str] = None
    comments: int
    review_comments: int
    commits: int
    additions: int
    deletions: int
    changed_files: int


class Payload(BaseModel):
    action: str
    number: int
    pull_request: PullRequest
    repository: Repository
    sender: User


class GitHubRequest(BaseModel):
    payload: Payload
