import pytest
from fastapi import HTTPException


def test_require_admin_valid_token(monkeypatch):
    from apps.shared.config import settings
    from apps.api.router_admin import require_admin
    monkeypatch.setattr(settings, "admin_token", "test-secret")
    require_admin(admin_session="test-secret")  # must not raise


def test_require_admin_wrong_token(monkeypatch):
    from apps.shared.config import settings
    from apps.api.router_admin import require_admin
    monkeypatch.setattr(settings, "admin_token", "test-secret")
    with pytest.raises(HTTPException) as exc:
        require_admin(admin_session="wrong")
    assert exc.value.status_code == 403


def test_require_admin_empty_app_token(monkeypatch):
    from apps.shared.config import settings
    from apps.api.router_admin import require_admin
    monkeypatch.setattr(settings, "admin_token", "")
    with pytest.raises(HTTPException) as exc:
        require_admin(admin_session="")
    assert exc.value.status_code == 403
