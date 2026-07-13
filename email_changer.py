"""Shared logic for auto-changing a Telegram account's login email.

Primary provider : tempmail.plus  (mailto.plus domain)
Fallback provider: Guerrilla Mail (grr.la domain)

Both confirmed to receive Telegram verification emails.
No API key required. Completely free.

Key design decisions
────────────────────
* Accepts an optional pre-connected `client` (Telethon).  When the bot
  already has the account's session open it passes that client in; the
  function uses it directly and does NOT disconnect it when done.
  Without a client the function opens its own and does disconnect.
* FloodWaitError from SendVerifyEmailCodeRequest is caught; the function
  waits the required seconds (up to 10 min) then retries once.
* The midway-resend is removed to avoid triggering a second FloodWait.
  A single send + polling window is reliable enough with these providers.
"""

import os
import re as _re
import uuid
import asyncio
import json
import time
import urllib.request as _urlreq
from telethon import TelegramClient, functions, types, errors


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _http_get(url, timeout=15):
    req = _urlreq.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept':     'application/json',
    })
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _retry_get(url, retries=3, delay=4, timeout=15):
    last = None
    for i in range(retries):
        try:
            return _http_get(url, timeout)
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(delay)
    raise last


# ── OTP extraction ───────────────────────────────────────────────────────────

def _extract_code(text):
    """Return first standalone 5-6 digit number (the OTP)."""
    if not text:
        return None
    m = _re.search(r'(?<!\d)(\d{5,6})(?!\d)', text)
    return m.group(1) if m else None


def _strip_html(html):
    return _re.sub(r'<[^>]+>', ' ', html or '')


# ── Provider 1: tempmail.plus (mailto.plus) ──────────────────────────────────

class _MailtoPlusInbox:
    def __init__(self, name: str):
        self.name    = name
        self.address = f'{name}@mailto.plus'

    def check(self):
        try:
            data = _retry_get(
                f'https://tempmail.plus/api/mails'
                f'?email={_urlreq.quote(self.address)}&limit=20&epin=',
                retries=3, delay=3
            )
            for m in data.get('mail_list', []):
                # Code often appears in subject alone — fast path
                code = _extract_code(m.get('subject', ''))
                if code:
                    return code
                # Fetch full body only if needed
                try:
                    mid    = m['mail_id']
                    detail = _retry_get(
                        f'https://tempmail.plus/api/mails/{mid}'
                        f'?email={_urlreq.quote(self.address)}&epin=',
                        retries=2, delay=3
                    )
                    for part in (detail.get('subject', ''),
                                 detail.get('text', ''),
                                 _strip_html(detail.get('html', '') or '')):
                        code = _extract_code(part)
                        if code:
                            return code
                except Exception:
                    pass
        except Exception:
            pass
        return None


# ── Provider 2: Guerrilla Mail — grr.la (fallback) ──────────────────────────

class _GrrlInbox:
    def __init__(self, name: str):
        self.name    = name
        self.address = f'{name}@grr.la'
        self.sid     = ''
        try:
            d = _http_get(
                f'https://api.guerrillamail.com/ajax.php'
                f'?f=set_email_user&email_user={name}&lang=en&site=grr.la'
            )
            self.sid = d.get('sid_token', '')
        except Exception:
            pass

    def check(self):
        if not self.sid:
            return None
        try:
            data = _retry_get(
                f'https://api.guerrillamail.com/ajax.php'
                f'?f=get_email_list&offset=0&sid_token={self.sid}&seq=0',
                retries=3, delay=3
            )
            lst = data.get('list', [])
            if not isinstance(lst, list):
                return None
            for m in lst:
                code = _extract_code(m.get('mail_subject', ''))
                if code:
                    return code
                try:
                    mid    = m.get('mail_id', '')
                    detail = _retry_get(
                        f'https://api.guerrillamail.com/ajax.php'
                        f'?f=fetch_email&email_id={mid}&sid_token={self.sid}',
                        retries=2, delay=3
                    )
                    for part in (detail.get('mail_subject', ''),
                                 _strip_html(detail.get('mail_body', '')),
                                 detail.get('mail_text_only', '')):
                        code = _extract_code(part)
                        if code:
                            return code
                except Exception:
                    pass
        except Exception:
            pass
        return None


# ── Main entry point ─────────────────────────────────────────────────────────

