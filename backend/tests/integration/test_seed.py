"""tests/integration/test_seed.py — flask seed-demo & set-password CLI tests.

Covers:
- Idempotency: running seed-demo twice does not duplicate rows
- Refuses in production (FLASK_ENV=production)
- Uses SEED_PASSWORD when set (does not print generated passwords)
- Generates & prints random passwords once when SEED_PASSWORD is unset
- Creates 4 accounts, 3 zones (~40/120/25 m²), 3 sources, settings & help_info
- set-password updates user password hash
- Partial unique index: second active zone with same name rejected
- Partial unique index: second open alert for one zone rejected; allowed once resolved
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest


class TestSeedDemo:
    @pytest.fixture(autouse=True, scope="class")
    def _fresh_db(self, app):
        """Each class gets a clean DB slate."""
        from app.extensions import db

        with app.app_context():
            db.drop_all()
            db.create_all()
        yield
        with app.app_context():
            db.drop_all()
            db.create_all()

    def test_refuses_in_production(self, app):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            app.cli,
            ["seed-demo"],
            env={**os.environ, "FLASK_ENV": "production"},
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "production" in result.output.lower() or "refuse" in result.output.lower()

    def test_seed_creates_accounts(self, app):
        from argon2 import PasswordHasher
        from click.testing import CliRunner

        from app.extensions import db
        from app.models.models import User

        runner = CliRunner()
        result = runner.invoke(
            app.cli,
            ["seed-demo"],
            env={**os.environ, "FLASK_ENV": "testing", "SEED_PASSWORD": "TestPass@1234"},
            catch_exceptions=False,
        )
        assert result.exit_code == 0

        ph = PasswordHasher()
        with app.app_context():
            users = db.session.query(User).all()
            by_email = {u.email: u for u in users}
        assert set(by_email.keys()) == {
            "admin@demo.local",
            "police1@demo.local",
            "police2@demo.local",
            "citizen@demo.local",
        }
        assert ph.verify(by_email["admin@demo.local"].password_hash, "TestPass@1234")

    def test_seed_creates_zones_sources_and_help_info(self, app):
        from app.extensions import db
        from app.models.models import Settings as SettingsModel, Source, Zone

        with app.app_context():
            zones = {z.name: z for z in db.session.query(Zone).all()}
            sources = {s.name: s for s in db.session.query(Source).all()}
            help_row = db.session.get(SettingsModel, "help_info")

        assert set(zones.keys()) == {"Main Gate", "Stage Area", "Exit Lane"}
        assert abs(zones["Main Gate"].area_m2 - 40.0) < 1.0
        assert zones["Main Gate"].mode == "COUNT"
        assert (zones["Main Gate"].warning_count, zones["Main Gate"].critical_count) == (3, 5)

        assert abs(zones["Stage Area"].area_m2 - 120.0) < 2.0
        assert zones["Stage Area"].mode == "COUNT"
        assert (zones["Stage Area"].warning_count, zones["Stage Area"].critical_count) == (8, 10)

        assert abs(zones["Exit Lane"].area_m2 - 25.0) < 1.0
        assert zones["Exit Lane"].mode == "DENSITY"

        assert len(sources) == 3
        assert sources["Main Gate Webcam"].coverage_area_m2 == 25.0
        assert sources["Stage Video Feed"].coverage_area_m2 == 60.0
        assert sources["Exit Lane Camera"].coverage_area_m2 == 6.0

        assert help_row is not None
        numbers = {item["number"] for item in json.loads(help_row.value_json)["emergency_numbers"]}
        assert {"112", "100", "102", "101"}.issubset(numbers)

    def test_seed_idempotent(self, app):
        """Running seed-demo a second time must not create duplicate rows."""
        from click.testing import CliRunner

        from app.extensions import db
        from app.models.models import Source, User, Zone

        runner = CliRunner()
        result = runner.invoke(
            app.cli,
            ["seed-demo"],
            env={**os.environ, "FLASK_ENV": "testing", "SEED_PASSWORD": "TestPass@1234"},
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        with app.app_context():
            assert db.session.query(User).count() == 4
            assert db.session.query(Zone).count() == 3
            assert db.session.query(Source).count() == 3

    def test_seed_password_env_no_printed_passwords(self, app):
        """When SEED_PASSWORD is set, generated passwords must NOT be printed."""
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            app.cli,
            ["seed-demo"],
            env={**os.environ, "FLASK_ENV": "testing", "SEED_PASSWORD": "TestPass@1234"},
            catch_exceptions=False,
        )
        assert "Generated passwords" not in result.output

    def test_seed_without_seed_password_generates_and_prints_once(self, app, monkeypatch):
        """When SEED_PASSWORD is unset, random passwords are generated and printed."""
        from click.testing import CliRunner

        from app.extensions import db
        from app.models.models import User

        monkeypatch.delenv("SEED_PASSWORD", raising=False)
        with app.app_context():
            db.session.query(User).filter_by(email="citizen@demo.local").delete()
            db.session.commit()

        runner = CliRunner()
        result = runner.invoke(
            app.cli,
            ["seed-demo"],
            env={"FLASK_ENV": "testing"},
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "Generated passwords" in result.output
        assert "citizen@demo.local:" in result.output

    def test_set_password_updates_hash(self, app):
        from argon2 import PasswordHasher
        from click.testing import CliRunner

        from app.extensions import db
        from app.models.models import User

        runner = CliRunner()
        result = runner.invoke(
            app.cli,
            ["set-password", "citizen@demo.local"],
            input="NewSecret@99\nNewSecret@99\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0

        ph = PasswordHasher()
        with app.app_context():
            user = db.session.query(User).filter_by(email="citizen@demo.local").first()
            assert user is not None
            assert ph.verify(user.password_hash, "NewSecret@99")

    def test_zone_name_partial_unique_index(self, app):
        """A second active zone with the same name must be rejected by the DB."""
        from sqlalchemy.exc import IntegrityError

        from app.extensions import db
        from app.models.models import Zone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        duplicate_geom = json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [77.0, 28.0],
                        [77.001, 28.0],
                        [77.001, 28.001],
                        [77.0, 28.001],
                        [77.0, 28.0],
                    ]
                ],
            }
        )
        with app.app_context():
            existing = db.session.query(Zone).filter_by(name="Main Gate").first()
            assert existing is not None

            dup = Zone(
                name="Main Gate",
                description="duplicate",
                geometry_json=duplicate_geom,
                centroid_lat=28.0005,
                centroid_lng=77.0005,
                area_m2=100.0,
                mode="DENSITY",
                warning_density=3.0,
                critical_density=4.0,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.session.add(dup)
            with pytest.raises(IntegrityError):
                db.session.flush()
            db.session.rollback()

    def test_zone_name_allowed_after_soft_delete(self, app):
        """After soft-deleting the original, a new zone with the same name is OK."""
        from app.extensions import db
        from app.models.models import Zone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        duplicate_geom = json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [77.0, 28.0],
                        [77.001, 28.0],
                        [77.001, 28.001],
                        [77.0, 28.001],
                        [77.0, 28.0],
                    ]
                ],
            }
        )
        with app.app_context():
            existing = db.session.query(Zone).filter_by(name="Stage Area").first()
            assert existing is not None
            existing.is_active = False
            db.session.flush()

            reused = Zone(
                name="Stage Area",
                description="reused name",
                geometry_json=duplicate_geom,
                centroid_lat=28.0005,
                centroid_lng=77.0005,
                area_m2=200.0,
                mode="DENSITY",
                warning_density=3.0,
                critical_density=4.0,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.session.add(reused)
            db.session.flush()
            db.session.rollback()

    def test_open_alert_partial_unique_index(self, app):
        """At most one open alert per zone; second raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        from app.extensions import db
        from app.models.models import AlertModel, Zone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with app.app_context():
            zone = db.session.query(Zone).filter_by(name="Main Gate").first()
            assert zone is not None

            db.session.query(AlertModel).filter_by(zone_id=zone.id).delete()
            db.session.flush()

            a1 = AlertModel(
                zone_id=zone.id,
                level="WARNING",
                peak_level="WARNING",
                status="NEW",
                condition_active=True,
                peak_density=3.5,
                peak_count=4,
                created_at=now,
            )
            db.session.add(a1)
            db.session.flush()

            a2 = AlertModel(
                zone_id=zone.id,
                level="WARNING",
                peak_level="WARNING",
                status="NEW",
                condition_active=True,
                peak_density=3.6,
                peak_count=5,
                created_at=now,
            )
            db.session.add(a2)
            with pytest.raises(IntegrityError):
                db.session.flush()
            db.session.rollback()

    def test_open_alert_allowed_after_resolve(self, app):
        """A new open alert is allowed once the previous one is RESOLVED."""
        from app.extensions import db
        from app.models.models import AlertModel, Zone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with app.app_context():
            zone = db.session.query(Zone).filter_by(name="Exit Lane").first()
            assert zone is not None

            db.session.query(AlertModel).filter_by(zone_id=zone.id).delete()
            db.session.flush()

            a1 = AlertModel(
                zone_id=zone.id,
                level="WARNING",
                peak_level="WARNING",
                status="RESOLVED",
                condition_active=False,
                peak_density=3.5,
                peak_count=4,
                created_at=now,
            )
            db.session.add(a1)
            db.session.flush()

            a2 = AlertModel(
                zone_id=zone.id,
                level="CRITICAL",
                peak_level="CRITICAL",
                status="NEW",
                condition_active=True,
                peak_density=4.5,
                peak_count=6,
                created_at=now,
            )
            db.session.add(a2)
            db.session.flush()
            db.session.rollback()
