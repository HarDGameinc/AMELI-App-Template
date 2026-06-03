from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.TemplateLoginView.as_view(), name="login"),
    path("login", views.TemplateLoginView.as_view()),
    path("logout/", views.logout_view, name="logout"),
    path("logout", views.logout_view),
    path("profile/", views.profile_view, name="profile"),
    path("profile", views.profile_view),
    path("profile/preferences/", views.update_preferences, name="profile-preferences"),
    path("profile/preferences", views.update_preferences),
    path("profile/avatar/", views.update_avatar, name="profile-avatar"),
    path("profile/avatar", views.update_avatar),
    path("profile/avatar/delete/", views.delete_avatar_view, name="profile-avatar-delete"),
    path("profile/avatar/delete", views.delete_avatar_view),
    path("profile/password/", views.change_password_view, name="profile-password"),
    path("profile/change-password", views.change_password_view),
    path("profile/sessions/revoke-others/", views.revoke_other_sessions_view, name="profile-revoke-others"),
    path("profile/sessions/revoke-others", views.revoke_other_sessions_view),
    path("profile/sessions/<str:session_key>/revoke/", views.revoke_session_view, name="profile-revoke-session"),
    path("profile/sessions/<str:session_key>/revoke", views.revoke_session_view),
    path("profile/mfa/start/", views.mfa_start_view, name="profile-mfa-start"),
    path("profile/mfa/start", views.mfa_start_view),
    path("profile/mfa/confirm/", views.mfa_confirm_view, name="profile-mfa-confirm"),
    path("profile/mfa/confirm", views.mfa_confirm_view),
    path("profile/mfa/disable/", views.mfa_disable_view, name="profile-mfa-disable"),
    path("profile/mfa/disable", views.mfa_disable_view),
    path("api/admin/session", views.admin_session_json, name="admin-session-json"),
]
