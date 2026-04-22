"""Auth dependencies for write endpoints.

Phase 0: bearer-token check on admin endpoints. The token is configured via
`ADMIN_API_TOKEN` env var. If the token is unset, admin endpoints refuse all
requests (fail closed) — operators must explicitly provision a token.

Kept deliberately simple: no user/role model, no JWT, no SSO. Those arrive
alongside audit logging and RBAC in a later phase.
"""

import hmac
import logging

from fastapi import Header, HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)


def require_admin_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """FastAPI dependency: enforce bearer-token auth on admin endpoints.

    Returns an opaque principal identifier ("admin") when auth succeeds.
    Raises 401/403 on failure. Uses constant-time compare to avoid timing leaks.

    Future sessions: when SSO/RBAC arrives, replace this with a dependency that
    returns a richer principal (user id, roles) and keep call sites unchanged.
    """
    expected = settings.admin_api_token
    if not expected:
        logger.error(
            "Admin endpoint called but ADMIN_API_TOKEN is unset; refusing request"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "data": None,
                "error": {
                    "code": "ADMIN_NOT_CONFIGURED",
                    "message": "Admin API token is not configured on the server.",
                },
                "meta": None,
            },
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "data": None,
                "error": {
                    "code": "MISSING_BEARER_TOKEN",
                    "message": "Authorization: Bearer <token> header is required.",
                },
                "meta": None,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(presented, expected):
        client = request.client.host if request.client else "unknown"
        logger.warning("Rejected admin request with bad token from %s", client)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "data": None,
                "error": {
                    "code": "INVALID_BEARER_TOKEN",
                    "message": "The provided bearer token is not valid.",
                },
                "meta": None,
            },
        )

    return "admin"
