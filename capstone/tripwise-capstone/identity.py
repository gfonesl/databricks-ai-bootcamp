from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class Role(StrEnum):
    OWNER = "owner"
    AUTOMATION = "automation"


class AuthorizationError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Actor:
    subject: str
    role: Role


def _subjects(variable_name: str) -> frozenset[str]:
    return frozenset(
        value.strip() for value in os.getenv(variable_name, "").split(",") if value.strip()
    )


def auth_mode() -> str:
    mode = os.getenv("TRIPWISE_AUTH_MODE", "enforce").strip().casefold()
    if mode not in {"enforce", "disabled"}:
        raise RuntimeError("TRIPWISE_AUTH_MODE must be 'enforce' or 'disabled'.")
    return mode


def validate_auth_config() -> None:
    if auth_mode() == "disabled":
        return
    missing = [
        name
        for name in ("TRIPWISE_OWNER_SUBJECTS", "TRIPWISE_AUTOMATION_SUBJECTS")
        if not _subjects(name)
    ]
    if missing:
        raise RuntimeError(
            "Tripwise authorization is not configured. Missing: " + ", ".join(missing)
        )


def required_role(path: str) -> Role | None:
    if path in {"/healthz", "/readyz"} or path.startswith("/static/"):
        return None
    if path == "/api/pipeline/context":
        return Role.AUTOMATION
    if path in {"/mcp", "/mcp/"}:
        return Role.AUTOMATION
    return Role.OWNER


def authorize(headers: Mapping[str, str], role: Role | None) -> Actor:
    if auth_mode() == "disabled":
        return Actor(subject="local-development", role=role or Role.OWNER)
    if role is None:
        return Actor(subject="health-probe", role=Role.AUTOMATION)

    subject = headers.get("x-forwarded-user", "").strip()
    if not subject:
        raise AuthorizationError(401, "Authenticated Databricks identity is required.")

    allowed = {
        Role.OWNER: _subjects("TRIPWISE_OWNER_SUBJECTS"),
        Role.AUTOMATION: _subjects("TRIPWISE_AUTOMATION_SUBJECTS"),
    }[role]
    if subject not in allowed:
        raise AuthorizationError(403, "This identity is not authorized for this operation.")
    return Actor(subject=subject, role=role)
