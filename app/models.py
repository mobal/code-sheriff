from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Repository(BaseModel):
    full_name: str


class PullRequest(BaseModel):
    body: str
    html_url: str
    number: int
    repository: Repository
    title: str


class GitHubRequest(BaseModel):
    action: str
    pull_request: PullRequest
