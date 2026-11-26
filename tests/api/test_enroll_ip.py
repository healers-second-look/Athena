"""Rate limiting must not trust client-spoofed forwarding headers by default."""

from __future__ import annotations

from secondlook.study.enrollment import reset_rate_limits

from .test_enroll_routes import _make_client


def test_spoofed_x_forwarded_for_does_not_bypass_rate_limit(monkeypatch):
    client, _ = _make_client(monkeypatch, require_enrollment=False)
    reset_rate_limits()
    for i in range(10):
        client.post(
            "/api/study/enroll/code",
            json={"code": "ATH-0000-00"},
            headers={"X-Forwarded-For": f"1.2.3.{i}", "X-Real-IP": f"4.5.6.{i}"},
        )
    resp = client.post(
        "/api/study/enroll/code",
        json={"code": "ATH-0000-00"},
        headers={"X-Forwarded-For": "9.9.9.9", "X-Real-IP": "8.8.8.8"},
    )
    assert resp.status_code == 429
