# replit.md

## Overview

This project appears to be a Telegram bot-based marketplace platform where users can buy and sell accounts (likely phone number-based accounts). The system tracks user balances in USDT, manages account transactions, supports a referral program, and handles withdrawals. Currently, all user data is stored in a JSON file (`user_data.json`), indicating this is an early-stage or lightweight application.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Data Model
The core entity is a user (identified by what appears to be a Telegram user ID) with the following properties:
- **Balance system**: Three-tier balance structure — `main_balance_usdt` (available funds), `hold_balance_usdt` (funds held during pending transactions), and `topup_balance_usdt` (funds from top-ups, possibly with different withdrawal rules)
- **Transaction tracking**: Counts of accounts bought and sold, plus a list of sold phone numbers
- **Referral system**: Each user can have a `referrer_id`, a list of `referrals` they've brought in, and tracked `referral_earnings`
- **Withdrawal processing**: A separate `withdrawal_processing_balance` field tracks funds currently being withdrawn
- **Activity tracking**: `created_at` and `last_activity` timestamps

### Data Storage
- **Current approach**: Flat JSON file (`user_data.json`) storing all user data
- **Problem**: JSON file storage doesn't scale, has no concurrency protection, and risks data corruption
- **Recommendation**: When building out this project, migrate to a proper database (PostgreSQL with Drizzle ORM would be appropriate). The data model maps naturally to relational tables: a `users` table, a `sold_accounts` table (for the sold numbers array), and a `referrals` table

### Application Logic
The bot likely handles these core flows:
1. **Account selling** — Users submit phone numbers/accounts to sell, receive USDT credit
2. **Account buying** — Users spend USDT balance to purchase accounts
3. **Balance management** — Top-ups, withdrawals, and hold mechanics for pending transactions
4. **Referral program** — Users earn a percentage (appears to be around 1-5% based on the data) when their referrals make transactions
5. **Withdrawal processing** — Funds move from main balance to withdrawal processing state

### Key Design Decisions
- **USDT as currency**: All balances are denominated in USDT, suggesting a crypto-adjacent marketplace
- **Hold balance pattern**: The hold system suggests transactions go through a verification/escrow period before funds are fully released
- **Telegram IDs as keys**: Users are identified by Telegram user IDs (numeric strings), meaning the bot is the primary interface

## External Dependencies

### Expected Integrations
- **Telegram Bot API**: The user IDs suggest this is a Telegram bot (likely using a Python library like `python-telegram-bot` or `aiogram`)
- **Payment/Crypto processing**: USDT balances and withdrawal processing suggest integration with a crypto payment gateway or manual payment handling
- **No database yet**: Currently using JSON file storage; should be migrated to PostgreSQL when scaling

### Likely Technology Stack
- **Language**: Python (common for Telegram bots with JSON data storage patterns)
- **Bot framework**: Likely `aiogram` or `python-telegram-bot`
- **Data storage**: JSON file (to be replaced with a database)

### Future Database Schema (Recommended)
When migrating to a proper database:
- `users` table: id, telegram_id, main_balance, hold_balance, topup_balance, withdrawal_processing_balance, accounts_bought, accounts_sold, referrer_id, referral_earnings, created_at, last_activity
- `sold_numbers` table: id, user_id (FK), phone_number, sold_at
- `referrals` table: referrer_id (FK), referred_id (FK), created_at