async def change_email_for_number(
        phone, raw_phone, api_id, api_hash,
        sessions_dir, data_file,
        mail_user=None,
        log=None,
        max_wait_attempts=36,
        sleep_secs=5,
        existing_client=None):
    """Auto-changes a Telegram account's login email.

    Parameters
    ----------
    existing_client : telethon.TelegramClient, optional
        A pre-connected, authorised client for this account.  When supplied
        the function uses it directly and NEVER disconnects it.
        When None the function opens (and later closes) its own client.

    Returns
    -------
    dict  {'success': bool, 'message': str, 'email': str | None}
    """

    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    # ── Build a unique email name: last-7-digits + random ────────────────────
    digits = ''.join(c for c in raw_phone if c.isdigit())
    suffix = digits[-7:] if len(digits) >= 7 else digits
    rand   = uuid.uuid4().hex[:5]
    name   = f'{suffix}{rand}'

    # ── Try provider 1, fall back to provider 2 ──────────────────────────────
    inbox   = None
    address = None
    for cls, label in [(_MailtoPlusInbox, 'mailto.plus'),
                       (_GrrlInbox,       'grr.la')]:
        try:
            _log(f'🌐 Setting up inbox ({label})…')
            obj = await asyncio.to_thread(cls, name)
            if not getattr(obj, 'address', None):
                raise ValueError("no address")
            inbox   = obj
            address = obj.address
            _log(f'📧 Email: {address}')
            break
        except Exception as e:
            _log(f'⚠️ {label} setup failed: {e}')

    if inbox is None:
        return {'success': False,
                'message': 'Could not set up any temp inbox.',
                'email': None}

    # ── Prepare Telethon client ───────────────────────────────────────────────
    owns_client = existing_client is None
    if owns_client:
        session_path = os.path.join(sessions_dir, phone)
        client = TelegramClient(session_path, api_id, api_hash)
    else:
        client = existing_client

    try:
        if owns_client:
            await client.connect()
            if not await client.is_user_authorized():
                return {'success': False,
                        'message': 'Session not authorized',
                        'email': address}

        # ── Send verification email (with FloodWait handling) ─────────────────
        async def _send_code():
            await client(functions.account.SendVerifyEmailCodeRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                email=address
            ))

        _log(f'📤 Sending OTP to {address}…')
        try:
            await _send_code()
        except errors.FloodWaitError as e:
            wait = e.seconds
            if wait > 600:          # > 10 min — give up
                return {'success': False,
                        'message': f'Telegram rate limit: {wait}s wait required. Try later.',
                        'email': address}
            _log(f'⏱ Telegram rate limit — waiting {wait}s before retry…')
            await asyncio.sleep(wait + 2)
            try:
                await _send_code()
            except Exception as e2:
                return {'success': False,
                        'message': f'OTP send failed after flood wait: {e2}',
                        'email': address}
        except Exception as e:
            return {'success': False,
                    'message': f'OTP send failed: {e}',
                    'email': address}

        # ── Poll inbox ────────────────────────────────────────────────────────
        _log('⏳ OTP sent! Scanning inbox…')
        otp_code = None

        for attempt in range(max_wait_attempts):
            await asyncio.sleep(sleep_secs)
            _log(f'🔍 Checking inbox… ({attempt + 1}/{max_wait_attempts})')

            try:
                otp_code = await asyncio.to_thread(inbox.check)
            except Exception as e:
                _log(f'⚠️ Inbox check error: {e}')

            if otp_code:
                _log(f'✅ OTP found: {otp_code}')
                break

            # ── If primary inbox repeatedly empty, switch to fallback ─────────
            if not otp_code and attempt == 10 and isinstance(inbox, _MailtoPlusInbox):
                _log('🔄 mailto.plus: no messages after 50s — trying grr.la fallback…')
                try:
                    fb = await asyncio.to_thread(_GrrlInbox, name)
                    if fb.sid:
                        # Send OTP to grr.la address too
                        fb_address = fb.address
                        _log(f'📤 Sending OTP to fallback: {fb_address}')
                        try:
                            await client(functions.account.SendVerifyEmailCodeRequest(
                                purpose=types.EmailVerifyPurposeLoginChange(),
                                email=fb_address
                            ))
                            inbox   = fb
                            address = fb_address
                            _log(f'✅ Switched to grr.la: {fb_address}')
                        except errors.FloodWaitError as fe:
                            _log(f'⏱ Flood wait on fallback switch: {fe.seconds}s — staying on mailto.plus')
                        except Exception as se:
                            _log(f'⚠️ Fallback send failed: {se}')
                except Exception as fe:
                    _log(f'⚠️ Fallback setup failed: {fe}')

            _log('📬 No code yet…')

        if not otp_code:
            return {
                'success': False,
                'message': (f'OTP not received within '
                            f'{max_wait_attempts * sleep_secs}s. '
                            f'Try manual method.'),
                'email': address
            }

        # ── Verify with Telegram ──────────────────────────────────────────────
        _log('🔐 Verifying with Telegram…')
        try:
            await client(functions.account.VerifyEmailRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                verification=types.EmailVerificationCode(code=otp_code)
            ))
        except Exception as e:
            return {'success': False,
                    'message': f'Verification failed: {e}',
                    'email': address}

        # ── Persist flag in user_data.json ────────────────────────────────────
        try:
            user_data_all = (json.load(open(data_file))
                             if os.path.exists(data_file) else {})
            for uid, info in user_data_all.items():
                for detail in info.get('processing_details', []):
                    if detail.get('number', '').replace('+', '').strip() == raw_phone:
                        detail['email_changed'] = True
                        detail['changed_email']  = address
                        break
            with open(data_file, 'w') as fw:
                json.dump(user_data_all, fw, indent=4)
        except Exception as e:
            _log(f'⚠️ Could not persist email_changed flag: {e}')

        _log(f'🎉 Done! Email changed to {address}')
        return {'success': True,
                'message': f'Email changed to {address}!',
                'email': address}

    except Exception as e:
        return {'success': False, 'message': str(e), 'email': address}
    finally:
        # Only disconnect if we opened the client ourselves
        if owns_client and client.is_connected():
            await client.disconnect()
