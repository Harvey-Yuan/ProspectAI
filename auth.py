"""
Google OAuth2 — Login + Gmail send permission
==============================================
Flow:
  1. GET /auth/google           — redirect user to Google consent screen
  2. GET /auth/callback         — exchange code for tokens, store in session
  3. GET /auth/me               — return current user info (or unauthenticated)
  4. POST /auth/logout          — clear session

Required env vars (see .env.example):
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET

Scopes requested:
  openid email profile
  https://www.googleapis.com/auth/gmail.send
"""

import os
import time

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from starlette.requests import Request

router = APIRouter(prefix="/auth")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.send"
        ),
    },
)


@router.get("/google")
async def google_login(request: Request):
    """Redirect the user to Google's OAuth consent screen."""
    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        access_type="offline",   # request a refresh_token
        prompt="consent",        # always show consent to guarantee refresh_token
    )


@router.get("/callback", name="google_callback")
async def google_callback(request: Request):
    """Handle Google's redirect, exchange code for tokens, save to session."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        return RedirectResponse(url=f"/?auth_error={exc.error}")

    userinfo = token.get("userinfo") or {}

    request.session["user"] = {
        "email":   userinfo.get("email", ""),
        "name":    userinfo.get("name", ""),
        "picture": userinfo.get("picture", ""),
    }
    # Store only the fields we need; avoid serialising the full token object
    request.session["gmail_token"] = {
        "access_token":  token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "expires_at":    token.get("expires_at"),   # unix timestamp
    }

    return RedirectResponse(url="/")


@router.get("/me")
async def me(request: Request):
    """Return current session user, or {authenticated: false}."""
    user = request.session.get("user")
    if not user:
        return {"authenticated": False}
    has_gmail = bool(request.session.get("gmail_token", {}).get("access_token"))
    return {"authenticated": True, "gmail_connected": has_gmail, **user}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


# ── Gmail token helpers used by CRM Agent ────────────────────────────────────

def get_valid_access_token(gmail_token: dict) -> str | None:
    """
    Return a valid access token, refreshing it if it has expired.
    gmail_token must contain access_token, refresh_token, expires_at.
    """
    if not gmail_token:
        return None

    # Refresh if token expires within 60 seconds
    expires_at = gmail_token.get("expires_at") or 0
    if time.time() < float(expires_at) - 60:
        return gmail_token["access_token"]

    refresh_token = gmail_token.get("refresh_token")
    if not refresh_token:
        return gmail_token.get("access_token")  # use as-is, may fail

    import httpx
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id":     os.getenv("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        },
        timeout=10,
    )
    if resp.status_code == 200:
        new_token = resp.json()
        gmail_token["access_token"] = new_token["access_token"]
        gmail_token["expires_at"]   = time.time() + new_token.get("expires_in", 3600)
        return gmail_token["access_token"]

    return gmail_token.get("access_token")  # fallback


def send_gmail(gmail_token: dict, to: str, subject: str, body: str) -> bool:
    """
    Send an email via the Gmail REST API using the stored OAuth token.
    Returns True on success.
    """
    import base64
    import email.mime.text
    import httpx

    access_token = get_valid_access_token(gmail_token)
    if not access_token:
        raise RuntimeError("No valid Gmail access token available.")

    mime_msg = email.mime.text.MIMEText(body, "plain", "utf-8")
    mime_msg["to"]      = to
    mime_msg["subject"] = subject
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()

    resp = httpx.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
        timeout=15,
    )
    return resp.status_code == 200
