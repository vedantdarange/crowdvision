"""tests/integration/test_analytics_audit_demo.py — B8 Analytics, CSV, Audit Log, Retention, Demo SPA & Safety Check."""
from __future__ import annotations

import codecs
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [77.2090, 28.6139],
        [77.2094, 28.6139],
        [77.2094, 28.6143],
        [77.2090, 28.6143],
        [77.2090, 28.6139],
    ]],
}


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _utc_naive(y: int, m: int, d: int, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).replace(tzinfo=None)


class TestAnalyticsAndCsvExport:
    def test_analytics_summary_known_numbers_and_null_response_times(
        self, app, client, clean_db, make_user, token_for
    ):
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.extensions import db
        from app.models.models import AlertModel, Report, Zone, ZoneSample

        pol = make_user(name="AnalystPol", email="apol@test.local", role="police")
        adm = make_user(name="AnalystAdm", email="aadm@test.local", role="admin")
        cit = make_user(name="AnalystCit", email="acit@test.local", role="citizen")
        pol_tok = token_for(pol.id, role="police")
        adm_tok = token_for(adm.id, role="admin")

        r_z1 = client.post(
            "/api/v1/zones",
            headers=_auth(adm_tok),
            json={
                "name": "Main Gate",
                "geometry": _SQUARE,
                "mode": "DENSITY",
                "warning_density": 3.0,
                "critical_density": 4.0,
            },
        )
        assert r_z1.status_code == 201
        z1_id = r_z1.get_json()["data"]["id"]

        r_z2 = client.post(
            "/api/v1/zones",
            headers=_auth(adm_tok),
            json={
                "name": "Exit Lane",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [77.2100, 28.6150],
                        [77.2104, 28.6150],
                        [77.2104, 28.6154],
                        [77.2100, 28.6154],
                        [77.2100, 28.6150],
                    ]],
                },
                "mode": "DENSITY",
                "warning_density": 3.0,
                "critical_density": 4.0,
            },
        )
        assert r_z2.status_code == 201
        z2_id = r_z2.get_json()["data"]["id"]

        # Anchor clock at 2026-11-25T10:00:00Z so default 24 h covers 2026-11-24T10:00:00Z .. 2026-11-25T10:00:00Z
        anchor = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
        clock = FakeClock(start=anchor.timestamp())

        with app.app_context():
            c = get_container()
            orig_clock = c.analytics_service._clock
            c.analytics_service._clock = clock

            # In-range alerts:
            # 1) Main Gate CRITICAL: ack +60s, resolve +180s
            a1 = AlertModel(
                zone_id=z1_id,
                level="CRITICAL",
                peak_level="CRITICAL",
                status="RESOLVED",
                condition_active=False,
                peak_density=4.8,
                peak_count=20.0,
                created_at=_utc_naive(2026, 11, 24, 12, 0, 0),
                acknowledged_at=_utc_naive(2026, 11, 24, 12, 1, 0),
                resolved_at=_utc_naive(2026, 11, 24, 12, 3, 0),
            )
            # 2) Main Gate WARNING: ack +120s, un-resolved
            a2 = AlertModel(
                zone_id=z1_id,
                level="WARNING",
                peak_level="WARNING",
                status="AUTO_CLEARED",
                condition_active=False,
                peak_density=3.2,
                peak_count=12.0,
                created_at=_utc_naive(2026, 11, 24, 14, 0, 0),
                acknowledged_at=_utc_naive(2026, 11, 24, 14, 2, 0),
                resolved_at=None,
            )
            # 3) Exit Lane CRITICAL: neither acknowledged nor resolved
            a3 = AlertModel(
                zone_id=z2_id,
                level="CRITICAL",
                peak_level="CRITICAL",
                status="NEW",
                condition_active=True,
                peak_density=5.1,
                peak_count=25.0,
                created_at=_utc_naive(2026, 11, 25, 8, 0, 0),
            )
            # 4) Out-of-range alert (>24h ago) -> excluded from default 24 h summary
            a_old = AlertModel(
                zone_id=z2_id,
                level="WARNING",
                peak_level="WARNING",
                status="AUTO_CLEARED",
                condition_active=False,
                peak_density=3.1,
                peak_count=9.0,
                created_at=_utc_naive(2026, 11, 23, 9, 0, 0),
            )

            # ZoneSamples in UTC -> IST (+05:30):
            # Main Gate: 10:00 UTC (= 15:30 IST -> hour 15) avg=1.0; 18:45 UTC (= 00:15 IST -> hour 0) avg=4.5
            # Exit Lane: 09:29 UTC (= 14:59 IST -> hour 14) avg=2.0; 09:30 UTC (= 15:00 IST -> hour 15) avg=3.5
            samples = [
                ZoneSample(zone_id=z1_id, ts=_utc_naive(2026, 11, 24, 10, 0), count=5.0, density=1.0, level="SAFE"),
                ZoneSample(zone_id=z1_id, ts=_utc_naive(2026, 11, 24, 18, 45), count=18.0, density=4.0, level="CRITICAL"),
                ZoneSample(zone_id=z1_id, ts=_utc_naive(2026, 11, 24, 18, 50), count=20.0, density=5.0, level="CRITICAL"),
                ZoneSample(zone_id=z2_id, ts=_utc_naive(2026, 11, 25, 9, 29), count=8.0, density=2.0, level="SAFE"),
                ZoneSample(zone_id=z2_id, ts=_utc_naive(2026, 11, 25, 9, 30), count=14.0, density=3.5, level="WARNING"),
                # Old sample outside range
                ZoneSample(zone_id=z2_id, ts=_utc_naive(2026, 11, 20, 9, 0), count=99.0, density=9.9, level="CRITICAL"),
            ]

            # Reports: 2 PENDING, 1 VERIFIED, 0 DISMISSED in range; 1 DISMISSED out of range
            reports = [
                Report(kind="CROWD", status="PENDING", zone_id=z1_id, lat=28.6141, lng=77.2092, count=5.0, created_by=cit.id, created_at=_utc_naive(2026, 11, 24, 11, 0)),
                Report(kind="SOS", status="PENDING", zone_id=z1_id, lat=28.6141, lng=77.2092, sos_type="FIRE", created_by=cit.id, created_at=_utc_naive(2026, 11, 24, 13, 0)),
                Report(kind="CROWD", status="VERIFIED", zone_id=z2_id, lat=28.6152, lng=77.2102, count=9.0, created_by=cit.id, created_at=_utc_naive(2026, 11, 25, 1, 0)),
                Report(kind="SOS", status="DISMISSED", zone_id=z2_id, lat=28.6152, lng=77.2102, sos_type="OTHER", created_by=cit.id, created_at=_utc_naive(2026, 11, 20, 1, 0)),
            ]

            db.session.add_all([a1, a2, a3, a_old, *samples, *reports])
            db.session.commit()

        try:
            resp = client.get("/api/v1/analytics/summary", headers=_auth(pol_tok))
            assert resp.status_code == 200
            data = resp.get_json()["data"]

            fixture_keys = set(
                json.loads(
                    (Path(__file__).resolve().parents[3] / "contract" / "examples" / "analytics_summary.json").read_text(encoding="utf-8")
                ).keys()
            )
            assert set(data.keys()) == fixture_keys
            assert data["from"] == "2026-11-24T10:00:00Z"
            assert data["to"] == "2026-11-25T10:00:00Z"
            assert data["timezone"] == "Asia/Kolkata"
            assert data["alerts_by_zone"] == [
                {"zone_id": z1_id, "zone_name": "Main Gate", "warning": 1, "critical": 1},
                {"zone_id": z2_id, "zone_name": "Exit Lane", "warning": 0, "critical": 1},
            ]
            # (60 + 120) / 2 = 90.0; resolved = 180.0
            assert data["avg_ack_seconds"] == pytest.approx(90.0)
            assert data["avg_resolve_seconds"] == pytest.approx(180.0)
            assert data["peak_hours"] == [
                {"zone_id": z1_id, "zone_name": "Main Gate", "hour": 0, "avg_density": pytest.approx(4.5)},
                {"zone_id": z2_id, "zone_name": "Exit Lane", "hour": 15, "avg_density": pytest.approx(3.5)},
            ]
            assert data["reports_by_status"] == {"PENDING": 2, "VERIFIED": 1, "DISMISSED": 0}

            # Narrow empty window -> avg_ack_seconds & avg_resolve_seconds are null, all report counts 0
            r_empty = client.get(
                "/api/v1/analytics/summary?from=2026-11-01T00:00:00Z&to=2026-11-01T01:00:00Z",
                headers=_auth(pol_tok),
            )
            assert r_empty.status_code == 200
            d_empty = r_empty.get_json()["data"]
            assert d_empty["alerts_by_zone"] == []
            assert d_empty["avg_ack_seconds"] is None
            assert d_empty["avg_resolve_seconds"] is None
            assert d_empty["peak_hours"] == []
            assert d_empty["reports_by_status"] == {"PENDING": 0, "VERIFIED": 0, "DISMISSED": 0}

            # Invalid range -> 422
            r_bad = client.get(
                "/api/v1/analytics/summary?from=2026-11-26T00:00:00Z&to=2026-11-25T00:00:00Z",
                headers=_auth(pol_tok),
            )
            assert r_bad.status_code == 422
            assert r_bad.get_json()["error"]["code"] == "VALIDATION_ERROR"
        finally:
            with app.app_context():
                get_container().analytics_service._clock = orig_clock

    def test_ist_peak_hour_midnight_utc_and_half_hour_offsets(
        self, app, client, clean_db, make_user, token_for
    ):
        """18:45 UTC -> 00:15 IST (hour 0), 18:15 UTC -> 23:45 IST (hour 23), 09:30 UTC -> hour 15 IST."""
        from app.extensions import db
        from app.models.models import ZoneSample

        adm = make_user(name="ISTAdm", email="ist_adm@test.local", role="admin")
        pol = make_user(name="ISTPol", email="ist_pol@test.local", role="police")
        adm_tok = token_for(adm.id, role="admin")
        pol_tok = token_for(pol.id, role="police")

        rz = client.post(
            "/api/v1/zones",
            headers=_auth(adm_tok),
            json={
                "name": "Midnight Zone",
                "geometry": _SQUARE,
                "mode": "DENSITY",
                "warning_density": 3.0,
                "critical_density": 4.0,
            },
        )
        assert rz.status_code == 201
        zid = rz.get_json()["data"]["id"]

        with app.app_context():
            db.session.add_all([
                # 18:15 UTC = 23:45 IST (hour 23) -> lower density
                ZoneSample(zone_id=zid, ts=_utc_naive(2026, 11, 24, 18, 15), count=5.0, density=1.2, level="SAFE"),
                # 18:45 UTC = 00:15 IST (hour 0, NOT hour 23!) -> highest density
                ZoneSample(zone_id=zid, ts=_utc_naive(2026, 11, 24, 18, 45), count=16.0, density=4.1, level="CRITICAL"),
            ])
            db.session.commit()

        r = client.get(
            "/api/v1/analytics/summary?from=2026-11-24T18:00:00Z&to=2026-11-24T19:00:00Z",
            headers=_auth(pol_tok),
        )
        assert r.status_code == 200
        peak = r.get_json()["data"]["peak_hours"]
        assert peak == [{"zone_id": zid, "zone_name": "Midnight Zone", "hour": 0, "avg_density": pytest.approx(4.1)}]

    def test_export_alerts_csv_bom_headers_escaping_and_range(
        self, app, client, clean_db, make_user, token_for
    ):
        from app.extensions import db
        from app.models.models import AlertModel

        adm = make_user(name="CsvAdm", email="csv_adm@test.local", role="admin")
        adm_tok = token_for(adm.id, role="admin")

        # Zone name with comma and quotes to verify RFC 4180 CSV escaping
        zone_name = 'Main Gate, "North" Wing'
        rz = client.post(
            "/api/v1/zones",
            headers=_auth(adm_tok),
            json={
                "name": zone_name,
                "geometry": _SQUARE,
                "mode": "DENSITY",
                "warning_density": 3.0,
                "critical_density": 4.0,
            },
        )
        assert rz.status_code == 201
        zid = rz.get_json()["data"]["id"]

        with app.app_context():
            a1 = AlertModel(
                zone_id=zid,
                level="CRITICAL",
                peak_level="CRITICAL",
                status="RESOLVED",
                condition_active=False,
                peak_density=4.5,
                peak_count=18.0,
                created_at=_utc_naive(2026, 11, 24, 10, 0, 0),
                acknowledged_at=_utc_naive(2026, 11, 24, 10, 1, 0),
                resolved_at=_utc_naive(2026, 11, 24, 10, 5, 0),
            )
            a_outside = AlertModel(
                zone_id=zid,
                level="WARNING",
                peak_level="WARNING",
                status="NEW",
                condition_active=True,
                peak_density=3.1,
                peak_count=10.0,
                created_at=_utc_naive(2026, 11, 20, 10, 0, 0),
            )
            db.session.add_all([a1, a_outside])
            db.session.commit()
            a1_id = a1.id

        resp = client.get(
            "/api/v1/analytics/export/alerts.csv?from=2026-11-24T00:00:00Z&to=2026-11-25T00:00:00Z",
            headers=_auth(adm_tok),
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("Content-Type", "")
        assert "charset=utf-8" in resp.headers.get("Content-Type", "").lower()
        cd = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd and "alerts.csv" in cd

        raw = resp.data
        assert raw.startswith(codecs.BOM_UTF8)
        text = raw.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == [
            "id",
            "zone",
            "level",
            "peak_level",
            "status",
            "peak_density",
            "peak_count",
            "created_at",
            "acknowledged_at",
            "resolved_at",
        ]
        assert len(rows) == 2
        assert rows[1] == [
            str(a1_id),
            zone_name,
            "CRITICAL",
            "CRITICAL",
            "RESOLVED",
            "4.5",
            "18",
            "2026-11-24T10:00:00Z",
            "2026-11-24T10:01:00Z",
            "2026-11-24T10:05:00Z",
        ]


class TestAuditLogsAndRetention:
    def test_audit_logs_pagination_and_filters(
        self, app, client, clean_db, make_user, token_for
    ):
        from app.extensions import db
        from app.models.models import AuditLog

        adm = make_user(name="AuditAdm", email="aud_adm@test.local", role="admin")
        pol = make_user(name="AuditPol", email="aud_pol@test.local", role="police")
        adm_tok = token_for(adm.id, role="admin")

        with app.app_context():
            db.session.add_all([
                AuditLog(actor_id=adm.id, action="ZONE_CREATED", entity_type="zone", entity_id=1, data_json='{"name":"Z1"}', created_at=_utc_naive(2026, 11, 24, 10, 0)),
                AuditLog(actor_id=pol.id, action="ALERT_ACKNOWLEDGED", entity_type="alert", entity_id=2, data_json='{}', created_at=_utc_naive(2026, 11, 24, 10, 1)),
                AuditLog(actor_id=pol.id, action="ALERT_RESOLVED", entity_type="alert", entity_id=2, data_json='{"note":"clear"}', created_at=_utc_naive(2026, 11, 24, 10, 2)),
                AuditLog(actor_id=adm.id, action="ZONE_CREATED", entity_type="zone", entity_id=3, data_json='{"name":"Z3"}', created_at=_utc_naive(2026, 11, 24, 10, 3)),
            ])
            db.session.commit()

        # Page 1 limit 2 -> newest first
        r_p1 = client.get("/api/v1/audit-logs?page=1&limit=2", headers=_auth(adm_tok))
        assert r_p1.status_code == 200
        body1 = r_p1.get_json()
        assert body1["pagination"] == {"total": 4, "page": 1, "limit": 2, "total_pages": 2}
        assert [row["entity_id"] for row in body1["data"]] == [3, 2]

        fixture_keys = set(
            json.loads(
                (Path(__file__).resolve().parents[3] / "contract" / "examples" / "audit_logs_list.json").read_text(encoding="utf-8")
            )["data"][0].keys()
        )
        assert set(body1["data"][0].keys()) == fixture_keys

        # Page 2 limit 2
        r_p2 = client.get("/api/v1/audit-logs?page=2&limit=2", headers=_auth(adm_tok))
        assert r_p2.status_code == 200
        assert [row["entity_id"] for row in r_p2.get_json()["data"]] == [2, 1]

        # Filter by action
        r_act = client.get("/api/v1/audit-logs?action=ZONE_CREATED", headers=_auth(adm_tok))
        assert r_act.status_code == 200
        assert r_act.get_json()["pagination"]["total"] == 2
        assert all(row["action"] == "ZONE_CREATED" for row in r_act.get_json()["data"])

        # Filter by actor_id
        r_actor = client.get(f"/api/v1/audit-logs?actor_id={pol.id}", headers=_auth(adm_tok))
        assert r_actor.status_code == 200
        assert r_actor.get_json()["pagination"]["total"] == 2
        assert all(row["actor"] == {"id": pol.id, "name": "AuditPol"} for row in r_actor.get_json()["data"])

        # Bad actor_id -> 422
        assert client.get("/api/v1/audit-logs?actor_id=notanint", headers=_auth(adm_tok)).status_code == 422

    def test_hourly_retention_deletes_old_samples_and_reports_with_fake_clock(
        self, app, client, clean_db, make_user, token_for
    ):
        from app.core.clock import FakeClock
        from app.extensions import db
        from app.models.models import Report, ZoneSample
        from app.realtime.tasks import run_tick_once

        adm = make_user(name="RetAdm", email="ret_adm@test.local", role="admin")
        cit = make_user(name="RetCit", email="ret_cit@test.local", role="citizen")
        adm_tok = token_for(adm.id, role="admin")

        rz = client.post(
            "/api/v1/zones",
            headers=_auth(adm_tok),
            json={
                "name": "Retention Zone",
                "geometry": _SQUARE,
                "mode": "DENSITY",
                "warning_density": 3.0,
                "critical_density": 4.0,
            },
        )
        assert rz.status_code == 201
        zid = rz.get_json()["data"]["id"]

        clock = FakeClock(start=1_700_000_000.0)
        now_naive = clock.utcnow().replace(tzinfo=None)

        with app.app_context():
            old_sample = ZoneSample(zone_id=zid, ts=now_naive - timedelta(days=7, minutes=1), count=2.0, density=0.5, level="SAFE")
            fresh_sample = ZoneSample(zone_id=zid, ts=now_naive - timedelta(days=6, hours=12), count=3.0, density=0.8, level="SAFE")
            old_report = Report(kind="SOS", status="PENDING", zone_id=zid, lat=28.6141, lng=77.2092, sos_type="OTHER", created_by=cit.id, created_at=now_naive - timedelta(days=31))
            fresh_report = Report(kind="CROWD", status="PENDING", zone_id=zid, lat=28.6141, lng=77.2092, count=4.0, created_by=cit.id, created_at=now_naive - timedelta(days=29))
            db.session.add_all([old_sample, fresh_sample, old_report, fresh_report])
            db.session.commit()
            old_s_id, fresh_s_id = old_sample.id, fresh_sample.id
            old_r_id, fresh_r_id = old_report.id, fresh_report.id

        s1 = run_tick_once(app, now=clock.utcnow())
        assert s1["samples_pruned"] == 1
        assert s1["reports_pruned"] == 1

        with app.app_context():
            assert db.session.get(ZoneSample, old_s_id) is None
            assert db.session.get(ZoneSample, fresh_s_id) is not None
            assert db.session.get(Report, old_r_id) is None
            assert db.session.get(Report, fresh_r_id) is not None

        # Before 1 hour elapses, retention does not re-run even if new stale rows exist
        clock.advance(100.0)
        with app.app_context():
            later_old = ZoneSample(zone_id=zid, ts=now_naive - timedelta(days=8), count=1.0, density=0.2, level="SAFE")
            db.session.add(later_old)
            db.session.commit()
            later_old_id = later_old.id
        s2 = run_tick_once(app, now=clock.utcnow())
        assert s2["samples_pruned"] == 0
        with app.app_context():
            assert db.session.get(ZoneSample, later_old_id) is not None

        # After 3600s total, hourly retention triggers again
        clock.advance(3550.0)
        s3 = run_tick_once(app, now=clock.utcnow())
        assert s3["samples_pruned"] == 1
        with app.app_context():
            assert db.session.get(ZoneSample, later_old_id) is None


class TestDemoServingAndStartupSafetyCheck:
    def test_startup_refuses_default_admin_password_with_serve_frontend_until_set_password(
        self, tmp_path, monkeypatch
    ):
        from argon2 import PasswordHasher
        from click.testing import CliRunner

        from app import create_app
        from app.core.time import utcnow
        from app.extensions import db
        from app.models.models import User

        db_file = tmp_path / "safety_check.db"
        db_uri = f"sqlite:///{db_file.as_posix()}"
        monkeypatch.setenv("DATABASE_URL", db_uri)
        monkeypatch.setenv("DETECTOR_BACKEND", "fake")

        # 1) Create DB and seed an admin with Demo@1234
        setup_app = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": db_uri,
                "RATELIMIT_ENABLED": False,
                "SERVE_FRONTEND": False,
            }
        )
        with setup_app.app_context():
            db.create_all()
            now_naive = utcnow().replace(tzinfo=None)
            admin = User(
                name="Demo Admin",
                email="admin@demo.local",
                password_hash=PasswordHasher().hash("Demo@1234"),
                role="admin",
                is_active=True,
                created_at=now_naive,
                updated_at=now_naive,
            )
            db.session.add(admin)
            db.session.commit()
            db.session.remove()
            db.engine.dispose()

        # 2) SERVE_FRONTEND=true without ALLOW_DEFAULT_PASSWORDS refuses to start
        with pytest.raises(RuntimeError, match="SERVE_FRONTEND=true"):
            create_app(
                config_override={
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": db_uri,
                    "RATELIMIT_ENABLED": False,
                    "SERVE_FRONTEND": True,
                    "ALLOW_DEFAULT_PASSWORDS": False,
                }
            )
        # Clean up engine handles from failed startup before next check
        with setup_app.app_context():
            db.session.remove()
            db.engine.dispose()

        # 3) ALLOW_DEFAULT_PASSWORDS=true overrides refusal
        allowed_app = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": db_uri,
                "RATELIMIT_ENABLED": False,
                "SERVE_FRONTEND": True,
                "ALLOW_DEFAULT_PASSWORDS": True,
            }
        )
        with allowed_app.app_context():
            db.session.remove()
            db.engine.dispose()

        # 4) Run documented fix `flask set-password admin@demo.local`, then startup succeeds
        runner = CliRunner()
        res = runner.invoke(
            setup_app.cli,
            ["set-password", "admin@demo.local"],
            input="StrongNewPass@99\nStrongNewPass@99\n",
            catch_exceptions=False,
        )
        assert res.exit_code == 0

        hardened_app = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": db_uri,
                "RATELIMIT_ENABLED": False,
                "SERVE_FRONTEND": True,
                "ALLOW_DEFAULT_PASSWORDS": False,
            }
        )
        with hardened_app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_spa_static_serving_deep_links_cache_headers_and_api_404(self, tmp_path):
        from app import create_app
        from app.extensions import db

        dist_dir = tmp_path / "dist"
        assets_dir = dist_dir / "assets"
        assets_dir.mkdir(parents=True)
        (dist_dir / "index.html").write_text("<!doctype html><html><body>SPA</body></html>", encoding="utf-8")
        (dist_dir / "sw.js").write_text("self.addEventListener('push', () => {});", encoding="utf-8")
        (assets_dir / "app-abc123.js").write_text("console.log('crowdvision');", encoding="utf-8")

        spa_app = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "RATELIMIT_ENABLED": False,
                "SERVE_FRONTEND": True,
                "ALLOW_DEFAULT_PASSWORDS": True,
                "FRONTEND_DIST_DIR": str(dist_dir),
            }
        )
        with spa_app.app_context():
            db.create_all()

        try:
            with spa_app.test_client() as tc:
                # Root -> index.html + no-cache
                r_root = tc.get("/")
                assert r_root.status_code == 200
                assert "SPA" in r_root.get_data(as_text=True)
                assert r_root.headers.get("Cache-Control") == "no-cache"

                # Deep link -> index.html + no-cache
                r_deep = tc.get("/police/alerts/3")
                assert r_deep.status_code == 200
                assert "SPA" in r_deep.get_data(as_text=True)
                assert r_deep.headers.get("Cache-Control") == "no-cache"

                # Service worker -> real file + no-cache
                r_sw = tc.get("/sw.js")
                assert r_sw.status_code == 200
                assert "addEventListener" in r_sw.get_data(as_text=True)
                assert r_sw.headers.get("Cache-Control") == "no-cache"

                # Hashed asset -> real file + cacheable
                r_asset = tc.get("/assets/app-abc123.js")
                assert r_asset.status_code == 200
                assert "crowdvision" in r_asset.get_data(as_text=True)
                cc_asset = r_asset.headers.get("Cache-Control", "")
                assert "max-age=31536000" in cc_asset and "no-cache" not in cc_asset

                # Unknown /api/* routes still return JSON 404 envelope (GET and POST)
                for fn in (tc.get, tc.post):
                    r_api_404 = fn("/api/unknown")
                    assert r_api_404.status_code == 404
                    assert r_api_404.get_json()["error"]["code"] == "NOT_FOUND"

                # Real /api/v1/health continues to work
                r_health = tc.get("/api/v1/health")
                assert r_health.status_code == 200
                assert r_health.get_json()["status"] == "ok"
        finally:
            with spa_app.app_context():
                db.session.remove()
                db.drop_all()
                db.engine.dispose()


