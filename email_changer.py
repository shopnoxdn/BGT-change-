"""Shared logic for auto-changing a Telegram account's login email.

Uses a real mailbox (Zoho Mail / any IMAP provider on a custom domain)
so that Telegram actually delivers the verification code — disposable
mail services (mail.tm, Guerrilla Mail, etc.) are silently blocked by
Telegram's delivery system.

Strategy:
  • For every number we generate a unique recipient alias:
        inbox+<phone_digits>_<random>@yourdomain.com
    All aliases land in the same inbox thanks to Zoho catch-all.
  • We send SendVerifyEmailCodeRequest, then poll IMAP for a new
    message addressed to that exact alias and extract the 6-digit code.
  • The IMAP credentials are read from environment variables so they
    never need to be hard-coded:
        IMAP_HOST      e.g. imap.zoho.com
        IMAP_PORT      e.g. 993  (SSL)
        IMAP_USER      e.g. inbox@yourdomain.com
        IMAP_PASS      your Zoho (or other provider) password / app-password
"""

import os
import re as _re
import uuid
import asyncio
import imaplib
import email as _email
from email.header import decode_header as _dh
from telethon import TelegramClient, functions, types

# ── IMAP credentials (set these as environment variables) ────────────────────
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.zoho.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER = os.environ.get("IMAP_USER", "")   # e.g. inbox@yourdomain.com
IMAP_PASS = os.environ.get("IMAP_PASS", "")   # Zoho password / app-password
# ─────────────────────────────────────────────────────────────────────────────


def _extract_code(text: str) -> str | None:
    """Return the first standalone 5-6 digit number found in text."""
    if not text:
        return None
    m = _re.search(r'(?<!\d)(\d{5,6})(?!\d)', text)
    return m.group(1) if m else None


def _decode_header_value(raw) -> str:
    """Safely decode an RFC-2047 encoded email header value."""
    if raw is None:
        return ""
    parts = _dh(raw)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _imap_search_for_alias(alias: str, log) -> str | None:
    """
    Open an IMAP connection, search INBOX for a message delivered TO
    <alias>, and return the first 6-digit code found in subject+body.
    Returns None if nothing found.
    """
    if not IMAP_USER or not IMAP_PASS:
        log("⚠️ IMAP credentials not configured (IMAP_USER / IMAP_PASS)")
        return None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("INBOX")

        # Search by TO header for this specific alias
        status, data = mail.search(None, f'TO "{alias}"')
        if status != "OK" or not data[0]:
            mail.logout()
            return None

        # Check messages newest-first
        ids = data[0].split()
        for mid in reversed(ids):
            _, msg_data = mail.fetch(mid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = _email.message_from_bytes(raw)

            subject = _decode_header_value(msg.get("Subject", ""))
            code = _extract_code(subject)
            if code:
                mail.logout()
                return code

            # Walk body parts
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct in ("text/plain", "text/html"):
                        payload = part.get_payload(decode=True)
                        if payload:
                            text = payload.decode(
                                part.get_content_charset() or "utf-8",
                                errors="replace"
                            )
                            # Strip HTML tags for the html part
                            if ct == "text/html":
                                text = _re.sub(r'<[^>]+>', ' ', text)
                            code = _extract_code(text)
                            if code:
                                mail.logout()
                                return code
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    text = payload.decode(
                        msg.get_content_charset() or "utf-8",
                        errors="replace"
                    )
                    code = _extract_code(text)
                    if code:
                        mail.logout()
                        return code

        mail.logout()
        return None
    except Exception as exc:
        log(f"⚠️ IMAP error: {exc}")
        return None


async def change_email_for_number(phone, raw_phone, api_id, api_hash,
                                   sessions_dir, data_file, mail_user=None,
                                   log=None, max_wait_attempts=36, sleep_secs=5):
    """Auto-changes a Telegram account's login email via IMAP inbox.

    Returns a dict: {'success': bool, 'message': str, 'email': str|None}
    """
    import json

    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    if not IMAP_USER or not IMAP_PASS:
        return {
            'success': False,
            'message': (
                'IMAP credentials not set. '
                'Please set IMAP_USER and IMAP_PASS environment variables.'
            ),
            'email': None
        }

    # Build a unique alias: inbox+<digits>_<random>@domain
    digits = ''.join(c for c in raw_phone if c.isdigit())
    rand   = uuid.uuid4().hex[:6]
    base_user, domain_part = IMAP_USER.split('@', 1)
    alias  = f"{base_user}+{digits}_{rand}@{domain_part}"
    _log(f'📧 Using email alias: {alias}')

    session_path = os.path.join(sessions_dir, phone)
    client = TelegramClient(session_path, api_id, api_hash)
    resent_once = False
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {'success': False, 'message': 'Session not authorized', 'email': alias}

        async def _send_code():
            await client(functions.account.SendVerifyEmailCodeRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                email=alias
            ))

        _log(f'📤 Sending OTP to {alias}')
        try:
            await _send_code()
        except Exception as e:
            return {'success': False, 'message': f'OTP send failed: {e}', 'email': alias}

        _log('⏳ OTP sent! Scanning inbox…')
        otp_code = None
        for attempt in range(max_wait_attempts):
            await asyncio.sleep(sleep_secs)
            _log(f'🔍 Checking inbox… ({attempt + 1}/{max_wait_attempts})')

            # Midway resend if still nothing
            if not otp_code and not resent_once and attempt >= max_wait_attempts // 2:
                resent_once = True
                _log('📭 No code yet halfway through — resending verification email…')
                try:
                    await _send_code()
                except Exception as e:
                    _log(f'⚠️ Resend failed: {e}')

            otp_code = await asyncio.to_thread(
                _imap_search_for_alias, alias, _log)

            if otp_code:
                _log(f'✅ OTP found: {otp_code}')
                break
            else:
                _log(f'📬 No code yet…')

        if not otp_code:
            return {
                'success': False,
                'message': f'OTP not received within {max_wait_attempts * sleep_secs}s. Try manual.',
                'email': alias
            }

        _log('🔐 Verifying with Telegram…')
        try:
            await client(functions.account.VerifyEmailRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                verification=types.EmailVerificationCode(code=otp_code)
            ))
        except Exception as e:
            return {'success': False, 'message': f'Verification failed: {e}', 'email': alias}

        # Persist email_changed flag in user_data.json
        try:
            user_data_all = json.load(open(data_file)) if os.path.exists(data_file) else {}
            for uid, info in user_data_all.items():
                for detail in info.get('processing_details', []):
                    if detail.get('number', '').replace('+', '').strip() == raw_phone:
                        detail['email_changed'] = True
                        break
            with open(data_file, 'w') as fw:
                json.dump(user_data_all, fw, indent=4)
        except Exception as e:
            _log(f'⚠️ Could not persist email_changed flag: {e}')

        _log(f'🎉 Done! Email changed to {alias}')
        return {'success': True, 'message': f'Email changed to {alias}!', 'email': alias}

    except Exception as e:
        return {'success': False, 'message': str(e), 'email': alias}
    finally:
        if client.is_connected():
            await client.disconnect()
