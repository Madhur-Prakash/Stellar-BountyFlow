"""GitHub endpoints: account linking (gist proof or optional OAuth), pull requests on submissions, and the
webhook receiver."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.core.rate_limit import rate_limit
from app.dependencies import CurrentUser, SessionDep
from app.modules.github import accounts, webhook
from app.modules.github import service as pr_service
from app.modules.github.schemas import (
    ChallengeOut,
    ChallengeRequest,
    GistVerifyRequest,
    GitHubAccountOut,
    GitHubConfigOut,
    OAuthCallbackRequest,
    OAuthStartOut,
    PublicGitHubAccount,
    PullRequestAdd,
    PullRequestOut,
)

router = APIRouter(tags=["github"])


@router.get("/github/config", response_model=GitHubConfigOut)
async def github_config() -> GitHubConfigOut:
    return accounts.config()


@router.get("/github/account", response_model=GitHubAccountOut | None)
async def my_account(session: SessionDep, user: CurrentUser) -> GitHubAccountOut | None:
    return await accounts.get_account(session, user)


@router.post("/github/account/challenge", response_model=ChallengeOut)
async def challenge(data: ChallengeRequest, user: CurrentUser) -> ChallengeOut:
    return await accounts.issue_challenge(user, data.login)


@router.post("/github/account/verify-gist", response_model=GitHubAccountOut)
async def verify_gist(data: GistVerifyRequest, session: SessionDep, user: CurrentUser) -> GitHubAccountOut:
    return await accounts.verify_gist(session, user, data.gist_url)


@router.post("/github/oauth/start", response_model=OAuthStartOut)
async def oauth_start(user: CurrentUser) -> OAuthStartOut:
    return await accounts.start_oauth(user)


@router.post("/github/oauth/callback", response_model=GitHubAccountOut)
async def oauth_callback(
    data: OAuthCallbackRequest, session: SessionDep, user: CurrentUser
) -> GitHubAccountOut:
    return await accounts.complete_oauth(session, user, data.code, data.state)


@router.delete("/github/account", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def unlink(session: SessionDep, user: CurrentUser) -> Response:
    await accounts.unlink(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{username}/github", response_model=PublicGitHubAccount | None)
async def public_account(username: str, session: SessionDep) -> PublicGitHubAccount | None:
    return await accounts.get_public_account(session, username)


@router.get("/submissions/{submission_id}/pull-requests", response_model=list[PullRequestOut])
async def list_pull_requests(
    submission_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[PullRequestOut]:
    return await pr_service.list_for_submission(session, user, submission_id)


@router.post(
    "/submissions/{submission_id}/pull-requests",
    response_model=PullRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("github:link-pr", 60, 3600))],
)
async def add_pull_request(
    submission_id: uuid.UUID, data: PullRequestAdd, session: SessionDep, user: CurrentUser
) -> PullRequestOut:
    return await pr_service.add(session, user, submission_id, data.url)


@router.delete(
    "/submissions/{submission_id}/pull-requests/{pull_request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_pull_request(
    submission_id: uuid.UUID, pull_request_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Response:
    await pr_service.remove(session, user, submission_id, pull_request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/submissions/{submission_id}/pull-requests/recheck", response_model=list[PullRequestOut])
async def recheck_pull_requests(
    submission_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[PullRequestOut]:
    return await pr_service.recheck(session, user, submission_id)


@router.post(
    "/github/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("github:webhook", 600, 60))],
)
async def github_webhook(
    request: Request,
    session: SessionDep,
    x_github_event: Annotated[str | None, Header()] = None,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """HMAC-verified (``GITHUB_WEBHOOK_SECRET``); CSRF-exempt because GitHub signs every delivery."""
    return await webhook.handle_delivery(
        session,
        body=await request.body(),
        event=x_github_event,
        signature_header=x_hub_signature_256,
        delivery_id=x_github_delivery,
    )
