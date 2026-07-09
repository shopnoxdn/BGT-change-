"""Shared logic for auto-changing a Telegram account's login email via mail.tm.

Used by both the Flask admin dashboard (web_app.py) and the Telegram bot
(main.py) so the OTP-detection logic only needs to be correct in one place.
"""
import os
import json
import time
import uuid
import asyncio
import re as _re
import urllib.request as _urlreq
from telethon import TelegramClient, functions, types


def _mailtm_request(method, path, data=None, token=None, retries=4):
    """mail.tm occasionally returns transient 500s; retry with backoff before failing."""
    url = 'https://api.mail.tm' + path
    body = json.dumps(data).encode() if data else None
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'User-Agent': 'Mozilla/5.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    last_err = None
    for attempt in range(retries):
        try:
            req = _urlreq.Request(url, data=body, headers=headers, method=method)
            with _urlreq.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_err


def _extract_code(text):
    """Language-independent code extraction: a standalone 5-6 digit run."""
    if not text:
        return None
    match = _re.search(r'(?<!\d)(\d{5,6})(?!\d)', text)
    return match.group(1) if match else None


async def change_email_for_number(phone, raw_phone, api_id, api_hash,
                                    sessions_dir, data_file, mail_user=None,
                                    log=None, max_wait_attempts=36, sleep_secs=5):
    """Auto-changes a Telegram account's login email using a fresh mail.tm mailbox.

    Returns a dict: {'success': bool, 'message': str, 'email': str|None}
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    if mail_user is None:
        digits_only = ''.join(c for c in raw_phone if c.isdigit())
        mail_user = digits_only[-7:] if len(digits_only) >= 7 else digits_only

    domain = None
    last_domain_err = None
    for domain_attempt in range(3):
        try:
            _log('🌐 Getting available domains from mail.tm…' if domain_attempt == 0
                 else f'🔁 Retrying domain fetch (attempt {domain_attempt + 1}/3)…')
            domains_resp = await asyncio.to_thread(_mailtm_request, 'GET', '/domains')
            if isinstance(domains_resp, list):
                domain = domains_resp[0]['domain']
            else:
                domain = domains_resp['hydra:member'][0]['domain']
            _log(f'✅ Domain: {domain}')
            break
        except Exception as e:
            last_domain_err = e
            if domain_attempt < 2:
                await asyncio.sleep(3)
    if not domain:
        return {'success': False, 'message': f'mail.tm domain fetch failed: {last_domain_err}', 'email': None}

    rand_suffix = uuid.uuid4().hex[:6]
    address = f'{mail_user}{rand_suffix}@{domain}'
    password = uuid.uuid4().hex

    try:
        _log(f'📧 Creating mailbox: {address}')
        await asyncio.to_thread(_mailtm_request, 'POST', '/accounts',
                                 {'address': address, 'password': password})
    except Exception as e:
        return {'success': False, 'message': f'Mailbox create failed: {e}', 'email': address}

    try:
        _log('🔑 Getting inbox token…')
        tok_resp = await asyncio.to_thread(_mailtm_request, 'POST', '/token',
                                            {'address': address, 'password': password})
        inbox_token = tok_resp['token']
    except Exception as e:
        return {'success': False, 'message': f'Token fetch failed: {e}', 'email': address}

    session_path = os.path.join(sessions_dir, phone)
    client = TelegramClient(session_path, api_id, api_hash)
    resent_once = False
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {'success': False, 'message': 'Session not authorized', 'email': address}

        async def _send_code():
            await client(functions.account.SendVerifyEmailCodeRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                email=address
            ))

        _log(f'📤 Sending OTP to {address}')
        try:
            await _send_code()
        except Exception as e:
            return {'success': False, 'message': f'OTP send failed: {e}', 'email': address}

        _log('⏳ OTP sent! Scanning inbox…')
        otp_code = None
        for attempt in range(max_wait_attempts):
            await asyncio.sleep(sleep_secs)
            _log(f'🔍 Checking inbox… ({attempt + 1}/{max_wait_attempts})')
            try:
                msgs = await asyncio.to_thread(
                    _mailtm_request, 'GET', '/messages', None, inbox_token)
                items = msgs if isinstance(msgs, list) else msgs.get('hydra:member', [])
                _log(f'📬 {len(items)} message(s) in inbox')

                # If nothing has arrived by the halfway point, the first email send
                # sometimes gets silently dropped — resend once and keep waiting.
                if not items and not resent_once and attempt >= max_wait_attempts // 2:
                    resent_once = True
                    _log('📭 No mail yet halfway through — resending verification email…')
                    try:
                        await _send_code()
                    except Exception as e:
                        _log(f'⚠️ Resend failed: {e}')

                for m in items:
                    mid = m['id']
                    subj = m.get('subject', '') or ''
                    sender_name = (m.get('from', {}) or {}).get('name', '') or ''
                    sender_addr = (m.get('from', {}) or {}).get('address', '') or ''
                    _log(f'📩 From: {sender_name} <{sender_addr}> | {subj}')
                    detail = await asyncio.to_thread(
                        _mailtm_request, 'GET', f'/messages/{mid}', None, inbox_token)
                    subject = detail.get('subject', '')
                    textBody = detail.get('text', '')
                    htmlBody = _re.sub(r'<[^>]+>', ' ', detail.get('html', [''])[0] if detail.get('html') else '')
                    _log(f'📝 Subject: {subject[:80]}')
                    # This mailbox is created solely to receive this one OTP, so any
                    # message that contains a standalone 5-6 digit code is a match —
                    # regardless of language or exact sender wording.
                    for part in (subject, textBody, htmlBody):
                        otp_code = _extract_code(part)
                        if otp_code:
                            break
                    if otp_code:
                        break
            except Exception as exc:
                _log(f'⚠️ Inbox error: {exc}')
            if otp_code:
                break

        if not otp_code:
            return {'success': False,
                    'message': f'OTP not received within {max_wait_attempts * sleep_secs}s. Try manual.',
                    'email': address}

        _log(f'✅ OTP found: {otp_code}')
        _log('🔐 Verifying with Telegram…')
        try:
            await client(functions.account.VerifyEmailRequest(
                purpose=types.EmailVerifyPurposeLoginChange(),
                verification=types.EmailVerificationCode(code=otp_code)
            ))
        except Exception as e:
            return {'success': False, 'message': f'Verification failed: {e}', 'email': address}

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

        _log(f'🎉 Done! Email changed to {address}')
        return {'success': True, 'message': f'Email changed to {address}!', 'email': address}

    except Exception as e:
        return {'success': False, 'message': str(e), 'email': address}
    finally:
        if client.is_connected():
            await client.disconnect()
