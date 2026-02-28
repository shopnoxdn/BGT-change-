# TG-Lion Project

## Project Overview
This project is a Telegram Bot and Web Dashboard for account trading and balance management.

### Features
- Sell Telegram accounts with admin approval.
- Buy accounts (work in progress).
- Balance management and withdrawals.
- Referral system.
- Web dashboard with real Telegram OTP login.
- Admin panel to manage users and processing numbers.

## Web App Login Update (Feb 2026)
- Implemented real Telegram OTP login for the web dashboard.
- Users must now provide their History ID followed by their Telegram phone number.
- The system connects to Telegram via Telethon, sends a real OTP, and creates a session upon successful verification.
- This ensures that only the actual owner of the Telegram account can access the dashboard.
- Added `telethon` and `flask[async]` dependencies.
- Created `sessions/` directory to store Telethon session files.
