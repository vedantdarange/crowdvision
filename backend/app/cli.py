"""app/cli.py — Flask CLI commands.

Commands:
  flask seed-demo       Create seed users, zones, sources, settings, help_info.
  flask set-password    Change a user's password interactively.
"""
from __future__ import annotations

import json
import logging
import math
import secrets
import string
from datetime import datetime, timezone

import click
from flask import Flask

from app.config import load_settings
from app.core.geometry import polygon_area_m2, polygon_centroid

logger = logging.getLogger(__name__)

_ALPHANUM = string.ascii_letters + string.digits + "!@#$%^&*"


def _random_password(length: int = 16) -> str:
    """Generate a cryptographically random password."""
    return "".join(secrets.choice(_ALPHANUM) for _ in range(length))


def _make_polygon(centre_lat: float, centre_lng: float, half_w_m: float, half_h_m: float) -> dict:
    """Return a GeoJSON Polygon (closed) as a dict.

    Rectangle around *centre* with full dimensions (2*half_w_m) × (2*half_h_m).
    """
    mpd_lat = math.pi * 6_378_137.0 / 180.0
    mpd_lng = math.pi * 6_378_137.0 * math.cos(math.radians(centre_lat)) / 180.0

    dlat = half_h_m / mpd_lat
    dlng = half_w_m / mpd_lng

    ring = [
        [centre_lng - dlng, centre_lat - dlat],
        [centre_lng + dlng, centre_lat - dlat],
        [centre_lng + dlng, centre_lat + dlat],
        [centre_lng - dlng, centre_lat + dlat],
        [centre_lng - dlng, centre_lat - dlat],  # closed
    ]
    return {"type": "Polygon", "coordinates": [ring]}


_SEED_ACCOUNTS = [
    {"email": "admin@demo.local", "name": "Admin", "role": "admin"},
    {"email": "police1@demo.local", "name": "Police 1", "role": "police"},
    {"email": "police2@demo.local", "name": "Police 2", "role": "police"},
    {"email": "citizen@demo.local", "name": "Citizen", "role": "citizen"},
]

_DEFAULT_SETTINGS: dict[str, object] = {
    "detect_conf": 0.35,
    "smoothing_window": 5,
    "debounce_s": 3,
    "clear_s": 8,
    "hysteresis_ratio": 0.85,
    "cooldown_s": 60,
    "escalation_s": 60,
    "stale_after_s": 10,
    "reraise_after_s": 60,
    "target_fps": 3,
    "frame_width": 640,
    "jpeg_quality": 0.7,
    "default_warning_density": 3.0,
    "default_critical_density": 4.0,
    "help_info": {
        "emergency_numbers": [
            {"label": "Emergency (Unified)", "number": "112"},
            {"label": "Police", "number": "100"},
            {"label": "Ambulance", "number": "102"},
            {"label": "Fire", "number": "101"},
        ],
        "medical_points": [],
        "exits": [],
    },
}


def _seed_settings(db_session) -> None:  # type: ignore[no-untyped-def]
    from app.models.models import Settings as SettingsModel

    for key, value in _DEFAULT_SETTINGS.items():
        existing = db_session.get(SettingsModel, key)
        if existing is None:
            db_session.add(SettingsModel(key=key, value_json=json.dumps(value)))


