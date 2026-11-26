"""app/container.py — Dependency injection wiring.

Builds repositories and services and attaches the Container instance
to flask_app.extensions['container'] inside create_app().
"""
from __future__ import annotations

from dataclasses import dataclass

from flask import Flask, current_app

from app.repositories.audit_repo import AuditRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.user_service import UserService


@dataclass(frozen=True)
class Container:
    user_repo: UserRepository
    audit_repo: AuditRepository
    audit_service: AuditService
    auth_service: AuthService
    user_service: UserService


def wire(flask_app: Flask) -> Container:
    """Instantiate repositories & services and bind them to *flask_app*."""
    user_repo = UserRepository()
    audit_repo = AuditRepository()
    audit_service = AuditService(audit_repo)
    auth_service = AuthService(user_repo)
    user_service = UserService(user_repo, audit_service)

    container = Container(
        user_repo=user_repo,
        audit_repo=audit_repo,
        audit_service=audit_service,
        auth_service=auth_service,
        user_service=user_service,
    )
    flask_app.extensions["container"] = container
    return container


def get_container() -> Container:
    """Return the wired Container for the active Flask application."""
    return current_app.extensions["container"]
