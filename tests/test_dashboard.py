from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
VIEWER_PASSWORD = "ViewerPass!12?"


@pytest.fixture()
def superadmin(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def public_user(db, superadmin):
    create_user_account(
        actor_username="admin",
        username="viewer",
        password=VIEWER_PASSWORD,
        role="public",
    )
    return User.objects.get(username="viewer")


def _body(response) -> str:
    return response.content.decode("utf-8")


# Toolbar links are rendered by base.html with the src-badge class. They
# only appear when the corresponding context-processor variable is set,
# so asserting on this specific attribute combo doubles as a regression
# guard for the render_to_string -> render() fix.
TOOLBAR_ADMIN = 'src-badge primary" href="/admin/"'
TOOLBAR_DOCS = 'src-badge primary" href="/docs"'
TOOLBAR_REDOC = 'src-badge primary" href="/redoc"'

# Hero/sidebar admin link uses the icon-action class on the dashboard.
HERO_OR_SIDEBAR_ADMIN = 'icon-action" href="/admin/"'


# ---- Anonymous visitor ----


@pytest.mark.django_db
def test_anon_dashboard_renders_app_name_and_login_cta(client):
    response = client.get("/")
    body = _body(response)

    assert response.status_code == 200
    assert "AMELI App Template" in body
    assert "Template Django-first listo para heredar" in body
    # The hero shows a primary Ingresar CTA and the toolbar shows a login link.
    assert "Ingresar" in body
    assert "/login/" in body


@pytest.mark.django_db
def test_anon_dashboard_toolbar_has_docs_and_redoc(client):
    # Regression guard: render_to_string used to skip context processors,
    # so docs_enabled / redoc_enabled were undefined and these toolbar
    # links disappeared. The view now uses render(request, ...).
    response = client.get("/")
    body = _body(response)

    assert TOOLBAR_DOCS in body
    assert TOOLBAR_REDOC in body


@pytest.mark.django_db
def test_anon_dashboard_does_not_link_to_admin(client):
    response = client.get("/")
    body = _body(response)

    # No href="/admin/" anywhere on the page (toolbar, hero, sidebar)
    assert 'href="/admin/"' not in body


@pytest.mark.django_db
def test_anon_dashboard_sidebar_shows_onboarding(client):
    response = client.get("/")
    body = _body(response)

    assert "Siguientes pasos para una app nueva" in body
    assert "Renombrar paquete" in body
    assert "Bootstrap admin" in body


# ---- Authenticated superadmin ----


@pytest.mark.django_db
def test_superadmin_dashboard_greets_user(client, superadmin):
    client.force_login(superadmin)
    response = client.get("/")
    body = _body(response)

    assert response.status_code == 200
    assert "Hola, admin" in body
    assert "@admin" in body
    assert "superadmin" in body


@pytest.mark.django_db
def test_superadmin_dashboard_toolbar_has_admin_link(client, superadmin):
    # Regression guard for the same context-processor bug: the toolbar
    # link in base.html depends on can_access_admin from the context
    # processor. Without it the link silently disappeared.
    client.force_login(superadmin)
    response = client.get("/")
    body = _body(response)

    assert TOOLBAR_ADMIN in body


@pytest.mark.django_db
def test_superadmin_dashboard_hero_and_sidebar_include_admin(client, superadmin):
    client.force_login(superadmin)
    response = client.get("/")
    body = _body(response)

    # icon-action class is what hero and sidebar use for the admin link
    assert HERO_OR_SIDEBAR_ADMIN in body
    # And the public-only login CTA must not appear for authenticated users
    assert "Ingresar" not in body


@pytest.mark.django_db
def test_superadmin_dashboard_sidebar_shows_quick_access(client, superadmin):
    client.force_login(superadmin)
    response = client.get("/")
    body = _body(response)

    assert "Accesos rapidos" in body
    # The onboarding panel must NOT appear for authenticated users
    assert "Siguientes pasos para una app nueva" not in body


# ---- Authenticated public user ----


@pytest.mark.django_db
def test_public_user_dashboard_hides_admin_links(client, public_user):
    client.force_login(public_user)
    response = client.get("/")
    body = _body(response)

    assert response.status_code == 200
    assert "Hola, viewer" in body
    # No admin link should be exposed to a public user
    assert 'href="/admin/"' not in body
