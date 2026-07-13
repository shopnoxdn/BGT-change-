"""Shared logic for auto-changing a Telegram account's login email.

Uses tempmail.plus (mailto.plus domain) as primary provider — confirmed
to receive Telegram verification emails. Falls back to grr.la (Guerrilla
Mail) if the primary fails.

Both providers are free, require no registration and no API key.
"""

import os
import re as _re
import uuid
import asyncio
import json
import time
import urllib.request as _urlreq
from telethon import TelegramClient, functions, types


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url, headers=None, timeout=15):
    h = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    if headers:
        h.update(headers)
    req = _urlreq.Request(url, headers=h)
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url, data, timeout=15):
    body = json.dumps(data).encode()
    h = {'Content-Type': 'application/json', 'Accept': 'application/json',
         'User-Agent': 'Mozilla/5.0'}
    req = _urlreq.Request(url, data=body, headers=h, method='POST')
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _retry(fn, retries=4, delay=3):
    """Call fn(), retry on any exception with increasing delay."""
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(delay * (i + 1))
    raise last


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------

def _extract_code(text):
    """Return first standalone 5-6 digit number (the OTP)."""
    if not text:
        return None
    m = _re.search(r'(?<!\d)(\d{5,6})(?!\d)', text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Provider 1: tempmail.plus  (mailto.plus)
# ---------------------------------------------------------------------------

class MailtoPlusInbox:
    """No-registration temp inbox at mailto.plus."""

    def __init__(self, name: str):
        self.name = name
        self.address = f'{name}@mailto.plus'

    def check(self) -> str | None:
        """Return OTP code if found in inbox, else None."""
        data = _get(
            f'https://tempmail.plus/api/mails'
            f'?email={_urlreq.quote(self.address)}&limit=20&epin='
        )
        for m in data.get('mail_list', []):
            subj = m.get('subject', '')
            code = _extract_code(subj)
            if code:
                return code
            # fetch full body
            try:
                mid = m['mail_id']
                detail = _get(
                    f'https://tempmail.plus/api/mails/{mid}'
                    f'?email={_urlreq.quote(self.address)}&epin='
                )
                for part in (detail.get('subject', ''),
                             detail.get('text', ''),
                             _re.sub(r'<[^>]+>', ' ', detail.get('html', '') or '')):
                    code = _extract_code(part)
                    if code:
                        return code
            except Exception:
                pass
        return None


# ---------------------------------------------------------------------------
# Provider 2: Guerrilla Mail — grr.la (fallback)
# ---------------------------------------------------------------------------

class GrrlInbox:
    """No-registration temp inbox at grr.la."""

    def __init__(self, name: str):
        self.name = name
        self.address = f'{name}@grr.la'
        self.sid = None
        self._init()

    def _init(self):
        try:
            d = _get(
                f'https://api.guerrillamail.com/ajax.php'
                f'?f=set_email_user&email_user={self.name}&lang=en&site=grr.la'
            )
            self.sid = d.get('sid_token', '')
        except Exception:
            pass

    def check(self) -> str | None:
        if not self.sid:
            return None
        try:
            data = _get(
                f'https://api.guerrillamail.com/ajax.php'
                f'?f=get_email_list&offset=0&sid_token={self.sid}&seq=0'
            )
            lst = data.get('list', [])
            if not isinstance(lst, list):
                return None
            for m in lst:
                subj = m.get('mail_subject', '')
                code = _extract_code(subj)
                if code:
                    return code
                # fetch full body
                try:
                    mid = m.get('mail_id', '')
                    detail = _get(
                        f'https://api.guerrillamail.com/ajax.php'
                        f'?f=fetch_email&email_id={mid}&sid_token={self.sid}'
                    )
                    for part in (detail.get('mail_subject', ''),
                                 detail.get('mail_body', ''),
                                 detail.get('mail_text_only', '')):
                        code = _extract_code(_re.sub(r'<[^>]+>', ' ', part or ''))
                        if code:
                            return code
                except Exception:
                    pass
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Main function (called by web_app.py and main.py)
# ---------------------------------------------------------------------------

async def change_email_for_number(phone, raw_phone, api_id, api_hash,
                                   sessions_dir, data_file, mail_user=None,
                                   log=None, max_wait_attempts=36, sleep_secs=5):
    """Auto-changes a Telegram account's login email.

    Tries mailto.plus first, falls back to grr.la.
    Returns: {'success': bool, 'message': str, 'email': str|None}
    """

    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    # Build email address: last-7-digits + random@mailto.plus
    digits = ''.join(c for c in raw_phone if c.isdigit())
    suffix = digits[-7:] if len(digits) >= 7 else digits
    rand   = uuid.uuid4().hex[:5]
    name   = f'{suffix}{rand}'

    # Try provider 1, fall back to provider 2
    inbox = None
    address = None
    for provider_cls, label in [(MailtoPlusInbox, 'mailto.plus'),
                                 (GrrlInbox,       'grr.la')]:
        try:
            _log(f'🌐 Setting up inbox at {label}…')
            obj = await asyncio.to_thread(provider_cls, name)
            # quick sanity — address attribute must exist
            _ = obj.address
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

    session_path = os.path.join(sessions_dir, phone)
    client = TelegramClient(session_path, api_id, api_hash)
    resent_once = False

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {'success': False, 'message': 'Session not authorized',
                    'email': address}

        async def _send_code():
            await client(functions.account.SendVerifyEmailCodeRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                email=address
            ))

        _log(f'📤 Sending OTP to {address}')
        try:
            await _send_code()
        except Exception as e:
            return {'success': False, 'message': f'OTP send failed: {e}',
                    'email': address}

        _log('⏳ OTP sent! Scanning inbox…')
        otp_code = None

        for attempt in range(max_wait_attempts):
            await asyncio.sleep(sleep_secs)
            _log(f'🔍 Checking inbox… ({attempt + 1}/{max_wait_attempts})')

            # Midway resend if still nothing
            if not resent_once and attempt >= max_wait_attempts // 2:
                resent_once = True
                _log('📭 Halfway — resending verification email…')
                try:
                    await _send_code()
                except Exception as e:
                    _log(f'⚠️ Resend failed: {e}')

            try:
                otp_code = await asyncio.to_thread(inbox.check)
            except Exception as e:
                _log(f'⚠️ Inbox check error: {e}')

            if otp_code:
                _log(f'✅ OTP found: {otp_code}')
                break
            else:
                _log(f'📬 No code yet…')

        if not otp_code:
            return {
                'success': False,
                'message': (f'OTP not received within '
                            f'{max_wait_attempts * sleep_secs}s. '
                            f'Try manual method.'),
                'email': address
            }

        _log('🔐 Verifying with Telegram…')
        try:
            await client(functions.account.VerifyEmailRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                verification=types.EmailVerificationCode(code=otp_code)
            ))
        except Exception as e:
            return {'success': False, 'message': f'Verification failed: {e}',
                    'email': address}

        # Persist email_changed flag
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
        if client.is_connected():
            await client.disconnect()