def _seed_zones(db_session, centre_lat: float, centre_lng: float) -> None:  # type: ignore[no-untyped-def]
    """Create the 3 contract §11 seed zones with sources (idempotent)."""
    from app.models.models import Source, User, Zone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin_user = db_session.query(User).filter_by(email="admin@demo.local").first()
    admin_id = admin_user.id if admin_user else None

    zone_defs = [
        # (name, description, offset_lat_m, offset_lng_m, half_w_m, half_h_m,
        #  mode, warning_density, critical_density, warning_count, critical_count,
        #  source_name, source_kind, coverage_area_m2)
        (
            "Main Gate",
            "Main entrance area (COUNT mode demo)",
            0.0, -20.0, 2.5, 4.0,   # 5 × 8 = 40 m²
            "COUNT", 3.0, 4.0, 3, 5,
            "Main Gate Webcam", "WEBCAM", 25.0,
        ),
        (
            "Stage Area",
            "Main stage viewing area (COUNT mode demo)",
            30.0, 0.0, 5.0, 6.0,   # 10 × 12 = 120 m²
            "COUNT", 3.0, 4.0, 8, 10,
            "Stage Video Feed", "VIDEO_FILE", 60.0,
        ),
        (
            "Exit Lane",
            "Emergency exit lane (DENSITY mode demo)",
            -30.0, 20.0, 2.5, 2.5,  # 5 × 5 = 25 m²
            "DENSITY", 3.0, 4.0, None, None,
            "Exit Lane Camera", "VIDEO_FILE", 6.0,
        ),
    ]

    mpd_lat = math.pi * 6_378_137.0 / 180.0
    mpd_lng = math.pi * 6_378_137.0 * math.cos(math.radians(centre_lat)) / 180.0

    for (
        name, description, offset_lat_m, offset_lng_m,
        half_w_m, half_h_m,
        mode, w_density, c_density, w_count, c_count,
        source_name, source_kind, coverage,
    ) in zone_defs:
        # Idempotency: skip if active zone with this name already exists
        existing = db_session.query(Zone).filter_by(name=name, is_active=True).first()
        if existing is not None:
            click.echo(f"  Zone '{name}' already exists — skipping.")
            continue

        z_lat = centre_lat + offset_lat_m / mpd_lat
        z_lng = centre_lng + offset_lng_m / mpd_lng

        geom = _make_polygon(z_lat, z_lng, half_w_m, half_h_m)
        geom_json = json.dumps(geom)
        area = polygon_area_m2(geom)
        clat, clng = polygon_centroid(geom)

        zone = Zone(
            name=name,
            description=description,
            geometry_json=geom_json,
            centroid_lat=clat,
            centroid_lng=clng,
            area_m2=area,
            mode=mode,
            warning_density=w_density,
            critical_density=c_density,
            warning_count=w_count,
            critical_count=c_count,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db_session.add(zone)
        db_session.flush()

        actual_coverage = min(coverage, area)

        source = Source(
            zone_id=zone.id,
            name=source_name,
            kind=source_kind,
            coverage_area_m2=actual_coverage,
            is_active=True,
            created_by=admin_id,
            created_at=now,
        )
        db_session.add(source)
        click.echo(f"  Created zone '{name}' (area={area:.1f} m², coverage={actual_coverage:.1f} m²)")


def register_commands(app: Flask) -> None:
    """Register all CLI commands on *app*."""

    @app.cli.command("seed-demo")
    def seed_demo() -> None:
        """Seed demo users, zones, sources, settings and help_info.

        Idempotent: running twice does not duplicate rows.
        Refuses when FLASK_ENV=production.
        """
        from argon2 import PasswordHasher

        from app.extensions import db
        from app.models.models import User

        cfg = load_settings()
        if cfg.flask_env == "production":
            click.echo(
                "ERROR: seed-demo refuses to run when FLASK_ENV=production.",
                err=True,
            )
            raise SystemExit(1)

        ph = PasswordHasher()
        seed_pw: str | None = cfg.seed_password
        generated_passwords: dict[str, str] = {}
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        with app.app_context():
            for acct in _SEED_ACCOUNTS:
                email = acct["email"]
                existing = db.session.query(User).filter(
                    User.email.ilike(email)
                ).first()
                if existing is not None:
                    click.echo(f"  User {email} already exists — skipping.")
                    continue

                pw = seed_pw if seed_pw else _random_password()
                if not seed_pw:
                    generated_passwords[email] = pw

                user = User(
                    name=acct["name"],
                    email=email,
                    password_hash=ph.hash(pw),
                    role=acct["role"],
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                db.session.add(user)
                click.echo(f"  Created user {email} (role={acct['role']})")

            db.session.flush()

            _seed_zones(db.session, cfg.demo_center[0], cfg.demo_center[1])
            _seed_settings(db.session)

            db.session.commit()
            click.echo("seed-demo complete.")

        if generated_passwords:
            click.echo("\n=== Generated passwords (save these — printed once) ===")
            for email, pw in generated_passwords.items():
                click.echo(f"  {email}: {pw}")
            click.echo("=======================================================\n")

    @app.cli.command("set-password")
    @click.argument("email")
    def set_password(email: str) -> None:
        """Set a new password for the user with EMAIL (prompts interactively)."""
        from argon2 import PasswordHasher

        from app.extensions import db
        from app.models.models import User

        new_pw = click.prompt("New password", hide_input=True, confirmation_prompt=True)
        if len(new_pw) < 8:
            click.echo("ERROR: password must be at least 8 characters.", err=True)
            raise SystemExit(1)

        with app.app_context():
            user = db.session.query(User).filter(User.email.ilike(email)).first()
            if user is None:
                click.echo(f"ERROR: no user found with email {email!r}.", err=True)
                raise SystemExit(1)
            ph = PasswordHasher()
            user.password_hash = ph.hash(new_pw)
            user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
            click.echo(f"Password updated for {email}.")