def _free_tcp_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _windows_child_pids(parent_pid: int) -> list[int]:
    """Return immediate child PIDs of `parent_pid` on Windows via Toolhelp snapshot."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    children: list[int] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if int(entry.th32ParentProcessID) == int(parent_pid):
                    children.append(int(entry.th32ProcessID))
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return children


def _is_pid_alive(pid: int) -> bool:
    import ctypes
    import os
    from ctypes import wintypes

    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = wintypes.DWORD(0)
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return int(code.value) == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 3.0) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestWsgiSubprocessEntryPoint:
    def test_wsgi_module_exposes_app_for_cli_and_gunicorn(self, tmp_path):
        import os
        import subprocess
        import sys

        backend_dir = Path(__file__).resolve().parents[2]
        db_path = tmp_path / "wsgi_import.db"
        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
                "FLASK_ENV": "production",
                "SERVE_FRONTEND": "false",
                "DETECTOR_BACKEND": "fake",
                "SECRET_KEY": "wsgi-import-secret-key",
                "JWT_SECRET_KEY": "wsgi-import-jwt-secret-key-at-least-32-bytes!",
                "VAPID_PUBLIC_KEY": "",
                "VAPID_PRIVATE_KEY": "",
            }
        )
        # Simulates Gunicorn importing `wsgi:app` (where __name__ == "wsgi")
        res = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from flask import Flask; import wsgi; "
                    "assert isinstance(wsgi.app, Flask); "
                    "assert '/api/v1/health' in {r.rule for r in wsgi.app.url_map.iter_rules()}"
                ),
            ],
            cwd=str(backend_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res.returncode == 0, f"Importing wsgi:app failed: {res.stdout}\n{res.stderr}"

    def test_wsgi_windows_subprocess_startup_websocket_and_clean_shutdown(self, tmp_path):
        import os
        import signal
        import subprocess
        import sys
        import time
        import urllib.request
        from PIL import Image
        import simple_websocket

        backend_dir = Path(__file__).resolve().parents[2]
        db_path = tmp_path / "wsgi_subproc.db"
        port = _free_tcp_port()

        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
                "FLASK_ENV": "production",
                "SERVE_FRONTEND": "false",
                "ALLOW_DEFAULT_PASSWORDS": "true",
                "DETECTOR_BACKEND": "fake",
                "SEED_PASSWORD": "Demo@1234",
                "SECRET_KEY": "wsgi-subproc-secret-key",
                "JWT_SECRET_KEY": "wsgi-subproc-jwt-secret-key-at-least-32-bytes!",
                "VAPID_PUBLIC_KEY": "",
                "VAPID_PRIVATE_KEY": "",
                "RATELIMIT_ENABLED": "false",
                "PORT": str(port),
            }
        )

        # Verify `wsgi:app` works with Flask CLI migrations & seed (seed-demo requires non-production env)
        seed_env = {**env, "FLASK_ENV": "development"}
        for args in (["db", "upgrade"], ["seed-demo"]):
            res = subprocess.run(
                [sys.executable, "-m", "flask", "--app", "wsgi:app", *args],
                cwd=str(backend_dir),
                env=seed_env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert res.returncode == 0, f"flask {args} failed: {res.stderr}"

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, "wsgi.py"],
            cwd=str(backend_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )

        worker_pids: list[int] = []
        ws = None
        try:
            base_http = f"http://127.0.0.1:{port}"
            health: dict | None = None
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    out, err = proc.communicate(timeout=5)
                    pytest.fail(
                        f"python wsgi.py exited early code={proc.returncode}\n"
                        f"stdout={out}\nstderr={err}"
                    )
                try:
                    status, health = _http_json(f"{base_http}/api/v1/health", timeout=2.0)
                    if (
                        status == 200
                        and health.get("detector") == "ready"
                        and health.get("worker_alive") is True
                    ):
                        break
                except Exception:
                    pass
                time.sleep(0.25)

            assert health is not None, "Timed out waiting for /api/v1/health HTTP response"
            assert health["detector"] == "ready" and health["worker_alive"] is True, (
                f"Expected ready detector worker within 15s, got health={health}"
            )
            assert health["status"] == "ok" and health["db"] == "ok"

            if os.name == "nt":
                worker_pids = _windows_child_pids(proc.pid)
                assert len(worker_pids) == 1, f"Expected 1 detector worker child, got {worker_pids}"
            else:
                out_ps = subprocess.check_output(["pgrep", "-P", str(proc.pid)], text=True)
                worker_pids = [int(p) for p in out_ps.split() if p.strip().isdigit()]
                assert len(worker_pids) == 1, f"Expected 1 detector worker child, got {worker_pids}"

            # Login & fetch an active seeded source
            st_login, body_login = _http_json(
                f"{base_http}/api/v1/auth/login",
                method="POST",
                body={"email": "police1@demo.local", "password": "Demo@1234"},
            )
            assert st_login == 200, body_login
            token = body_login["data"]["access_token"]

            req_src = urllib.request.Request(
                f"{base_http}/api/v1/sources",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req_src, timeout=3.0) as resp_src:
                assert resp_src.status == 200
                sources = json.loads(resp_src.read().decode("utf-8"))["data"]
            assert len(sources) >= 1
            source_id = sources[0]["id"]

            # Connect real WebSocket client and verify frame:submit -> frame:result
            ws = simple_websocket.Client.connect(
                f"ws://127.0.0.1:{port}/socket.io/?EIO=4&transport=websocket"
            )
            eio_open = ws.receive(timeout=5)
            assert isinstance(eio_open, str) and eio_open.startswith("0"), eio_open
            ws.send("40" + json.dumps({"token": token}))

            connected_ack = False
            hellos: list[dict] = []
            ws_deadline = time.monotonic() + 5.0
            while (not connected_ack or not hellos) and time.monotonic() < ws_deadline:
                pkt = ws.receive(timeout=5)
                if pkt == "2":
                    ws.send("3")
                    continue
                if isinstance(pkt, str) and pkt.startswith("40"):
                    connected_ack = True
                elif isinstance(pkt, str) and pkt.startswith("42"):
                    ev, payload = json.loads(pkt[2:])
                    if ev == "hello":
                        hellos.append(payload)
            assert connected_ack and len(hellos) == 1

            buf = io.BytesIO()
            Image.new("RGB", (64, 64), color=(100, 140, 200)).save(buf, format="JPEG")
            jpeg_bytes = buf.getvalue()

            ws.send(
                "451-"
                + json.dumps(
                    [
                        "frame:submit",
                        {
                            "source_id": source_id,
                            "seq": 1,
                            "captured_at": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                            "reset": True,
                            "width": 64,
                            "height": 64,
                            "image": {"_placeholder": True, "num": 0},
                        },
                    ]
                )
            )
            ws.send(jpeg_bytes)

            frame_results: list[dict] = []
            res_deadline = time.monotonic() + 8.0
            while not frame_results and time.monotonic() < res_deadline:
                pkt = ws.receive(timeout=5)
                if pkt == "2":
                    ws.send("3")
                    continue
                if isinstance(pkt, str) and pkt.startswith("42"):
                    ev, payload = json.loads(pkt[2:])
                    if ev == "frame:result":
                        frame_results.append(payload)

            assert len(frame_results) == 1
            fr = frame_results[0]
            assert fr["ok"] is True
            assert fr["source_id"] == source_id
            assert fr["seq"] == 1
            ws.send("41")
            ws.close()
            ws = None
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            if proc.poll() is None:
                sig = signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT
                proc.send_signal(sig)
                try:
                    proc.wait(timeout=10.0)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    proc.wait(timeout=5.0)
                    pytest.fail("python wsgi.py did not shut down within 10s")
            try:
                proc.communicate(timeout=2.0)
            except Exception:
                pass

            # Confirm no orphan worker survives shutdown
            wait_exit = time.monotonic() + 3.0
            while any(_is_pid_alive(pid) for pid in worker_pids) and time.monotonic() < wait_exit:
                time.sleep(0.1)
            orphans = [pid for pid in worker_pids if _is_pid_alive(pid)]
            if orphans:
                for pid in orphans:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                    else:
                        os.kill(pid, signal.SIGKILL)
            assert orphans == [], f"Orphan worker processes survived shutdown: {orphans}"
