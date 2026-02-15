#!/usr/bin/env python3
"""
Telegram Bot for Account Trading and Balance Management
"""

import os
import threading
import logging
import json
import re
import asyncio
from datetime import datetime
from typing import Dict, Any

import importlib

# Dynamic imports to avoid Replit auto-installer detecting 'telegram' package
tg = importlib.import_module("telegram")
tg_ext = importlib.import_module("telegram.ext")
Update = tg.Update
InlineKeyboardButton = tg.InlineKeyboardButton
InlineKeyboardMarkup = tg.InlineKeyboardMarkup
ReplyKeyboardMarkup = tg.ReplyKeyboardMarkup
KeyboardButton = tg.KeyboardButton
Application = tg_ext.Application
CommandHandler = tg_ext.CommandHandler
CallbackQueryHandler = tg_ext.CallbackQueryHandler
ContextTypes = tg_ext.ContextTypes
MessageHandler = tg_ext.MessageHandler
ConversationHandler = tg_ext.ConversationHandler
filters = tg_ext.filters

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# Suppress sensitive logging from HTTP requests
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Verify correct telegram module is loaded
assert hasattr(tg, "Update"), "python-telegram-bot not resolved; ensure 'telegram' package is not installed"
logger.info(f"telegram loaded successfully from python-telegram-bot v{getattr(tg, '__version__', 'n/a')}")

# Simple in-memory data storage (will be replaced with PostgreSQL later)
user_data: Dict[str, Dict[str, Any]] = {}
user_data_lock = threading.Lock()

# Global withdrawal settings
withdrawal_settings: Dict[str, Any] = {
    'global_limit': 1.0,  # Default global minimum withdrawal limit
    'user_limits': {},  # Custom limits per user: {user_id: limit}
    'bot_active': True  # Bot status (active by default)
}

# Per-method minimum withdrawal limits
METHOD_WITHDRAWAL_LIMITS: Dict[str, float] = {
    'bank': 5.0,
    'paypal': 2.0,
    'upi': 0.2,
    'cashapp': 1000.0,
    'bitcoin': 100.0,
    'bep20': 20.0,
    'trc20': 70.0,
    'binance': 25.0,
    'payeer': 30.0
}

def get_method_withdrawal_limit(method: str) -> float:
    """Get the minimum withdrawal limit for a specific payment method"""
    return METHOD_WITHDRAWAL_LIMITS.get(method, 1.0)

def get_combined_withdrawal_limit(user_id: str, user_balance: float, method: str) -> float:
    """Get the combined withdrawal limit considering both method and user-specific limits"""
    method_limit = get_method_withdrawal_limit(method)
    user_limit = get_user_withdrawal_limit(user_id, user_balance)
    return max(method_limit, user_limit)

def get_user_withdrawal_limit(user_id: str, user_balance: float) -> float:
    """Get the withdrawal limit for a user based on their balance and settings"""
    # Check if user has a custom limit set
    if user_id in withdrawal_settings['user_limits']:
        return withdrawal_settings['user_limits'][user_id]
    
    # If user balance is exactly $1 (or very close), return $3
    if abs(user_balance - 1.0) < 0.01:
        return 3.0
    
    # Otherwise return global limit
    return withdrawal_settings['global_limit']

def load_countries_data():
    """Initialize country data from file or memory"""
    global COUNTRIES_DATA
    try:
        if os.path.exists('countries_data.json'):
            with open('countries_data.json', 'r') as f:
                data = json.load(f)
                if data:
                    COUNTRIES_DATA.update(data)
            logger.info("Loaded country data from file")
        else:
            # COUNTRIES_DATA is already initialized with hardcoded values
            logger.info("Using hardcoded country data")
    except Exception as e:
        logger.error(f"Error loading country data: {e}")

def save_countries_data():
    """Save country data to file"""
    try:
        with open('countries_data.json', 'w') as f:
            json.dump(COUNTRIES_DATA, f, indent=4)
        logger.info("Saved country data to file")
    except Exception as e:
        logger.error(f"Error saving country data: {e}")

def load_withdrawal_settings():
    """Initialize withdrawal settings from file or memory"""
    global withdrawal_settings
    try:
        if os.path.exists('withdrawal_settings.json'):
            with open('withdrawal_settings.json', 'r') as f:
                withdrawal_settings = json.load(f)
            logger.info("Loaded withdrawal settings from file")
        else:
            withdrawal_settings = {'global_limit': 1.0, 'user_limits': {}}
            logger.info("Initialized withdrawal settings in memory")
    except Exception as e:
        logger.error(f"Error loading withdrawal settings: {e}")
        withdrawal_settings = {'global_limit': 1.0, 'user_limits': {}}

def save_withdrawal_settings():
    """Save withdrawal settings to file"""
    try:
        with open('withdrawal_settings.json', 'w') as f:
            json.dump(withdrawal_settings, f, indent=4)
        logger.info("Saved withdrawal settings to file")
    except Exception as e:
        logger.error(f"Error saving withdrawal settings: {e}")

# Conversation states for sell account flow
WAITING_FOR_NUMBER, WAITING_FOR_ADMIN_APPROVAL, WAITING_FOR_PIN = range(3)

# Admin settings - hardcoded for portability
ADMIN_CHAT_ID = "5810613583"
ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID)

# Admin conversation states  
WAITING_FOR_USER_ID, WAITING_FOR_AMOUNT = range(3, 5)

# Country data with user-specified countries and separate buy/sell prices (updated from uploaded file)
COUNTRIES_DATA = {
    'italy': {'name': 'Italy 🇮🇹', 'sell_price': 2.9, 'buy_price': 3.77},
    'mexico': {'name': 'Mexico 🇲🇽', 'sell_price': 0.70, 'buy_price': 0.91},
    'kazakhstan': {'name': 'Kazakhstan 🇰🇿', 'sell_price': 1.0, 'buy_price': 1.3},
    'russia': {'name': 'Russia 🇷🇺', 'sell_price': 1.3, 'buy_price': 1.69},
    'ukraine': {'name': 'Ukraine 🇺🇦', 'sell_price': 1.0, 'buy_price': 1.3},
    'yemen': {'name': 'Yemen 🇾🇪', 'sell_price': 0.60, 'buy_price': 0.78},
    'latvia': {'name': 'Latvia 🇱🇻', 'sell_price': 0.50, 'buy_price': 0.65},
    'sierra_leone': {'name': 'Sierra Leone 🇸🇱', 'sell_price': 0.45, 'buy_price': 0.59},
    'kyrgyzstan': {'name': 'Kyrgyzstan 🇰🇬', 'sell_price': 1.0, 'buy_price': 1.3},
    'usa': {'name': 'United States 🇺🇸', 'sell_price': 0.22, 'buy_price': 0.29},
    'egypt': {'name': 'Egypt 🇪🇬', 'sell_price': 0.45, 'buy_price': 0.59},
    'iraq': {'name': 'Iraq 🇮🇶', 'sell_price': 0.60, 'buy_price': 0.78},
    'saudi_arabia': {'name': 'Saudi Arabia 🇸🇦', 'sell_price': 2.3, 'buy_price': 2.99},
    'turkey': {'name': 'Turkey 🇹🇷', 'sell_price': 1.0, 'buy_price': 1.3},
    'venezuela': {'name': 'Venezuela 🇻🇪', 'sell_price': 0.50, 'buy_price': 0.65},
    'france': {'name': 'France 🇫🇷', 'sell_price': 1.5, 'buy_price': 1.95},
    'argentina': {'name': 'Argentina 🇦🇷', 'sell_price': 0.60, 'buy_price': 0.78},
    'netherlands': {'name': 'Netherlands 🇳🇱', 'sell_price': 1.0, 'buy_price': 1.3},
    'england': {'name': '🇬🇧 England', 'sell_price': 0.75, 'buy_price': 0.98},
    'uzbekistan': {'name': 'Uzbekistan 🇺🇿', 'sell_price': 0.80, 'buy_price': 1.04},
    'hong_kong': {'name': 'Hong Kong 🇭🇰', 'sell_price': 0.65, 'buy_price': 0.85},
    'thailand': {'name': 'Thailand 🇹🇭', 'sell_price': 0.70, 'buy_price': 0.91},
    'samoa': {'name': 'Samoa 🇼🇸', 'sell_price': 0.70, 'buy_price': 0.91},
    'spain': {'name': 'Spain 🇪🇸', 'sell_price': 1.5, 'buy_price': 1.95},
    'tunisia': {'name': 'Tunisia 🇹🇳', 'sell_price': 0.40, 'buy_price': 0.52},
    'senegal': {'name': 'Senegal 🇸🇳', 'sell_price': 0.50, 'buy_price': 0.65},
    'morocco': {'name': 'Morocco 🇲🇦', 'sell_price': 0.30, 'buy_price': 0.39},
    'india': {'name': 'India 🇮🇳', 'sell_price': 0.35, 'buy_price': 0.46},
    'lebanon': {'name': 'Lebanon 🇱🇧', 'sell_price': 0.70, 'buy_price': 0.91},
    'vietnam': {'name': 'Vietnam 🇻🇳', 'sell_price': 0.35, 'buy_price': 0.46},
    'ghana': {'name': 'Ghana 🇬🇭', 'sell_price': 0.35, 'buy_price': 0.46},
    'iran': {'name': 'Iran 🇮🇷', 'sell_price': 0.70, 'buy_price': 0.91},
    'uae': {'name': 'Uni Emirat Arab 🇦🇪', 'sell_price': 1.0, 'buy_price': 1.3},
    'georgia': {'name': 'Georgia 🇬🇪', 'sell_price': 0.60, 'buy_price': 0.78},
    'mali': {'name': 'Mali 🇲🇱', 'sell_price': 0.44, 'buy_price': 0.57},
    'portugal': {'name': 'Portugal 🇵🇹', 'sell_price': 1.0, 'buy_price': 1.3},
    'babo': {'name': 'Babo 🇵🇬', 'sell_price': 0.60, 'buy_price': 0.78},
    'niger': {'name': 'Niger 🇳🇪', 'sell_price': 0.50, 'buy_price': 0.65},
    'pakistan': {'name': 'Pakistan 🇵🇰', 'sell_price': 0.35, 'buy_price': 0.46},
    'peru': {'name': 'Peru 🇵🇪', 'sell_price': 0.80, 'buy_price': 1.04},
    'afghanistan': {'name': 'Afghanistan 🇦🇫', 'sell_price': 0.55, 'buy_price': 0.72},
    'tanzania': {'name': 'Tanzania 🇹🇿', 'sell_price': 0.37, 'buy_price': 0.48},
    'zimbabwe': {'name': 'Zimbabwe 🇿🇼', 'sell_price': 0.46, 'buy_price': 0.60},
    'guatemala': {'name': 'Guatemala 🇬🇹', 'sell_price': 0.90, 'buy_price': 1.17},
    'sri_lanka': {'name': 'Sri Lanka 🇱🇰', 'sell_price': 0.50, 'buy_price': 0.65},
    'jordan': {'name': 'Jordan 🇯🇴', 'sell_price': 1.0, 'buy_price': 1.3},
    'syria': {'name': 'Syria 🇸🇾', 'sell_price': 0.65, 'buy_price': 0.85},
    'indonesia': {'name': 'Indonesia 🇮🇩', 'sell_price': 0.35, 'buy_price': 0.46},
    'cambodia': {'name': 'Cambodia 🇰🇭', 'sell_price': 0.40, 'buy_price': 0.52},
    'sudan': {'name': 'Sudan 🇸🇩', 'sell_price': 0.55, 'buy_price': 0.72},
    'puerto_rico': {'name': 'Puerto Rico 🇵🇷', 'sell_price': 0.45, 'buy_price': 0.59},
    'timor': {'name': 'Timor 🇹🇱', 'sell_price': 0.50, 'buy_price': 0.65},
    'taiwan': {'name': 'Taiwan 🇹🇼', 'sell_price': 1.0, 'buy_price': 1.3},
    'sweden': {'name': 'Sweden 🇸🇪', 'sell_price': 0.80, 'buy_price': 1.04},
    'estonia': {'name': 'Estonia 🇪🇪', 'sell_price': 0.85, 'buy_price': 1.11},
    'laos': {'name': 'Laos 🇱🇦', 'sell_price': 0.70, 'buy_price': 0.91},
    'nigeria': {'name': 'Nigeria 🇳🇬', 'sell_price': 0.25, 'buy_price': 0.33},
    'israel': {'name': 'Israel 🇮🇱', 'sell_price': 0.75, 'buy_price': 0.98},
    'china': {'name': 'China 🇨🇳', 'sell_price': 0.80, 'buy_price': 1.04},
    'philippines': {'name': 'Philippines 🇵🇭', 'sell_price': 0.50, 'buy_price': 0.65},
    'malaysia': {'name': 'Malaysia 🇲🇾', 'sell_price': 1.45, 'buy_price': 1.89},
    'madagascar': {'name': 'Madagascar 🇲🇬', 'sell_price': 0.47, 'buy_price': 0.61},
    'ireland': {'name': 'Ireland 🇮🇪', 'sell_price': 0.55, 'buy_price': 0.72},
    'austria': {'name': 'Austria 🇦🇹', 'sell_price': 0.70, 'buy_price': 0.91},
    'serbia': {'name': 'Serbia 🇷🇸', 'sell_price': 0.50, 'buy_price': 0.65},
    'romania': {'name': 'Romania 🇷🇴', 'sell_price': 1.0, 'buy_price': 1.3},
    'slovenia': {'name': 'Slovenia 🇸🇮', 'sell_price': 0.60, 'buy_price': 0.78},
    'ethiopia': {'name': 'Ethiopia 🇪🇹', 'sell_price': 0.35, 'buy_price': 0.46},
    'nicaragua': {'name': 'Nicaragua 🇳🇮', 'sell_price': 0.60, 'buy_price': 0.78},
    'paraguay': {'name': 'Paraguay 🇵🇾', 'sell_price': 0.55, 'buy_price': 0.72},
    'hungary': {'name': 'Hungary 🇭🇺', 'sell_price': 0.50, 'buy_price': 0.65},
    'nepal': {'name': 'Nepal 🇳🇵', 'sell_price': 0.24, 'buy_price': 0.31},
    'uganda': {'name': 'Uganda 🇺🇬', 'sell_price': 0.44, 'buy_price': 0.57},
    'mongolia': {'name': 'Mongolia 🇲🇳', 'sell_price': 0.77, 'buy_price': 1.0},
    'belarus': {'name': 'Belarus 🇧🇾', 'sell_price': 0.60, 'buy_price': 0.78},
    'canada': {'name': 'Canada 🇨🇦', 'sell_price': 0.39, 'buy_price': 0.51},
    'colombia': {'name': 'Colombia 🇨🇴', 'sell_price': 0.40, 'buy_price': 0.52},
    'croatia': {'name': 'Croatia 🇭🇷', 'sell_price': 0.50, 'buy_price': 0.65},
    'poland': {'name': 'Poland 🇵🇱', 'sell_price': 0.80, 'buy_price': 1.04},
    'kenya': {'name': 'Kenya 🇰🇪', 'sell_price': 0.35, 'buy_price': 0.46},
    'el_salvador': {'name': 'El Salvador 🇸🇻', 'sell_price': 0.60, 'buy_price': 0.78},
    'myanmar': {'name': 'Myanmar 🇲🇲', 'sell_price': 0.35, 'buy_price': 0.46},
    'libya': {'name': 'Libya 🇱🇾', 'sell_price': 0.80, 'buy_price': 1.04},
    'bolivia': {'name': 'Bolivia 🇧🇴', 'sell_price': 0.30, 'buy_price': 0.39},
    'fiji': {'name': 'Fiji 🇫🇯', 'sell_price': 1.0, 'buy_price': 1.3},
    'tonga': {'name': 'Tonga 🇹🇴', 'sell_price': 0.60, 'buy_price': 0.78},
    'costa_rica': {'name': 'Costa Rica 🇨🇷', 'sell_price': 0.35, 'buy_price': 0.46},
    'honduras': {'name': 'Honduras 🇭🇳', 'sell_price': 0.30, 'buy_price': 0.39},
    'japan': {'name': 'Japan 🇯🇵', 'sell_price': 1.2, 'buy_price': 1.56},
    'norway': {'name': 'Norway 🇳🇴', 'sell_price': 1.2, 'buy_price': 1.56},
    'australia': {'name': 'Australia 🇦🇺', 'sell_price': 0.5, 'buy_price': 0.65},
    'switzerland': {'name': 'Switzerland 🇨🇭', 'sell_price': 1.0, 'buy_price': 1.3},
    'denmark': {'name': 'Denmark 🇩🇰', 'sell_price': 1.2, 'buy_price': 1.56},
    'chile': {'name': 'Chile 🇨🇱', 'sell_price': 0.50, 'buy_price': 0.65},
    'benin': {'name': 'Benin 🇧🇯', 'sell_price': 0.30, 'buy_price': 0.39},
    'burundi': {'name': 'Burundi 🇧🇮', 'sell_price': 0.40, 'buy_price': 0.52},
    'cuba': {'name': 'Cuba 🇨🇺', 'sell_price': 0.65, 'buy_price': 0.85},
    'panama': {'name': 'Panama 🇵🇦', 'sell_price': 0.40, 'buy_price': 0.52},
    'qatar': {'name': 'Qatar 🇶🇦', 'sell_price': 1.6, 'buy_price': 2.08},
    'oman': {'name': 'Oman 🇴🇲', 'sell_price': 1.4, 'buy_price': 1.82},
    'kuwait': {'name': 'Kuwait 🇰🇼', 'sell_price': 2.2, 'buy_price': 2.86},
    'togo': {'name': 'Togo 🇹🇬', 'sell_price': 0.45, 'buy_price': 0.59},
    'armenia': {'name': 'Armenia 🇦🇲', 'sell_price': 0.60, 'buy_price': 0.78},
    'bangladesh': {'name': 'Bangladesh 🇧🇩', 'sell_price': 0.65, 'buy_price': 0.85},
    'mozambique': {'name': 'Mozambique 🇲🇿', 'sell_price': 0.40, 'buy_price': 0.52},
    'angola': {'name': 'Angola 🇦🇴', 'sell_price': 0.35, 'buy_price': 0.46},
    'chad': {'name': 'Chad 🇹🇩', 'sell_price': 0.40, 'buy_price': 0.52},
    'algeria': {'name': 'Algeria 🇩🇿', 'sell_price': 0.40, 'buy_price': 0.52},
    'guinea': {'name': 'Guinea 🇬🇳', 'sell_price': 0.30, 'buy_price': 0.39},
    'singapore': {'name': 'Singapore 🇸🇬', 'sell_price': 1.2, 'buy_price': 1.56},
    'malta': {'name': 'Malta 🇲🇹', 'sell_price': 1.5, 'buy_price': 1.95},
    'turkmenistan': {'name': 'Turkmenistan 🇹🇲', 'sell_price': 0.75, 'buy_price': 0.98},
    'bermuda': {'name': 'Bermuda 🇧🇲', 'sell_price': 0.60, 'buy_price': 0.78},
    'bahrain': {'name': 'Bahrain 🇧🇭', 'sell_price': 1.3, 'buy_price': 1.69},
    'germany': {'name': 'Germany 🇩🇪', 'sell_price': 2.0, 'buy_price': 2.6},
    'brazil': {'name': 'Brazil 🇧🇷', 'sell_price': 1.0, 'buy_price': 1.3},
    'maldives': {'name': 'Maldives 🇲🇻', 'sell_price': 1.0, 'buy_price': 1.3},
    'czech_republic': {'name': 'Czech Republic 🇨🇿', 'sell_price': 0.85, 'buy_price': 1.11},
    'moldova': {'name': 'Moldova 🇲🇩', 'sell_price': 0.70, 'buy_price': 0.91},
    'belgium': {'name': 'Belgium 🇧🇪', 'sell_price': 1.0, 'buy_price': 1.3},
    'new_zealand': {'name': 'New Zealand 🇳🇿', 'sell_price': 0.60, 'buy_price': 0.78},
    'cameroon': {'name': 'Cameroon 🇨🇲', 'sell_price': 0.35, 'buy_price': 0.46},
    'macau': {'name': 'Macau 🇲🇴', 'sell_price': 0.80, 'buy_price': 1.04},
    'solomon_islands': {'name': 'Solomon Islands 🇸🇧', 'sell_price': 0.80, 'buy_price': 1.04},
    'aruba': {'name': 'Aruba 🇦🇼', 'sell_price': 1.2, 'buy_price': 1.56},
    'djibouti': {'name': 'Djibouti 🇩🇯', 'sell_price': 0.60, 'buy_price': 0.78},
    'albania': {'name': 'Albania 🇦🇱', 'sell_price': 1.0, 'buy_price': 1.3},
    'monaco': {'name': 'Monaco 🇲🇨', 'sell_price': 1.5, 'buy_price': 1.95},
    'comoros': {'name': 'Comoros 🇰🇲', 'sell_price': 0.65, 'buy_price': 0.85},
    'iceland': {'name': 'Iceland 🇮🇸', 'sell_price': 0.65, 'buy_price': 0.85},
    'bosnia': {'name': 'Bosnia 🇧🇦', 'sell_price': 0.65, 'buy_price': 0.85},
    'dominican': {'name': 'Dominican 🇩🇴', 'sell_price': 0.50, 'buy_price': 0.65},
    'ecuador': {'name': 'Ecuador 🇪🇨', 'sell_price': 0.60, 'buy_price': 0.78},
    'trinidad': {'name': 'Trinidad 🇹🇹', 'sell_price': 0.55, 'buy_price': 0.72},
    'jamaica': {'name': 'Jamaica 🇯🇲', 'sell_price': 0.60, 'buy_price': 0.78},
    'haiti': {'name': 'Haiti 🇭🇹', 'sell_price': 0.60, 'buy_price': 0.78},
    'azerbaijan': {'name': 'Azerbaijan 🇦🇿', 'sell_price': 0.85, 'buy_price': 1.11},
    'bulgaria': {'name': 'Bulgaria 🇧🇬', 'sell_price': 0.65, 'buy_price': 0.85},
    'luxembourg': {'name': 'Luxembourg 🇱🇺', 'sell_price': 0.65, 'buy_price': 0.85},
    'swaziland': {'name': 'Swaziland 🇸🇿', 'sell_price': 0.45, 'buy_price': 0.59},
    'cape_verde': {'name': 'Cape Verde 🇨🇻', 'sell_price': 1.0, 'buy_price': 1.3},
    'seychelles': {'name': 'Seychelles 🇸🇨', 'sell_price': 0.80, 'buy_price': 1.04},
    'uruguay': {'name': 'Uruguay 🇺🇾', 'sell_price': 0.55, 'buy_price': 0.72},
    'grenada': {'name': 'Grenada 🇬🇩', 'sell_price': 0.60, 'buy_price': 0.78},
    'ivory_coast': {'name': 'Ivory Coast 🇨🇮', 'sell_price': 0.55, 'buy_price': 0.72},
    'anguilla': {'name': 'Anguilla 🇦🇮', 'sell_price': 0.80, 'buy_price': 1.04},
    'cayman_islands': {'name': 'Cayman Islands 🇰🇾', 'sell_price': 0.80, 'buy_price': 1.04},
    'grenadines': {'name': 'Grenadines 🇻🇨', 'sell_price': 1.0, 'buy_price': 1.3},
    'lucia': {'name': 'Lucia 🇱🇨', 'sell_price': 1.0, 'buy_price': 1.3},
    'principe': {'name': 'Príncipe 🇸🇹', 'sell_price': 1.0, 'buy_price': 1.3},
    'guadeloupe': {'name': 'Guadeloupe 🇬🇵', 'sell_price': 1.0, 'buy_price': 1.3},
    'mauritius': {'name': 'Mauritius 🇲🇺', 'sell_price': 1.0, 'buy_price': 1.3},
    'suriname': {'name': 'Suriname 🇸🇷', 'sell_price': 0.80, 'buy_price': 1.04},
    'lesotho': {'name': 'Lesotho 🇱🇸', 'sell_price': 0.65, 'buy_price': 0.85},
    'guyana': {'name': 'Guyana 🇬🇾', 'sell_price': 0.60, 'buy_price': 0.78},
    'botswana': {'name': 'Botswana 🇧🇼', 'sell_price': 0.50, 'buy_price': 0.65},
    'dominica': {'name': 'Dominica 🇩🇲', 'sell_price': 0.60, 'buy_price': 0.78},
    'namibia': {'name': 'Namibia 🇳🇦', 'sell_price': 0.50, 'buy_price': 0.65},
    'barbados': {'name': 'Barbados 🇧🇧', 'sell_price': 0.60, 'buy_price': 0.78},
    'belize': {'name': 'Belize 🇧🇿', 'sell_price': 0.80, 'buy_price': 1.04},
    'gabon': {'name': 'Gabon 🇬🇦', 'sell_price': 0.60, 'buy_price': 0.78},
    'south_africa': {'name': 'South Africa 🇿🇦', 'sell_price': 0.30, 'buy_price': 0.39},
    'bhutan': {'name': 'Bhutan 🇧🇹', 'sell_price': 1.0, 'buy_price': 1.3},
    'palestine': {'name': 'Palestine 🇵🇸', 'sell_price': 0.70, 'buy_price': 0.91},
    'congo': {'name': 'Congo 🇨🇬', 'sell_price': 0.40, 'buy_price': 0.52},
    'central_africa': {'name': 'Central Africa 🇨🇫', 'sell_price': 0.30, 'buy_price': 0.39},
    'zambia': {'name': 'Zambia 🇿🇲', 'sell_price': 0.45, 'buy_price': 0.59},
    'malawi': {'name': 'Malawi 🇲🇼', 'sell_price': 0.50, 'buy_price': 0.65}
}

def load_user_data():
    """Initialize user data from file or memory"""
    global user_data
    try:
        if os.path.exists('user_data.json'):
            with open('user_data.json', 'r') as f:
                user_data = json.load(f)
            logger.info("Loaded user data from file")
        else:
            user_data = {}
            logger.info("Initialized user data in memory")
    except Exception as e:
        logger.error(f"Error loading user data: {e}")
        user_data = {}

def save_user_data():
    """Save user data to file"""
    try:
        with open('user_data.json', 'w') as f:
            json.dump(user_data, f, indent=4)
        logger.info("Saved user data to file")
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Get user data, create if doesn't exist with thread safety"""
    with user_data_lock:
        data_changed = False
        
        if user_id not in user_data:
            user_data[user_id] = {
                'main_balance_usdt': 0.0,
                'hold_balance_usdt': 0.0,
                'topup_balance_usdt': 0.0,
                'accounts_bought': 0,
                'accounts_sold': 0,
                'sold_numbers': [], # List of numbers sold by this user
                'referrer_id': None,
                'referrals': [],
                'referral_earnings': 0.0,
                'created_at': datetime.now().isoformat(),
                'last_activity': datetime.now().isoformat()
            }
            data_changed = True

    # Add referral fields if missing
    if 'referrer_id' not in user_data[user_id]:
        user_data[user_id]['referrer_id'] = None
        data_changed = True
    if 'referrals' not in user_data[user_id]:
        user_data[user_id]['referrals'] = []
        data_changed = True
    if 'referral_earnings' not in user_data[user_id]:
        user_data[user_id]['referral_earnings'] = 0.0
        data_changed = True

    # Initialize processing_details if missing
    if 'processing_details' not in user_data[user_id]:
        user_data[user_id]['processing_details'] = []
        data_changed = True

    # Migrate old data if needed
    if 'balance_usdt' in user_data[user_id] and 'main_balance_usdt' not in user_data[user_id]:
        user_data[user_id]['main_balance_usdt'] = user_data[user_id].pop('balance_usdt', 0.0)
        user_data[user_id]['hold_balance_usdt'] = 0.0
        data_changed = True

        # Add topup_balance_usdt if missing
        if 'topup_balance_usdt' not in user_data[user_id]:
            user_data[user_id]['topup_balance_usdt'] = 0.0
            data_changed = True

    # Add withdrawal_processing_balance if missing
    if 'withdrawal_processing_balance' not in user_data[user_id]:
        user_data[user_id]['withdrawal_processing_balance'] = 0.0
        data_changed = True

    # Update last activity
    user_data[user_id]['last_activity'] = datetime.now().isoformat()
    
    # Create a copy to return
    result = user_data[user_id].copy()
    
    # Only save if data actually changed (outside the lock)
    if data_changed:
        save_user_data()
    
    return result

def create_main_menu():
    """Create the main menu inline keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("💸 Sell Account", callback_data="sell_account"),
            InlineKeyboardButton("🏦 Withdrawal", callback_data="withdrawal")
        ],
        [
            InlineKeyboardButton("💰 Balance", callback_data="balance"),
            InlineKeyboardButton("ℹ️ Safety & Terms", callback_data="terms")
        ],
        [
            InlineKeyboardButton("👥 Refer & Earn", callback_data="refer"),
            InlineKeyboardButton("📜 My History", callback_data="my_history")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_reply_keyboard():
    """Create the main menu reply keyboard"""
    keyboard = [
        [
            KeyboardButton("💸 Sell Account"),
            KeyboardButton("🏦 Withdrawal")
        ],
        [
            KeyboardButton("💰 Balance"),
            KeyboardButton("ℹ️ Safety & Terms")
        ],
        [
            KeyboardButton("👥 Refer & Earn"),
            KeyboardButton("📜 My History")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def check_bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if bot is active, if not notify user and return False"""
    if str(update.effective_user.id) == ADMIN_CHAT_ID:
        return True
        
    if not withdrawal_settings.get('bot_active', True):
        off_text = """
🛑 **Bot is Currently Offline**
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

🛠️ **Maintenance in Progress**
Our engineers are currently working on improving the system to provide you with a better experience. 🚀

💎 **Professional Services**
All pending transactions are safe and will be processed once we are back online.

📅 **We'll be back soon!**
Thank you for your patience and for choosing our professional trading platform. ✨
"""
        if update.callback_query:
            await update.callback_query.answer("⚠️ Bot is Offline", show_alert=True)
            await update.callback_query.message.reply_text(off_text, parse_mode='Markdown')
        elif update.message:
            await update.message.reply_text(off_text, parse_mode='Markdown')
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    if not await check_bot_status(update, context):
        return
    user = update.effective_user
    user_id = str(user.id)
    
    # Add broadcast pick up
    if os.path.exists('broadcast_queue.json'):
        try:
            with open('broadcast_queue.json', 'r') as f:
                broadcast = json.load(f)
            
            # Simple broadcast to all known users in user_data
            message = broadcast.get('message')
            if message:
                count = 0
                for uid in list(user_data.keys()):
                    try:
                        await context.bot.send_message(chat_id=int(uid), text=f"📢 **Notification**\n\n{message}", parse_mode='Markdown')
                        count += 1
                        await asyncio.sleep(0.05) # Small delay to avoid flood
                    except Exception:
                        pass
                logger.info(f"Broadcasted message to {count} users")
            
            os.remove('broadcast_queue.json')
        except Exception as e:
            logger.error(f"Error in broadcast: {e}")
    
    # Check for referral parameter
    referrer_id = None
    if update.message and update.message.text:
        parts = update.message.text.split()
        if len(parts) > 1 and parts[1].startswith('ref_'):
            referrer_id = parts[1].replace('ref_', '')
    
    # Initialize user data
    user_info = get_user_data(user_id)
    
    # Process referral if this is a new user with a referrer
    if referrer_id and referrer_id != user_id:
        with user_data_lock:
            # Check if user doesn't already have a referrer
            if user_id in user_data and user_data[user_id].get('referrer_id') is None:
                # Verify referrer exists
                if referrer_id in user_data:
                    # Set referrer for this user
                    user_data[user_id]['referrer_id'] = referrer_id
                    
                    # Add this user to referrer's referrals list
                    if user_id not in user_data[referrer_id]['referrals']:
                        user_data[referrer_id]['referrals'].append(user_id)
                        
                        # Give $0.04 bonus to referrer
                        user_data[referrer_id]['main_balance_usdt'] += 0.04
                        user_data[referrer_id]['referral_earnings'] += 0.04
                        
                        logger.info(f"Referral bonus: User {user_id} referred by {referrer_id}, bonus $0.04 added")
                        
                        # Notify referrer about new referral
                        try:
                            asyncio.create_task(context.bot.send_message(
                                chat_id=referrer_id,
                                text=f"🎉 **New Referral!**\n\nA new user joined using your referral link!\n💰 You earned $0.04 bonus!",
                                parse_mode='Markdown'
                            ))
                        except Exception as e:
                            logger.error(f"Failed to notify referrer {referrer_id}: {e}")
        save_user_data()

    welcome_text = f"""
🌟 **WELCOME TO BGT WALLET** 🌟
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
Hello {user.first_name}! 👋 

Manage your digital assets and account sales with professional speed and security.

💰 **Main Balance:** {user_info['main_balance_usdt']:.2f} USDT
⏳ **Hold Balance:** {user_info['hold_balance_usdt']:.2f} USDT

🚀 Select an option below to get started:
"""
    
    inline_markup = create_main_menu()
    reply_markup = create_reply_keyboard()

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=inline_markup, parse_mode='Markdown')
        # Also send reply keyboard separately for callback queries
        await update.callback_query.message.reply_text("Main Dashboard Menu:", reply_markup=reply_markup)

async def admin_link_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin link add callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    context.user_data['admin_link_add'] = True
    
    keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🔗 **Add Dashboard Link**\n\nPlease send the link you want to set for the dashboard.\n\nExample: `https://example.com`",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_admin_link_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin link add input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    link = update.message.text.strip()
    
    # Simple URL validation
    if not (link.startswith('http://') or link.startswith('https://')):
        await update.message.reply_text("❌ Invalid link! Please start with http:// or https://")
        return

    try:
        # Save to settings.json
        settings = {}
        if os.path.exists('settings.json'):
            with open('settings.json', 'r') as f:
                settings = json.load(f)
        
        settings['dashboard_link'] = link
        
        with open('settings.json', 'w') as f:
            json.dump(settings, f)
            
        success_text = f"✅ **Dashboard Link Updated!**\n\n🔗 **New Link:** {link}"
        
        keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        # Clear context
        context.user_data.pop('admin_link_add', None)
    except Exception as e:
        logger.error(f"Error saving dashboard link: {e}")
        await update.message.reply_text(f"❌ Error saving link: {str(e)}")

async def my_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle My History button callback"""
    if not await check_bot_status(update, context):
        return
        
    user_id = str(update.effective_user.id)
    # Use part of the user ID and a hash-like string to create a 15-char ID
    import hashlib
    login_id = hashlib.md5(user_id.encode()).hexdigest()[:15].upper()
    
    # Load dashboard link from settings
    dashboard_link = "No link set"
    if os.path.exists('settings.json'):
        try:
            with open('settings.json', 'r') as f:
                settings = json.load(f)
                dashboard_link = settings.get('dashboard_link', "No link set")
        except: pass

    history_text = f"""
📜 **BGT WALLET - ACTIVITY LOG** 📜
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
🆔 **Login ID:** `{login_id}`

This is your unique 15-character identifier for the web dashboard.
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
"""
    keyboard = [
        [InlineKeyboardButton("🌐 Open Dashboard", url=dashboard_link)] if dashboard_link != "No link set" else [],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ]
    # Remove empty sub-lists
    keyboard = [r for r in keyboard if r]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(history_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.effective_message.reply_text(history_text, reply_markup=reply_markup, parse_mode='Markdown')

async def balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle balance button callback"""
    if not await check_bot_status(update, context):
        return
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)

    # Check if user is admin
    is_admin = user_id == ADMIN_CHAT_ID

    balance_text = f"""
🏦 **BGT WALLET - ASSET DETAILS** 🏦
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
⏳ **Hold Balance:** `{user_info['hold_balance_usdt']:.2f} USDT`

💰 **Main Balance:** `{user_info['main_balance_usdt']:.2f} USDT`

⏳ **Withdrawal In-Progress:** `{user_info.get('withdrawal_processing_balance', 0.0):.2f} USDT`

🆔 **User ID:** `{user_id}`
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
"""

    keyboard = []
    if is_admin:
        keyboard.extend([
            [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")],
            [InlineKeyboardButton("💳 Main Balance Control", callback_data="admin_main_balance")],
            [InlineKeyboardButton("⏳ Hold Balance Control", callback_data="admin_hold_balance")]
        ])

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(balance_text, reply_markup=reply_markup, parse_mode='Markdown')

async def refer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle refer button callback"""
    if not await check_bot_status(update, context):
        return
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    
    bot_username = "BGT_Wallet_bot"
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    referral_count = len(user_info.get('referrals', []))
    referral_earnings = user_info.get('referral_earnings', 0.0)
    
    refer_text = f"""
🤝 **BGT WALLET - REFERRAL PROGRAM** 🤝
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
Invite your friends and earn rewards for every successful sale they complete!

🔗 **Your Referral Link:**
`{referral_link}`

👥 **Total Referrals:** `{referral_count}`
💰 **Total Earnings:** `{referral_earnings:.2f} USDT`
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(refer_text, reply_markup=reply_markup, parse_mode='Markdown')

async def buy_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle buy account button callback - show all countries with 30% higher prices"""
    query = update.callback_query
    await query.answer()

    buy_text = """
🛒 **BGT WALLET - ASSET ACQUISITION** 🛒
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
Select a country to browse available digital assets for purchase.

📍 **Select Country:**
"""

    # Get all countries sorted by buy price (descending for better visibility)
    all_countries = list(COUNTRIES_DATA.keys())
    all_countries.sort(key=lambda x: COUNTRIES_DATA[x]['buy_price'], reverse=True)

    # Create keyboard with 2 countries per row using buy_price
    keyboard = []
    for i in range(0, len(all_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(all_countries):
                country_key = all_countries[i + j]
                if country_key in COUNTRIES_DATA:
                    country_data = COUNTRIES_DATA[country_key]
                    # Use the buy_price directly from the data
                    buy_price = country_data['buy_price']
                    # Format button text to ensure price is visible
                    name = country_data['name']
                    if len(name) > 15:
                        name = name[:12] + "..."
                    button_text = f"{name} ${buy_price}"
                    row.append(InlineKeyboardButton(button_text, callback_data=f"buy_country_{country_key}"))
        if row:  # Only add non-empty rows
            keyboard.append(row)

    # Add back button
    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(buy_text, reply_markup=reply_markup, parse_mode='Markdown')

async def sell_account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle sell account button callback - show all countries directly"""
    if not await check_bot_status(update, context):
        return
    query = update.callback_query
    await query.answer()

    sell_text = """
💸 **Sell Telegram Account**

Select Country:
"""

    # Get all countries sorted by sell price (descending for better visibility)
    all_countries = list(COUNTRIES_DATA.keys())
    # Move newly added or updated countries to the top if they are within the last 24 hours (simplified logic)
    # Since we don't have a 'created_at' for countries, we'll just keep the price sort
    # but ensure the list is actually being updated from the file
    all_countries.sort(key=lambda x: COUNTRIES_DATA[x]['sell_price'], reverse=True)

    # Create keyboard with 2 countries per row
    keyboard = []
    # Maximum countries to show per page to avoid "Message is too long" or keyboard size limits
    # Telegram allows max 100 buttons per message. We use 90 to be safe.
    MAX_COUNTRIES = 90
    
    # Ensure COUNTRIES_DATA is not empty and check for data
    if not COUNTRIES_DATA:
        # Emergency initialization if empty
        load_countries_data()
        all_countries = list(COUNTRIES_DATA.keys())
        all_countries.sort(key=lambda x: COUNTRIES_DATA.get(x, {}).get('sell_price', 0), reverse=True)

    # Check if we should show the next page (pagination)
    page = context.user_data.get('sell_page', 0)
    start_idx = page * MAX_COUNTRIES
    end_idx = start_idx + MAX_COUNTRIES
    display_countries = all_countries[start_idx:end_idx]
    
    logger.info(f"Displaying {len(display_countries)} countries for sell flow. Total: {len(all_countries)}")
    
    for i in range(0, len(display_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(display_countries):
                country_key = display_countries[i + j]
                if country_key in COUNTRIES_DATA:
                    country_data = COUNTRIES_DATA[country_key]
                    # Format button text to ensure price is visible
                    name = country_data['name']
                    if len(name) > 15:
                        name = name[:12] + "..."
                    button_text = f"{name} ${country_data['sell_price']}"
                    row.append(InlineKeyboardButton(button_text, callback_data=f"select_{country_key}"))
        if row:  # Only add non-empty rows
            keyboard.append(row)

    # Pagination buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"sell_page_{page-1}"))
    if end_idx < len(all_countries):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"sell_page_{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)

    # Add back button
    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(sell_text, reply_markup=reply_markup, parse_mode='Markdown')

async def sell_pagination_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle sell account list pagination"""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split('_')[-1])
    context.user_data['sell_page'] = page
    await sell_account_callback(update, context)

async def topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle top-up button callback"""
    if not await check_bot_status(update, context):
        return
    query = update.callback_query
    await query.answer()

    topup_text = """
💳 **Top-Up Balance**

Add funds to your account using the following payment methods:

💰 **Available Payment Methods:**

🟡 **Binance** - Fast and secure
💳 **Payeer** - Digital payment system  
💎 **USDT TRC20** - Tron network
🔸 **USDT BEP20** - Binance Smart Chain
🌐 **USDT Arbitrum** - Low fees

Choose your preferred payment method from the buttons below:
"""

    keyboard = [
        [
            InlineKeyboardButton("🟡 Binance", callback_data="topup_binance"),
            InlineKeyboardButton("💳 Payeer", callback_data="topup_payeer")
        ],
        [
            InlineKeyboardButton("💎 USDT TRC20", callback_data="topup_trc20"),
            InlineKeyboardButton("🔸 USDT BEP20", callback_data="topup_bep20")
        ],
        [
            InlineKeyboardButton("🌐 USDT Arbitrum", callback_data="topup_arbitrum")
        ],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(topup_text, reply_markup=reply_markup, parse_mode='Markdown')

# Withdrawal states
WAITING_FOR_WITHDRAW_ADDRESS, WAITING_FOR_WITHDRAW_AMOUNT = range(100, 102)

async def withdrawal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle withdrawal button callback"""
    if not await check_bot_status(update, context):
        return
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    
    withdrawal_text = f"""
🏦 **Withdraw USDT**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT

Select your withdrawal method:
"""

    keyboard = [
        [
            InlineKeyboardButton("USDT (BEP20)", callback_data="withdraw_usdt_bep20"),
            InlineKeyboardButton("USDT (TRC20)", callback_data="withdraw_usdt_trc20")
        ],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdrawal_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_method_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle USDT method selection"""
    query = update.callback_query
    await query.answer()
    
    method = query.data.split('_')[-1].upper()
    context.user_data['withdraw_method'] = method
    
    await query.edit_message_text(f"Please enter your USDT ({method}) address:")
    return WAITING_FOR_WITHDRAW_ADDRESS

async def handle_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle withdrawal address input"""
    address = update.message.text.strip()
    context.user_data['withdraw_address'] = address
    
    user_id = str(update.effective_user.id)
    user_info = get_user_data(user_id)
    
    await update.message.reply_text(
        f"Your address: `{address}`\n\nEnter the amount to withdraw:\n(Your main balance: {user_info['main_balance_usdt']:.2f} USDT)",
        parse_mode='Markdown'
    )
    return WAITING_FOR_WITHDRAW_AMOUNT

async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle withdrawal amount input and validate"""
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number.")
        return WAITING_FOR_WITHDRAW_AMOUNT

    user_id = str(update.effective_user.id)
    user_info = get_user_data(user_id)

    if amount < 10:
        await update.message.reply_text("❌ Minimum withdrawal 10 USDT\nWithdrawal cancelled.")
        # Reset context and go to start
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END

    if amount > user_info['main_balance_usdt']:
        await update.message.reply_text(f"❌ Insufficient balance! Your balance: {user_info['main_balance_usdt']:.2f} USDT\nWithdrawal cancelled.")
        # Reset context and go to start
        context.user_data.clear()
        await start(update, context)
        return ConversationHandler.END

    # Process withdrawal
    with user_data_lock:
        user_data[user_id]['main_balance_usdt'] -= amount
        user_data[user_id]['withdrawal_processing_balance'] = user_data[user_id].get('withdrawal_processing_balance', 0.0) + amount
        save_user_data()

    method = context.user_data.get('withdraw_method')
    address = context.user_data.get('withdraw_address')

    processing_text = f"""
✅ **Withdrawal Processing**

📍 Address: `{address}`
💰 Amount: {amount:.2f} USDT ({method})
⏳ Time: Up to 12 minutes

Please wait while we process your request.
"""
    await update.message.reply_text(processing_text, parse_mode='Markdown')
    
    # Reset conversation context
    context.user_data.clear()
    
    # Return to main menu
    await start(update, context)
    return ConversationHandler.END

async def cancel_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel withdrawal and return to start"""
    await update.message.reply_text("Withdrawal cancelled.")
    await start(update, context)
    return ConversationHandler.END

# Withdrawal callback functions for each payment method
async def withdraw_binance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Binance withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'binance')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
🟡 **Binance Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **Binance email** and **withdrawal amount**:

Format: email@example.com 10.50
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_paypal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle PayPal withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'paypal')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
🌐 **PayPal Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **PayPal email** and **withdrawal amount**:

Format: paypal@example.com 15.00
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_bank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Bank withdrawal (USA/UK/Canada only)"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'bank')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
🏦 **Bank Withdrawal** (USA/UK/Canada Only)

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

⚠️ **Available for USA, UK, and Canada residents only**

Please provide your **bank details** and **withdrawal amount**:

Format: ACCOUNT_NUMBER ROUTING_CODE AMOUNT

Example: 1234567890 987654321 25.00
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

# Admin Top-Up Info Control
async def admin_send_sms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin send SMS callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    sms_text = """
📩 **Send SMS**

Choose how to send messages:

📢 **Send SMS All Users** - Send message to all users
👤 **Send SMS Single User** - Send message to specific user

Select an option:
"""

    keyboard = [
        [InlineKeyboardButton("📢 Send SMS All Users", callback_data="admin_sms_all_users")],
        [InlineKeyboardButton("👤 Send SMS Single User", callback_data="admin_sms_single_user")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(sms_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_sms_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin SMS all users callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    sms_all_text = """
📢 **Send SMS to All Users**

Write the message you want to send to all users.

Example: Hello everyone! New features are available.

Please type your message:
"""

    context.user_data['admin_sms_all_users'] = True
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_send_sms")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(sms_all_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_sms_single_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin SMS single user callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    sms_single_text = """
👤 **Send SMS to Single User**

First, enter the User Chat ID:

Example: 123456789

Please enter the user Chat ID:
"""

    context.user_data['admin_sms_single_user'] = True
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_send_sms")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(sms_single_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_chat_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin chat user callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    chat_text = """
💬 **Chat with User**

Enter the User Chat ID to start conversation:

Example: 123456789

Please enter the user Chat ID:
"""

    context.user_data['admin_chat_user'] = True
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(chat_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_topup_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin top-up info control"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    topup_info_text = """
💳 **Top-Up Info Control Panel**

Control what information shows for each payment method when users select top-up options.

Select a payment method to edit its details:
"""

    keyboard = [
        [InlineKeyboardButton("🟡 Binance Info", callback_data="edit_binance_info")],
        [InlineKeyboardButton("💳 Payeer Info", callback_data="edit_payeer_info")],
        [InlineKeyboardButton("💎 TRC20 Info", callback_data="edit_trc20_info")],
        [InlineKeyboardButton("🔸 BEP20 Info", callback_data="edit_bep20_info")],
        [InlineKeyboardButton("🌐 PayPal Info", callback_data="edit_paypal_info")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(topup_info_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_withdrawal_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin withdrawal set callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    current_global_limit = withdrawal_settings.get('global_limit', 1.0)
    custom_user_count = len(withdrawal_settings.get('user_limits', {}))

    withdrawal_set_text = f"""
🏦 **Withdrawal Set Control**

📊 **Current Settings:**
• Global Minimum Limit: ${current_global_limit} USD
• Custom User Limits: {custom_user_count} users

Choose an option:
"""

    keyboard = [
        [InlineKeyboardButton("📊 All Set", callback_data="admin_withdrawal_all_set")],
        [InlineKeyboardButton("👤 Custom User Withdrawal Limit Set", callback_data="admin_withdrawal_custom_user")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdrawal_set_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_withdrawal_all_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin withdrawal all set callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    current_limit = withdrawal_settings.get('global_limit', 1.0)

    all_set_text = f"""
📊 **All Set - Global Withdrawal Limit**

💵 **Current Global Limit:** ${current_limit} USD

Enter new minimum withdrawal limit for ALL users (USD):

Example: 3.00

Note: This limit applies to all users who don't have a custom limit set.
"""

    context.user_data['admin_withdrawal_all_set'] = True
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_withdrawal_set")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(all_set_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_withdrawal_custom_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin withdrawal custom user callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    custom_user_text = """
👤 **Custom User Withdrawal Limit Set**

Enter the User Chat ID to set custom withdrawal limit:

Example: 123456789

Please enter the user Chat ID:
"""

    context.user_data['admin_withdrawal_custom_user'] = True
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_withdrawal_set")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(custom_user_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_admin_withdrawal_all_set_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin withdrawal all set limit input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    try:
        limit_input = update.message.text.strip()
        new_limit = float(limit_input)
        
        if new_limit <= 0:
            await update.message.reply_text("❌ Limit must be greater than zero!")
            return
        if new_limit > 10000:
            await update.message.reply_text("❌ Limit cannot exceed $10,000 USD!")
            return
        if len(limit_input.split('.')) > 1 and len(limit_input.split('.')[1]) > 2:
            await update.message.reply_text("❌ Limit can have maximum 2 decimal places!")
            return
            
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number! Example: 3.00")
        return

    # Update global limit
    withdrawal_settings['global_limit'] = new_limit
    save_withdrawal_settings()

    success_text = f"""
✅ **Global Withdrawal Limit Updated!**

💵 **New Limit:** ${new_limit} USD

This limit now applies to all users who don't have a custom limit set.
"""

    keyboard = [
        [InlineKeyboardButton("🔄 Change Again", callback_data="admin_withdrawal_all_set")],
        [InlineKeyboardButton("🔙 Withdrawal Set", callback_data="admin_withdrawal_set")],
        [InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Clear context
    context.user_data.pop('admin_withdrawal_all_set', None)

async def handle_admin_withdrawal_custom_user_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin withdrawal custom user ID input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    target_user_id = update.message.text.strip()

    # Validate user ID
    if not target_user_id.isdigit():
        await update.message.reply_text("❌ User ID must be a number!")
        return

    # Store target user ID and ask for limit (get or create user data for users who haven't started bot)
    context.user_data['withdrawal_limit_target_user'] = target_user_id
    
    user_info = get_user_data(target_user_id)
    current_limit = withdrawal_settings['user_limits'].get(target_user_id, withdrawal_settings['global_limit'])

    limit_request_text = f"""
💵 **Set Custom Withdrawal Limit**

👤 **User ID:** {target_user_id}
💰 **User Balance:** {user_info['main_balance_usdt']:.2f} USDT
📊 **Current Limit:** ${current_limit} USD

Enter new withdrawal limit for this user (USD):

Example: 5.00
"""

    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_withdrawal_set")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(limit_request_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_admin_withdrawal_custom_user_limit_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin withdrawal custom user limit input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    target_user_id = context.user_data.get('withdrawal_limit_target_user')
    if not target_user_id:
        await update.message.reply_text("❌ Target user not found!")
        return

    try:
        limit_input = update.message.text.strip()
        new_limit = float(limit_input)
        
        if new_limit <= 0:
            await update.message.reply_text("❌ Limit must be greater than zero!")
            return
        if new_limit > 10000:
            await update.message.reply_text("❌ Limit cannot exceed $10,000 USD!")
            return
        if len(limit_input.split('.')) > 1 and len(limit_input.split('.')[1]) > 2:
            await update.message.reply_text("❌ Limit can have maximum 2 decimal places!")
            return
            
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number! Example: 5.00")
        return

    # Update user-specific limit
    withdrawal_settings['user_limits'][target_user_id] = new_limit
    save_withdrawal_settings()

    success_text = f"""
✅ **Custom Withdrawal Limit Set!**

👤 **User ID:** {target_user_id}
💵 **New Limit:** ${new_limit} USD

This user now has a custom withdrawal limit that overrides the global setting.
"""

    keyboard = [
        [InlineKeyboardButton("👤 Set Another User", callback_data="admin_withdrawal_custom_user")],
        [InlineKeyboardButton("🔙 Withdrawal Set", callback_data="admin_withdrawal_set")],
        [InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Clear context
    context.user_data.pop('admin_withdrawal_custom_user', None)
    context.user_data.pop('withdrawal_limit_target_user', None)

# Additional withdrawal method callbacks
async def withdraw_payeer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Payeer withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'payeer')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
💳 **Payeer Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **Payeer account** and **withdrawal amount**:

Format: P1234567890 20.00
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_trc20_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle TRC20 withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'trc20')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
💎 **TRC20 USDT Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **TRC20 wallet address** and **withdrawal amount**:

Format: TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t 15.00
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_bep20_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle BEP20 withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'bep20')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
🔸 **BEP20 USDT Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **BEP20 wallet address** and **withdrawal amount**:

Format: 0x742d35Cc6634C0532925a3b8D4c0532925a3b8D4c 25.00
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_bitcoin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Bitcoin withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'bitcoin')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
₿ **Bitcoin Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **Bitcoin address** and **withdrawal amount**:

Format: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa 30.00
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_cashapp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Cash App withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'cashapp')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
📱 **Cash App Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **Cash App tag** and **withdrawal amount**:

Format: $username 18.50
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

async def withdraw_upi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle UPI withdrawal"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)
    min_withdrawal = get_combined_withdrawal_limit(user_id, user_info['main_balance_usdt'], 'upi')

    if user_info['main_balance_usdt'] < min_withdrawal:
        await query.edit_message_text(
            f"❌ **Insufficient Balance!**\n\nMinimum withdrawal: ${min_withdrawal:.2f} USD\nYour balance: {user_info['main_balance_usdt']:.2f} USDT",
            parse_mode='Markdown'
        )
        return

    withdraw_text = f"""
🇮🇳 **UPI Withdrawal**

💰 **Current Balance:** {user_info['main_balance_usdt']:.2f} USDT
💵 **Minimum Amount:** ${min_withdrawal:.2f} USD

Please provide your **UPI ID** and **withdrawal amount**:

Format: username@paytm 12.75
"""

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="withdrawal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(withdraw_text, reply_markup=reply_markup, parse_mode='Markdown')

# Top-up payment method handlers
async def topup_binance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Binance top-up"""
    query = update.callback_query
    await query.answer()

    topup_text = """
🟡 **Binance Top-Up**

To add funds to your account via Binance:

📋 **Binance ID:** `1087738186`

**Instructions:**
1. Open your Binance app/website
2. Go to P2P or Transfer section
3. Send USDT to Binance ID: **1087738186**
4. After payment, send screenshot to admin for verification

💡 **Note:** Processing time is usually 5-15 minutes after verification.
"""

    keyboard = [[InlineKeyboardButton("🔙 Back to Top-Up", callback_data="topup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(topup_text, reply_markup=reply_markup, parse_mode='Markdown')

async def topup_payeer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Payeer top-up"""
    query = update.callback_query
    await query.answer()

    topup_text = """
💳 **Payeer Top-Up**

To add funds to your account via Payeer:

📋 **Payeer ID:** `P1132712885`

**Instructions:**
1. Log in to your Payeer account
2. Go to Transfer/Send Money section
3. Send USDT to Payeer ID: **P1132712885**
4. After payment, send transaction ID to admin for verification

💡 **Note:** Processing time is usually 5-15 minutes after verification.
"""

    keyboard = [[InlineKeyboardButton("🔙 Back to Top-Up", callback_data="topup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(topup_text, reply_markup=reply_markup, parse_mode='Markdown')

async def topup_trc20_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle TRC20 USDT top-up"""
    query = update.callback_query
    await query.answer()

    topup_text = """
💎 **USDT TRC20 Top-Up**

To add funds to your account via TRC20 network:

📋 **TRC20 Address:** 
`TNuVc3rWtsM3mmBVUZLUHbUqcxxNJV8NqX`

**Instructions:**
1. Open your crypto wallet (TronLink, Trust Wallet, etc.)
2. Select USDT TRC20 network
3. Send USDT to the address above
4. After payment, send transaction hash to admin for verification

⚠️ **Important:** Only send USDT on TRC20 network. Other tokens or networks may result in loss of funds.

💡 **Note:** Processing time is usually 5-15 minutes after verification.
"""

    keyboard = [[InlineKeyboardButton("🔙 Back to Top-Up", callback_data="topup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(topup_text, reply_markup=reply_markup, parse_mode='Markdown')

async def topup_bep20_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle BEP20 USDT top-up"""
    query = update.callback_query
    await query.answer()

    topup_text = """
🔸 **USDT BEP20 Top-Up**

To add funds to your account via BEP20 network:

📋 **BEP20 Address:** 
`0xb53712a37728f313d76c53ce514ebd4ba95f99c1`

**Instructions:**
1. Open your crypto wallet (MetaMask, Trust Wallet, etc.)
2. Select USDT BEP20/BSC network
3. Send USDT to the address above
4. After payment, send transaction hash to admin for verification

⚠️ **Important:** Only send USDT on BEP20/BSC network. Other tokens or networks may result in loss of funds.

💡 **Note:** Processing time is usually 5-15 minutes after verification.
"""

    keyboard = [[InlineKeyboardButton("🔙 Back to Top-Up", callback_data="topup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(topup_text, reply_markup=reply_markup, parse_mode='Markdown')

async def topup_arbitrum_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Arbitrum USDT top-up"""
    query = update.callback_query
    await query.answer()

    topup_text = """
🌐 **USDT Arbitrum Top-Up**

To add funds to your account via Arbitrum network:

📋 **Arbitrum Address:** 
`0xb53712a37728f313d76c53ce514ebd4ba95f99c1`

**Instructions:**
1. Open your crypto wallet (MetaMask, etc.)
2. Select USDT on Arbitrum network
3. Send USDT to the address above
4. After payment, send transaction hash to admin for verification

⚠️ **Important:** Only send USDT on Arbitrum network. Other tokens or networks may result in loss of funds.

💡 **Note:** Processing time is usually 5-15 minutes after verification. Lower fees compared to Ethereum mainnet.
"""

    keyboard = [[InlineKeyboardButton("🔙 Back to Top-Up", callback_data="topup")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(topup_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, account_type: str, price: float) -> None:
    """Handle account purchase"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)

    if user_info['main_balance_usdt'] >= price:
        # Deduct balance and increment bought accounts
        user_info['main_balance_usdt'] -= price
        user_info['accounts_bought'] += 1
        save_user_data()

        success_text = f"""
✅ **Purchase Successful!**

📱 **{account_type} Account** purchased
💰 **Cost:** {price} USDT
💳 **Current Main Balance:** {user_info['main_balance_usdt']:.2f} USDT

📧 Account details will be sent to your inbox soon.

🎉 Thanks for using our service!
"""
    else:
        needed = price - user_info['main_balance_usdt']
        success_text = f"""
❌ **Insufficient Balance!**

💰 **Required:** {price} USDT
💳 **Your Main Balance:** {user_info['main_balance_usdt']:.2f} USDT
🔺 **Additional needed:** {needed:.2f} USDT

💳 Please top-up your balance first.
"""

    keyboard = [
        [InlineKeyboardButton("💳 Top-Up Balance", callback_data="topup")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

# Purchase callback handlers
async def buy_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_purchase(update, context, "Premium", 50.0)

async def buy_standard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_purchase(update, context, "Standard", 25.0)

async def buy_basic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_purchase(update, context, "Basic", 10.0)

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to main menu"""
    await start(update, context)

# Country Region Handlers
async def countries_europe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show European countries"""
    query = update.callback_query
    await query.answer()

    europe_countries = ['italy', 'france', 'spain', 'england', 'netherlands', 'germany', 'switzerland', 'sweden', 'norway', 'denmark', 'austria', 'belgium', 'portugal', 'latvia', 'estonia', 'ireland', 'serbia', 'romania', 'slovenia', 'hungary', 'belarus', 'croatia', 'poland', 'czech', 'moldova', 'bosnia', 'bulgaria', 'luxembourg', 'malta', 'iceland', 'albania', 'monaco']

    text = "🇪🇺 **European Countries** (Demo Mode)\n\n"
    text += "⚠️ This is a test bot - no real transactions occur\n\n"

    keyboard = []
    for i in range(0, len(europe_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(europe_countries):
                country_key = europe_countries[i + j]
                country_data = COUNTRIES_DATA[country_key]
                button_text = f"{country_data['name']} ${country_data['sell_price']}"
                row.append(InlineKeyboardButton(button_text, callback_data=f"select_{country_key}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Country List", callback_data="sell_account")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def countries_asia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Asian countries"""
    query = update.callback_query
    await query.answer()

    asia_countries = ['kazakhstan', 'russia', 'ukraine', 'kyrgyzstan', 'uzbekistan', 'turkmenistan', 'tajikistan', 'georgia', 'armenia', 'azerbaijan', 'turkey', 'saudi', 'uae', 'qatar', 'oman', 'kuwait', 'bahrain', 'iraq', 'iran', 'afghanistan', 'pakistan', 'india', 'bangladesh', 'sri_lanka', 'nepal', 'bhutan', 'maldives', 'myanmar', 'thailand', 'vietnam', 'laos', 'cambodia', 'malaysia', 'singapore', 'indonesia', 'philippines', 'brunei', 'timor', 'taiwan', 'hong_kong', 'macau', 'china', 'mongolia', 'japan', 'south_korea', 'north_korea', 'syria', 'lebanon', 'jordan', 'israel', 'palestine', 'yemen']

    text = "🌏 **Asian Countries** (Demo Mode)\n\n"
    text += "⚠️ This is a test bot - no real transactions occur\n\n"

    keyboard = []
    for i in range(0, len(asia_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(asia_countries):
                country_key = asia_countries[i + j]
                country_data = COUNTRIES_DATA[country_key]
                button_text = f"{country_data['name']} ${country_data['sell_price']}"
                row.append(InlineKeyboardButton(button_text, callback_data=f"select_{country_key}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Country List", callback_data="sell_account")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def countries_africa_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show African countries"""
    query = update.callback_query
    await query.answer()

    africa_countries = ['egypt', 'libya', 'tunisia', 'algeria', 'morocco', 'sudan', 'south_sudan', 'ethiopia', 'somalia', 'djibouti', 'eritrea', 'kenya', 'uganda', 'tanzania', 'rwanda', 'burundi', 'congo_dr', 'congo', 'central_africa', 'cameroon', 'chad', 'gabon', 'equatorial_guinea', 'sao_tome', 'nigeria', 'ghana', 'ivory_coast', 'liberia', 'sierra_leone', 'guinea', 'guinea_bissau', 'senegal', 'gambia', 'mali', 'burkina_faso', 'niger', 'togo', 'benin', 'madagascar', 'mauritius', 'seychelles', 'comoros', 'south_africa', 'namibia', 'botswana', 'zimbabwe', 'zambia', 'malawi', 'mozambique', 'angola', 'lesotho', 'swaziland', 'cape_verde']

    text = "🌍 **African Countries** (Demo Mode)\n\n"
    text += "⚠️ This is a test bot - no real transactions occur\n\n"

    keyboard = []
    for i in range(0, len(africa_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(africa_countries):
                country_key = africa_countries[i + j]
                country_data = COUNTRIES_DATA[country_key]
                button_text = f"{country_data['name']} ${country_data['sell_price']}"
                row.append(InlineKeyboardButton(button_text, callback_data=f"select_{country_key}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Country List", callback_data="sell_account")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def countries_america_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show American countries"""
    query = update.callback_query
    await query.answer()

    america_countries = ['usa', 'canada', 'mexico', 'guatemala', 'belize', 'el_salvador', 'honduras', 'nicaragua', 'costa_rica', 'panama', 'cuba', 'jamaica', 'haiti', 'dominican', 'puerto_rico', 'trinidad', 'barbados', 'grenada', 'lucia', 'grenadines', 'dominica', 'antigua', 'anguilla', 'cayman', 'bermuda', 'colombia', 'venezuela', 'guyana', 'suriname', 'brazil', 'ecuador', 'peru', 'bolivia', 'paraguay', 'uruguay', 'argentina', 'chile', 'falkland', 'guadeloupe', 'martinique', 'french_guiana']

    text = "🌎 **American Countries** (Demo Mode)\n\n"
    text += "⚠️ This is a test bot - no real transactions occur\n\n"

    keyboard = []
    for i in range(0, len(america_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(america_countries):
                country_key = america_countries[i + j]
                country_data = COUNTRIES_DATA[country_key]
                button_text = f"{country_data['name']} ${country_data['sell_price']}"
                row.append(InlineKeyboardButton(button_text, callback_data=f"select_{country_key}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Country List", callback_data="sell_account")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def countries_others_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show other countries"""
    query = update.callback_query
    await query.answer()

    other_countries = ['australia', 'new_zealand', 'fiji', 'tonga', 'samoa', 'solomon', 'vanuatu', 'papua', 'micronesia', 'palau', 'marshall', 'kiribati', 'tuvalu', 'nauru', 'cook', 'niue', 'tokelau', 'aruba', 'curacao', 'sint_maarten']

    text = "🌊 **Other Countries** (Demo Mode)\n\n"
    text += "⚠️ This is a test bot - no real transactions occur\n\n"

    keyboard = []
    for i in range(0, len(other_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(other_countries):
                country_key = other_countries[i + j]
                country_data = COUNTRIES_DATA[country_key]
                button_text = f"{country_data['name']} ${country_data['sell_price']}"
                row.append(InlineKeyboardButton(button_text, callback_data=f"select_{country_key}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Country List", callback_data="sell_account")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def country_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle individual country selection and start sell conversation"""
    query = update.callback_query
    await query.answer()

    # Extract country key from callback data (remove 'select_' prefix)
    country_key = query.data.replace('select_', '')

    if country_key in COUNTRIES_DATA:
        country_data = COUNTRIES_DATA[country_key]

        # Store selected country in context
        context.user_data['selected_country'] = country_key
        context.user_data['country_data'] = country_data

        number_request_text = f"""
🔢 **Provide Number**

📱 Country: {country_data['name']}
💰 Sell Price: ${country_data['sell_price']} USD

Please send a number with **7 to 14 digits**:

⚠️ **Note:** This is a Telegram bot. What happens here has no relation to reality. We do not support anything against countries, governments, or Telegram. You act at your own risk.
"""

        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="sell_account")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(number_request_text, reply_markup=reply_markup, parse_mode='Markdown')

        return WAITING_FOR_NUMBER
    else:
        await query.edit_message_text("❌ Country information not found!", parse_mode='Markdown')
        return ConversationHandler.END

async def send_admin_approval_request(context: ContextTypes.DEFAULT_TYPE, user_id: str, number: str, country: str, price: float) -> None:
    """Send approval request to admin for sell account"""
    try:
        user_info = get_user_data(user_id)
        approval_text = f"""
🔔 **New Account Sale Request**

👤 **User:** {user_id}
📞 **Number:** {number}
🌍 **Country:** {country}
💰 **Price:** ${price} USD

💳 **Main Balance:** {user_info['main_balance_usdt']:.2f} USDT
💳 **Hold Balance:** {user_info['hold_balance_usdt']:.2f} USDT

**Do you approve this sell request?**
"""

        keyboard = [
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_sell_{user_id}_{price}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject_sell_{user_id}")],
            [InlineKeyboardButton("📩 Reject SMS", callback_data=f"reject_sms_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=approval_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send admin approval request: {e}")

async def handle_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the number input from user"""
    if not update.message or not update.message.text:
        return WAITING_FOR_NUMBER

    number = update.message.text.strip()

    # Check if number was already sold by anyone
    with user_data_lock:
        for u_id, u_data in user_data.items():
            if 'sold_numbers' in u_data and number in u_data['sold_numbers']:
                await update.message.reply_text(
                    "❌ Sorry! This number has **already been sold** and cannot be used again."
                )
                return WAITING_FOR_NUMBER

    # Validate number length (7-14 digits)
    if not number.isdigit() or len(number) < 7 or len(number) > 14:
        await update.message.reply_text(
            "❌ Sorry! Please provide a number with **7 to 14 digits**.\n\n"
            "Example: 1234567 or 12345678901234"
        )
        return WAITING_FOR_NUMBER

    # Store the number
    context.user_data['user_number'] = number

    # Get stored country data
    country_data = context.user_data.get('country_data')
    if not country_data:
        await update.message.reply_text("❌ Error! Please start over.")
        return ConversationHandler.END

    # Show 4-second animation while checking number
    animation_frames = [
        "⏳ **Please wait...**\n\n🔍 Checking number.",
        "⏳ **Please wait...**\n\n🔍 Checking number..",
        "⏳ **Please wait...**\n\n🔍 Checking number...",
        "⏳ **Please wait...**\n\n🔍 Checking number...."
    ]
    
    # Send initial animation message
    anim_msg = await update.message.reply_text(animation_frames[0], parse_mode='Markdown')
    
    # Animate for 4 seconds (1 second per frame)
    for i in range(1, 4):
        await asyncio.sleep(1)
        try:
            await anim_msg.edit_text(animation_frames[i], parse_mode='Markdown')
        except Exception:
            pass
    
    await asyncio.sleep(1)

    # Final waiting text (processing message)
    processing_text = f"""
⏳ **BGT WALLET - PROCESSING** ⏳
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
🌍 **Country:** {country_data['name']}
📞 `{number}`
💰 **Payout:** ${country_data['sell_price']} USD
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
Your asset is currently being processed by our real-time system.

⏱️ **Hold Period:** 24 Hours.
🔔 **Next Step:** You will receive a notification to enter your OTP once the manual check is complete.

Please wait patiently. You can track this in your Web Dashboard.
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
"""

    keyboard = [[InlineKeyboardButton("❌ Cancel Sale", callback_data="sell_account")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Edit the animation message to show processing message
    try:
        await anim_msg.edit_text(processing_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception:
        await update.message.reply_text(processing_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Send admin approval request
    await send_admin_approval_request(
        context, 
        str(update.effective_user.id),
        number, 
        country_data['name'], 
        country_data['sell_price']
    )

    # In this new flow, we return to WAITING_FOR_ADMIN_APPROVAL
    # and wait for the admin to call approve_sell_callback which will prompt the user for PIN.
    return WAITING_FOR_ADMIN_APPROVAL

async def handle_pin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the verification OTP input from user"""
    # Check if process is still ongoing
    if not context.user_data.get('admin_approved'):
        country_data = context.user_data.get('country_data', {})
        country_name = country_data.get('name', 'Unknown')
        user_number = context.user_data.get('user_number', 'Unknown')
        
        wait_text = f"""
⏳ **REQUEST IN PROGRESS** ⏳
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
🌍 **Country:** {country_name}
📞 `{user_number}`
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
Your account details are currently being processed by our system. 

⏱️ **Estimated time:** Maximum 5 minutes.
🔔 **Next Step:** You will receive a notification as soon as you can enter your verification code.

Please wait patiently and do not send any other messages.
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
"""
        keyboard = [[InlineKeyboardButton("❌ Cancel Sale", callback_data="sell_account")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(wait_text, reply_markup=reply_markup, parse_mode='Markdown')
        return WAITING_FOR_ADMIN_APPROVAL

    if not update.message or not update.message.text:
        return WAITING_FOR_PIN

    pin = update.message.text.strip()

    # Validate otp length (1-6 digits)
    if not pin.isdigit() or len(pin) < 1 or len(pin) > 6:
        # Get country info for the error message
        country_data = context.user_data.get('country_data', {})
        country_name = country_data.get('name', 'Unknown')
        user_number = context.user_data.get('user_number', 'Unknown')
        
        keyboard = [[InlineKeyboardButton("❌ Cancel Sale", callback_data="cancel_sale_otp")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"❌ **Sorry! Please provide a verification OTP with **1 to 6 digits**.**\n\n"
            f"🌍 **Country:** {country_name}\n"
            f"📞 `{user_number}`\n\n"
            "Example: 1, 123, or 123456",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return WAITING_FOR_PIN

    # Get stored data
    country_data = context.user_data.get('country_data')
    user_number = context.user_data.get('user_number')

    if not country_data or not user_number:
        await update.message.reply_text("❌ Error! Please start over.")
        return ConversationHandler.END

    # Show 3-second animation while checking verification code
    pin_animation_frames = [
        "⏳ **OTP Verification...**\n\nPlease wait up to 5 minutes.",
        "⏳ **OTP Verification...**\n\nPlease wait up to 5 minutes..",
        "⏳ **OTP Verification...**\n\nPlease wait up to 5 minutes..."
    ]
    
    # Send initial animation message
    pin_anim_msg = await update.message.reply_text(pin_animation_frames[0], parse_mode='Markdown')
    
    # Animate for 3 seconds (1 second per frame)
    for i in range(1, 3):
        await asyncio.sleep(1)
        try:
            await pin_anim_msg.edit_text(pin_animation_frames[i], parse_mode='Markdown')
        except Exception:
            pass
    
    await asyncio.sleep(1)
    
    # Delete animation message
    try:
        await pin_anim_msg.delete()
    except Exception:
        pass

    # Update user balance and stats - add to hold balance
    user_id = str(update.effective_user.id)
    context.user_data['otp_submitted'] = True
    
    # Get stored data
    country_data = context.user_data.get('country_data')
    user_number = context.user_data.get('user_number')

    # Show final submission message to user
    submission_text = f"""
✅ **OTP Submitted!**
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

📞 **Number:** {user_number}
🔐 **OTP:** {pin}

⏳ **OTP Verification In Progress...**
Everything will be processed within maximum 5 minutes. Please stay tuned.
"""

    await update.message.reply_text(submission_text, parse_mode='Markdown')

    # Notify user
    try:
        user_info = get_user_data(user_id)
        notification_text = f"""
🔔 **New OTP Verification Request**

👤 **User ID:** `{user_id}`
📞 **Number:** `{user_number}`
🔐 **OTP:** `{pin}`
🌍 **Country:** {country_data['name']}
💰 **Price:** ${country_data['sell_price']} USD

Please verify the OTP and confirm if it's correct.
"""

        keyboard = [
            [InlineKeyboardButton("✅ Confirm & Add to Hold", callback_data=f"confirm_otp_{user_id}_{country_data['sell_price']}_{user_number}_{country_data['name']}")],
            [InlineKeyboardButton("❌ Wrong OTP", callback_data=f"wrong_otp_{user_id}_{user_number}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=notification_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send admin verification notification: {e}")

    # Clear stored data
    context.user_data.pop('admin_approved', None)
    context.user_data.pop('otp_submitted', None)
    context.user_data.pop('user_number', None)
    context.user_data.pop('country_data', None)

    return ConversationHandler.END

async def cancel_sell_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the sell conversation"""
    context.user_data.clear()
    await sell_account_callback(update, context)
    return ConversationHandler.END


async def send_admin_notification(context: ContextTypes.DEFAULT_TYPE, user_id: str, number: str, pin: str, country: str, price: float) -> None:
    """Send notification to admin about new sell request"""
    try:
        user_info = get_user_data(user_id)
        notification_text = f"""
🔔 **New Account Sale Request**

👤 **User:** {user_id}
📞 **Number:** {number}
🔐 **PIN:** {pin}
🌍 **Country:** {country}
💰 **Price:** ${price} USD

⏳ **Hold Balance:** {user_info['hold_balance_usdt']:.2f} USDT
💰 **Main Balance:** {user_info['main_balance_usdt']:.2f} USDT

Please approve:
"""

        keyboard = [
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{price}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject_pin_{user_id}_{price}")],
            [InlineKeyboardButton("📩 Reject SMS", callback_data=f"reject_pin_sms_{user_id}_{price}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=notification_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}")

async def confirm_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin confirmation of OTP"""
    query = update.callback_query
    await query.answer()

    # Pattern: confirm_otp_{user_id}_{price}_{number}_{country}
    data = query.data.split('_')
    if len(data) < 5:
        return
        
    user_id = data[2]
    price = float(data[3])
    user_number = data[4]
    country_name = data[5] if len(data) > 5 else 'N/A'

    with user_data_lock:
        if user_id not in user_data:
            user_data[user_id] = {
                'main_balance_usdt': 0.0,
                'hold_balance_usdt': 0.0,
                'topup_balance_usdt': 0.0,
                'accounts_bought': 0,
                'accounts_sold': 0,
                'sold_numbers': [],
                'processing_details': [],
                'created_at': datetime.now().isoformat(),
                'last_activity': datetime.now().isoformat()
            }
        
        # Add to processing_details for web tracking ONLY NOW when confirmed & added to hold
        if 'processing_details' not in user_data[user_id]:
            user_data[user_id]['processing_details'] = []
            
        user_data[user_id]['processing_details'].append({
            'number': user_number,
            'price': price,
            'status': 'Processing',
            'timestamp': datetime.now().isoformat(),
            'country': country_name
        })
        save_user_data()

        user_data[user_id]['hold_balance_usdt'] += price
        user_data[user_id]['accounts_sold'] += 1
        if 'sold_numbers' not in user_data[user_id]:
            user_data[user_id]['sold_numbers'] = []
        user_data[user_id]['sold_numbers'].append(user_number)
        user_data[user_id]['last_activity'] = datetime.now().isoformat()
    
    save_user_data()

    # Notify user
    try:
        success_text = f"""
✅ **Confirm & Add to Hold completed - {user_number}**
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

📞 **Number:** {user_number}
💰 **Sell price:** ${price} USD ✓
⏰ **Country's wait time:** 24 hrs ✓

🎉 **Submission successful!** ${price} USD has been added to your Hold Balance!
"""
        keyboard = [
            [InlineKeyboardButton("💰 Check Balance", callback_data="balance")],
            [InlineKeyboardButton("🔙 Sell More Accounts", callback_data="sell_account")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=int(user_id), text=success_text, reply_markup=reply_markup, parse_mode='Markdown')

        # Send second notification to admin for final approval (Hold to Main)
        # Create processing entry ONLY when admin confirms it's on hold
        if 'processing_details' not in user_data[user_id]:
            user_data[user_id]['processing_details'] = []
        
        # We don't add to processing_details yet. 
        # Admin must click "Final Approval" to move to Successful.
        # However, the user wants "Confirm add to hold" logic. 
        # Let's adjust the admin approval button.

        admin_final_text = f"""
🔔 **Final Approval Required**

👤 **User ID:** `{user_id}`
📞 **Number:** `{user_number}`
💰 **Amount:** ${price} USD

The OTP was correct and balance is in **Hold**. Please confirm to transfer to **Main Balance**.
"""
        admin_final_keyboard = [
            [InlineKeyboardButton("✅ Final Approval (Transfer to Main)", callback_data=f"final_approve_{user_id}_{price}_{user_number}")],
            [InlineKeyboardButton("❌ Reject Transfer", callback_data=f"final_reject_{user_id}_{price}_{user_number}")]
        ]
        admin_final_markup = InlineKeyboardMarkup(admin_final_keyboard)
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_final_text,
            reply_markup=admin_final_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user of OTP success or send final admin notification: {e}")

    await query.edit_message_text(f"✅ OTP Confirmed! ${price} added to Hold Balance of user {user_id}. Final approval request sent.")

async def final_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin final confirmation to move from Hold to Main Balance"""
    query = update.callback_query
    await query.answer()

    # Pattern: final_approve_{user_id}_{price}_{number}
    data = query.data.split('_')
    if len(data) < 5:
        return
        
    user_id = data[2]
    price = float(data[3])
    user_number = data[4]

    with user_data_lock:
        if user_id in user_data:
            # Update status in processing_details
            if 'processing_details' in user_data[user_id]:
                for entry in user_data[user_id]['processing_details']:
                    if entry.get('number') == user_number:
                        entry['status'] = 'Successful'
                        break

            # Check if they actually have enough in hold
            if user_data[user_id].get('hold_balance_usdt', 0) >= price:
                user_data[user_id]['hold_balance_usdt'] -= price
                user_data[user_id]['main_balance_usdt'] += price
                user_data[user_id]['last_activity'] = datetime.now().isoformat()
                save_user_data()
            else:
                await query.edit_message_text(f"❌ Error: User {user_id} does not have enough Hold Balance.")
                return

    # Notify user (Professional Style)
    try:
        # Move successful transfer to SUCCESSFUL list in processing_details
        if 'processing_details' not in user_data[user_id]:
            user_data[user_id]['processing_details'] = []
            
        # Update existing processing entry or create new one for successful
        found = False
        for entry in user_data[user_id]['processing_details']:
            if entry.get('number') == user_number:
                entry['status'] = 'Successful'
                found = True
                break
        
        if not found:
            user_data[user_id]['processing_details'].append({
                'number': user_number,
                'price': price,
                'status': 'Successful',
                'timestamp': datetime.now().isoformat(),
                'country': 'N/A'
            })
        save_user_data()

        congrats_text = f"""
🌟 **TRANSACTION SUCCESSFUL** 🌟
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

Congratulations! Your account sale has been verified and fully approved by our administration team.

💰 **Net Profit:** ${price} USD
📱 **Phone Number:** {user_number}
✅ **Status:** Verified & Completed

📈 **Balance Update Details:**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔹 **Hold Balance:** ${price} has been cleared
🔸 **Main Balance:** ${price} is now available
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Your funds have been moved to your **Main Balance**. You can now proceed to withdraw your earnings or use them within the system.

Thank you for being a valued member of our community! 🚀✨
"""
        await context.bot.send_message(chat_id=int(user_id), text=congrats_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user of final approval: {e}")

    await query.edit_message_text(f"✅ Final Approval! ${price} moved from Hold to Main for user {user_id}.")

async def final_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection of final transfer with balance deduction"""
    query = update.callback_query
    await query.answer()
    
    # Pattern: final_reject_{user_id}_{price}_{number}
    data = query.data.split('_')
    if len(data) < 5:
        return
        
    user_id = data[2]
    price = float(data[3])
    user_number = data[4]
    
    with user_data_lock:
        if user_id in user_data:
            # Update status in processing_details
            if 'processing_details' in user_data[user_id]:
                for entry in user_data[user_id]['processing_details']:
                    if entry.get('number') == user_number:
                        entry['status'] = 'Reject'
                        break

            # Deduct from hold balance as the sale failed/was rejected
            if user_data[user_id].get('hold_balance_usdt', 0) >= price:
                user_data[user_id]['hold_balance_usdt'] -= price
                user_data[user_id]['last_activity'] = datetime.now().isoformat()
                save_user_data()
            else:
                logger.warning(f"User {user_id} didn't have enough hold balance for rejection deduction")

    # Notify user (Professional Step-by-Step Style)
    try:
        # Update status in processing_details for rejection
        if 'processing_details' not in user_data[user_id]:
            user_data[user_id]['processing_details'] = []
            
        found = False
        for entry in user_data[user_id]['processing_details']:
            if entry.get('number') == user_number:
                entry['status'] = 'Reject'
                found = True
                break
        
        if not found:
            user_data[user_id]['processing_details'].append({
                'number': user_number,
                'price': price,
                'status': 'Reject',
                'timestamp': datetime.now().isoformat(),
                'country': 'N/A'
            })
        save_user_data()

        reject_text = f"""
❌ **TRANSACTION REJECTED** ❌
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

We regret to inform you that your account sale for the following number has been rejected during the final verification stage.

📱 **Rejected Number:** {user_number}
💰 **Amount Deducted:** ${price} (Hold Balance)
⚠️ **Reason:** Verification Failure

**Detailed Explanation:**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1️⃣ **Account Access:** The administrator could not gain full access to the provided account.
2️⃣ **Security Check:** The account failed our internal security and safety protocols.
3️⃣ **Sale Terminated:** Due to the above reasons, the transaction has been cancelled.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**What happens now?**
- The pending amount has been removed from your **Hold Balance**.
- No funds were added to your Main Balance for this specific number.
- Please ensure you only sell active and accessible accounts.

If you believe this was an error, please contact support with your User ID: `{user_id}`.
"""
        await context.bot.send_message(chat_id=int(user_id), text=reject_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user of rejection: {e}")
        
    await query.edit_message_text(f"❌ Transfer rejected and funds deducted from Hold for user {user_id}, number {user_number}.")

async def wrong_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection of OTP as wrong"""
    query = update.callback_query
    await query.answer()

    # Pattern: wrong_otp_{user_id}_{number}
    data = query.data.split('_')
    if len(data) < 4:
        return
        
    user_id = data[2]
    user_number = data[3]

    # Notify user
    try:
        error_text = f"""
❌ **OTP Verification Failed!**
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

📞 **Number:** {user_number}
⚠️ The OTP you provided was incorrect. Please try again with the correct OTP.
"""
        await context.bot.send_message(chat_id=int(user_id), text=error_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user of OTP failure: {e}")

    await query.edit_message_text(f"❌ Wrong OTP reported to user {user_id} for number {user_number}.")

async def admin_download_data_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin request to download user data file"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.answer("❌ Access Denied!", show_alert=True)
        return

    save_user_data() # Ensure file is up to date

    if not os.path.exists('user_data.json'):
        await query.message.reply_text("❌ Data file not found!")
        return

    try:
        with open('user_data.json', 'rb') as f:
            await context.bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=f,
                filename="user_data.json",
                caption="📊 Latest User Data Export"
            )
    except Exception as e:
        logger.error(f"Failed to send data file: {e}")
        await query.message.reply_text(f"❌ Error downloading data: {e}")

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin panel"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    bot_active = withdrawal_settings.get('bot_active', True)
    bot_status_text = "🟢 **ONLINE**" if bot_active else "🔴 **OFFLINE**"

    admin_text = f"""
🔧 **Admin Panel**

🤖 **Bot Status:** {bot_status_text}

💳 **Balance Control Options:**
• Main Balance Control - Manage user's Main Balance
• Hold Balance Control - Manage user's Hold Balance

💰 **Price Control Options:**
• Sell Account Price Control - Manage sell account prices
• Buy Account Price Control - Manage buy account prices

💳 **Payment Info Options:**
• Top-Up Info - Control payment method details

📊 **System Status:**
• All systems operational
• Database connected
"""

    keyboard = [
        [
            InlineKeyboardButton("✅ Bot ON", callback_data="admin_bot_on"),
            InlineKeyboardButton("❌ Bot OFF", callback_data="admin_bot_off")
        ],
        [InlineKeyboardButton("💳 Main Balance Control", callback_data="admin_main_balance")],
        [InlineKeyboardButton("⏳ Hold Balance Control", callback_data="admin_hold_balance")],
        [InlineKeyboardButton("💸 Sell Account Price Control", callback_data="admin_sell_price_control")],
        [InlineKeyboardButton("🛒 Buy Account Price Control", callback_data="admin_buy_price_control")],
        [InlineKeyboardButton("🆕 Add New Country", callback_data="admin_add_new_country")],
        [InlineKeyboardButton("🔗 Link Add", callback_data="admin_link_add")],
        [InlineKeyboardButton("🗑️ Delete Country", callback_data="admin_delete_country")],
        [InlineKeyboardButton("💳 Top-Up Info", callback_data="admin_topup_info")],
        [InlineKeyboardButton("🏦 Withdrawal Set", callback_data="admin_withdrawal_set")],
        [InlineKeyboardButton("📩 Send SMS", callback_data="admin_send_sms")],
        [InlineKeyboardButton("📊 Download Data", callback_data="admin_download_data")],
        [InlineKeyboardButton("💬 Chat User", callback_data="admin_chat_user")],
        [InlineKeyboardButton("🔙 Balance View", callback_data="balance")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_bot_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bot ON/OFF status changes"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        return

    action = query.data.replace('admin_bot_', '')
    is_active = (action == 'on')
    
    withdrawal_settings['bot_active'] = is_active
    save_withdrawal_settings()

    status_msg = "✅ **Bot has been turned ON!**" if is_active else "❌ **Bot has been turned OFF!**"
    
    # Send notification to all users
    notification_text = ""
    if is_active:
        notification_text = "✨ **System Update** ✨\n\n✅ The bot is now **ONLINE** and ready to process your requests! 🚀\n\nThank you for your patience."
        count = 5
    else:
        notification_text = "⚠️ **Maintenance Alert** ⚠️\n\n🔴 The bot is currently **OFFLINE** for maintenance and upgrades. 🛠️\n\nWe will notify you once we are back online. Sorry for any inconvenience!"
        count = 3

    # Send multiple notifications as requested
    for user_id_key in user_data.keys():
        try:
            for _ in range(count):
                await context.bot.send_message(chat_id=user_id_key, text=notification_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to notify user {user_id_key}: {e}")

    await admin_panel_callback(update, context)

async def admin_sell_price_control_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin sell price control callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    price_control_text = """
💸 **Sell Account Price Control**

Select a country to change its sell price:
"""

    # Get all countries sorted by sell price (descending for better visibility)
    all_countries = list(COUNTRIES_DATA.keys())
    all_countries.sort(key=lambda x: COUNTRIES_DATA[x]['sell_price'], reverse=True)

    # Create keyboard with 2 countries per row
    keyboard = []
    # Maximum countries to show per page to avoid "Message is too long" or keyboard size limits
    # Telegram allows max 100 buttons per message
    MAX_COUNTRIES = 90
    display_countries = all_countries[:MAX_COUNTRIES]
    
    for i in range(0, len(display_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(display_countries):
                country_key = display_countries[i + j]
                if country_key in COUNTRIES_DATA:
                    country_data = COUNTRIES_DATA[country_key]
                    sell_price = country_data['sell_price']
                    # Format button text to show country and current price
                    name = country_data['name']
                    if len(name) > 15:
                        name = name[:12] + "..."
                    button_text = f"{name} ${sell_price}"
                    row.append(InlineKeyboardButton(button_text, callback_data=f"admin_edit_sell_{country_key}"))
        if row:  # Only add non-empty rows
            keyboard.append(row)

    # Add "Add New Country" button
    keyboard.append([InlineKeyboardButton("🆕 Add New Country", callback_data="admin_add_new_country")])
    
    # Add back button
    keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(price_control_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_edit_sell_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin edit sell price for specific country"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    # Extract country key from callback data: admin_edit_sell_{country_key}
    country_key = query.data.split('_', 3)[3]

    if country_key not in COUNTRIES_DATA:
        await query.edit_message_text("❌ Country data not found!")
        return

    country_data = COUNTRIES_DATA[country_key]
    current_price = country_data['sell_price']

    edit_price_text = f"""
💰 **Edit Sell Price**

🌍 **Country:** {country_data['name']}
💵 **Current Sell Price:** ${current_price} USD

Enter new sell price (USD):

Example: 1.50
"""

    # Set context for price change
    context.user_data['price_control_country'] = country_key
    context.user_data['price_control_type'] = 'sell'
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Price Control", callback_data="admin_sell_price_control")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(edit_price_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_add_new_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin add new country"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    add_country_text = """
🆕 **Add New Country**

Write the country name with flag emoji:

Examples:
• Bangladesh 🇧🇩
• Pakistan 🇵🇰  
• Nepal 🇳🇵
• Sweden 🇸🇪

Please enter country name with flag:
"""

    # Set context for new country
    context.user_data['admin_add_new_country'] = True
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Price Control", callback_data="admin_sell_price_control")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(add_country_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_delete_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin delete country - show all countries"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    delete_country_text = """
🗑️ **Delete Country**

Select a country to delete:

⚠️ Warning: This will permanently remove the country from the sell list!
"""

    # Get all countries sorted by sell price (descending for better visibility)
    all_countries = list(COUNTRIES_DATA.keys())
    all_countries.sort(key=lambda x: COUNTRIES_DATA[x]['sell_price'], reverse=True)

    # Create keyboard with 2 countries per row
    keyboard = []
    # Maximum countries to show per page to avoid "Message is too long" or keyboard size limits
    # Telegram allows max 100 buttons per message
    MAX_COUNTRIES = 90
    display_countries = all_countries[:MAX_COUNTRIES]
    
    for i in range(0, len(display_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(display_countries):
                country_key = display_countries[i + j]
                if country_key in COUNTRIES_DATA:
                    country_data = COUNTRIES_DATA[country_key]
                    sell_price = country_data['sell_price']
                    name = country_data['name']
                    if len(name) > 15:
                        name = name[:12] + "..."
                    button_text = f"{name} ${sell_price}"
                    row.append(InlineKeyboardButton(button_text, callback_data=f"admin_del_country_{country_key}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(delete_country_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_confirm_delete_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin confirm delete country - delete and stay on same page"""
    query = update.callback_query

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.answer("❌ Access Denied!", show_alert=True)
        return

    # Extract country key from callback data: admin_del_country_{country_key}
    country_key = query.data.replace('admin_del_country_', '')

    if country_key not in COUNTRIES_DATA:
        await query.answer("❌ Country not found!", show_alert=True)
        return

    country_data = COUNTRIES_DATA[country_key]
    country_name = country_data['name']

    # Delete the country
    del COUNTRIES_DATA[country_key]
    save_countries_data()

    # Show confirmation as popup
    await query.answer(f"✅ {country_name} deleted!", show_alert=False)

    # Refresh the delete country page with updated list
    delete_country_text = f"""
🗑️ **Delete Country**

✅ **Deleted:** {country_name}

Select another country to delete:

⚠️ Warning: This will permanently remove the country from the sell list!
"""

    # Get all countries sorted by sell price (descending for better visibility)
    all_countries = list(COUNTRIES_DATA.keys())
    all_countries.sort(key=lambda x: COUNTRIES_DATA[x]['sell_price'], reverse=True)

    # Create keyboard with 2 countries per row
    keyboard = []
    for i in range(0, len(all_countries), 2):
        row = []
        for j in range(2):
            if i + j < len(all_countries):
                ck = all_countries[i + j]
                if ck in COUNTRIES_DATA:
                    cd = COUNTRIES_DATA[ck]
                    sell_price = cd['sell_price']
                    name = cd['name']
                    if len(name) > 15:
                        name = name[:12] + "..."
                    button_text = f"{name} ${sell_price}"
                    row.append(InlineKeyboardButton(button_text, callback_data=f"admin_del_country_{ck}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(delete_country_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_admin_new_country_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin new country name input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    country_name = update.message.text.strip()
    
    # Validate input
    if len(country_name) > 50 or len(country_name) < 3:
        await update.message.reply_text("❌ Country name must be between 3-50 characters!")
        return

    # Store country name and ask for price
    context.user_data['new_country_name'] = country_name
    
    price_request_text = f"""
💰 **Set Sell Price**

🌍 **Country:** {country_name}

Enter the sell price for this country (USD):

Example: 1.50

Note: Buy price will be automatically calculated as 30% higher.
"""

    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_sell_price_control")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(price_request_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_admin_new_country_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin new country price input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    country_name = context.user_data.get('new_country_name')
    if not country_name:
        await update.message.reply_text("❌ Country name not found!")
        return

    try:
        price_input = update.message.text.strip()
        sell_price = float(price_input)
        
        # Validate price range
        if sell_price <= 0:
            await update.message.reply_text("❌ Price must be greater than zero!")
            return
        if sell_price > 1000:
            await update.message.reply_text("❌ Price cannot exceed $1000 USD!")
            return
        if len(price_input.split('.')) > 1 and len(price_input.split('.')[1]) > 2:
            await update.message.reply_text("❌ Price can have maximum 2 decimal places!")
            return
            
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number! Example: 1.50")
        return

    # Create new country key
    new_country_key = country_name.lower().replace(' ', '_').replace('🇧🇩', '').replace('🇵🇰', '').replace('🇮🇳', '').replace('🇺🇸', '').replace('🇬🇧', '').strip()
    
    # Calculate buy price (30% higher)
    buy_price = round(sell_price * 1.3, 2)
    
    # Add to COUNTRIES_DATA
    COUNTRIES_DATA[new_country_key] = {
        'name': country_name,
        'sell_price': sell_price,
        'buy_price': buy_price
    }
    save_countries_data()

    success_text = f"""
✅ **New Country Added Successfully!**

🌍 **Country:** {country_name}
💰 **Sell Price:** ${sell_price} USD
💰 **Buy Price:** ${buy_price} USD (auto-calculated)

This country is now available for users to buy/sell accounts!
"""

    keyboard = [
        [InlineKeyboardButton("🆕 Add Another Country", callback_data="admin_add_new_country")],
        [InlineKeyboardButton("🔙 Price Control", callback_data="admin_sell_price_control")],
        [InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Clear context
    context.user_data.pop('admin_add_new_country', None)
    context.user_data.pop('new_country_name', None)

async def admin_buy_price_control_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin buy price control callback"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    price_control_text = """
🛒 **Buy Account Price Control**

Change country buy prices. Write the country name in English:

Examples:
• bangladesh
• usa  
• germany

Please enter the country name:
"""

    context.user_data['admin_buy_price_control'] = True
    keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(price_control_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_price_control_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin price control callback (legacy - should not be used)"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    price_control_text = """
🔧 **Price Control Panel**

Change country prices. Write the country name in English:

Examples:
• bangladesh
• usa  
• germany

Please enter the country name:
"""

    context.user_data['admin_price_control'] = True
    keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(price_control_text, reply_markup=reply_markup, parse_mode='Markdown')

async def approve_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin approval for sell request"""
    query = update.callback_query
    await query.answer()

    admin_id = str(query.from_user.id)
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("❌ Access Denied!", show_alert=True)
        return

    # Parse callback data: approve_sell_{user_id}_{price}
    data_parts = query.data.split('_')
    if len(data_parts) != 4:
        await query.answer("❌ Invalid Data!", show_alert=True)
        return

    user_id = data_parts[2]
    price = float(data_parts[3])

    # Mark as approved in user context
    # Note: ConversationHandler state is per user/chat, so we need to access the correct context
    # However, since the user is in WAITING_FOR_ADMIN_APPROVAL state, we can set it in their user_data
    # We'll use the dispatcher/application context if possible, but for now we rely on the bot's ability to store it.
    
    # In python-telegram-bot, context.application.user_data[int(user_id)] is the way to access it
    context.application.user_data[int(user_id)]['admin_approved'] = True
    context.application.user_data[int(user_id)]['approval_time'] = datetime.now()

    # Get country info for the notification
    user_context = context.application.user_data[int(user_id)]
    country_data = user_context.get('country_data', {})
    country_name = country_data.get('name', 'Unknown')
    user_number = user_context.get('user_number', 'Unknown')

    # Update admin message
    approved_text = f"""
✅ **Sell Request Approved!**

👤 **User:** {user_id}
💰 **Price:** ${price} USD
📈 **Status:** Approved - Waiting for user's OTP
"""

    await query.edit_message_text(approved_text, parse_mode='Markdown')

    # Notify user to continue with OTP
    try:
        # NOTE: We no longer create a processing entry here.
        # It will be created ONLY when admin confirms the OTP.

        keyboard = [[InlineKeyboardButton("❌ Cancel Sale", callback_data="cancel_sale_otp")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ **Your request has been approved!**\n\nPlease enter the **verification code (OTP)** sent to your Telegram account for number:\n🌍 **Country:** {country_name}\n📞 `{user_number}`\n\n💰 Once verified, ${price} USD will be added to your balance.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

async def reject_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection for sell request"""
    query = update.callback_query
    await query.answer()

    admin_id = str(query.from_user.id)
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("❌ Access Denied!", show_alert=True)
        return

    # Parse callback data: reject_sell_{user_id}
    data_parts = query.data.split('_')
    if len(data_parts) != 3:
        await query.answer("❌ Invalid Data!", show_alert=True)
        return

    user_id = data_parts[2]

    # Update admin message
    rejected_text = f"""
❌ **Sell Request Rejected!**

👤 **User:** {user_id}
🚫 **Status:** Rejected - User cannot proceed
"""

    await query.edit_message_text(rejected_text, parse_mode='Markdown')

    # Reset user state and force end conversation
    user_id_int = int(user_id)
    if user_id_int in context.application.user_data:
        context.application.user_data[user_id_int].clear()
    
    # Ensure page is reset when entering sell flow
    if 'sell_page' in context.user_data:
        context.user_data.pop('sell_page')
    
    # End conversation for the user
    context.application.drop_user_data(user_id_int)

    # Notify user of rejection
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ **Sell Failed!**\n\nYour account sell request has been rejected. Please try again later.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

async def reject_sms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection with SMS for sell request"""
    query = update.callback_query
    await query.answer()

    admin_id = str(query.from_user.id)
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("Access Denied!", show_alert=True)
        return

    # Parse callback data: reject_sms_{user_id}
    data_parts = query.data.split('_')
    if len(data_parts) != 3:
        await query.answer("Invalid Data!", show_alert=True)
        return

    user_id = data_parts[2]

    # Store user_id for SMS and ask admin to write message
    context.user_data['reject_sms_user_id'] = user_id

    sms_text = f"""
📩 **Reject with SMS**

👤 **User:** {user_id}

Please write the rejection message to send to the user:
"""

    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(sms_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_reject_sms_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection SMS message input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    user_id = context.user_data.get('reject_sms_user_id')
    if not user_id:
        return

    message = update.message.text.strip()

    # Send rejection message to user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ **Sell Failed!**\n\n{message}",
            parse_mode='Markdown'
        )

        # Confirm to admin
        await update.message.reply_text(
            f"✅ **Rejection sent!**\n\n👤 User: {user_id}\n📩 Message: {message}",
            parse_mode='Markdown'
        )

        # Reset user state and force end conversation
        user_id_int = int(user_id)
        if user_id_int in context.application.user_data:
            context.application.user_data[user_id_int].clear()
        
        # End conversation for the user
        context.application.drop_user_data(user_id_int)

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message: {e}")
        logger.error(f"Failed to send reject SMS to user {user_id}: {e}")

    # Clear context
    context.user_data.pop('reject_sms_user_id', None)

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin approval for completed account"""
    query = update.callback_query
    await query.answer()

    admin_id = str(query.from_user.id)
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("❌ Access Denied!", show_alert=True)
        return

    # Parse callback data: approve_{user_id}_{amount}
    data_parts = query.data.split('_')
    if len(data_parts) != 3:
        await query.answer("❌ Invalid Data!", show_alert=True)
        return

    user_id = data_parts[1]
    amount = float(data_parts[2])

    # Move from hold to main balance
    referrer_id = None
    referral_commission = 0.0
    
    with user_data_lock:
        if user_id not in user_data:
            await query.answer("❌ User not found!", show_alert=True)
            return
        
        # Admin manually approving moves from hold to main
        # We check hold balance
        if user_data[user_id]['hold_balance_usdt'] >= amount:
            old_hold = user_data[user_id]['hold_balance_usdt']
            old_main = user_data[user_id]['main_balance_usdt']
            user_data[user_id]['hold_balance_usdt'] -= amount
            user_data[user_id]['main_balance_usdt'] += amount
            user_data[user_id]['last_activity'] = datetime.now().isoformat()
            logger.info(f"Transferred {amount} for user {user_id}: Hold {old_hold}->{user_data[user_id]['hold_balance_usdt']}, Main {old_main}->{user_data[user_id]['main_balance_usdt']}")
            
            # Get updated balances for display
            current_hold = user_data[user_id]['hold_balance_usdt']
            current_main = user_data[user_id]['main_balance_usdt']
            
            # Process 3% referral commission
            referrer_id = user_data[user_id].get('referrer_id')
            if referrer_id and referrer_id in user_data:
                referral_commission = amount * 0.03
                user_data[referrer_id]['main_balance_usdt'] += referral_commission
                user_data[referrer_id]['referral_earnings'] += referral_commission
                logger.info(f"Referral commission: ${referral_commission:.4f} to {referrer_id} from user {user_id}'s income of ${amount}")
            
            save_user_data()
        else:
            # Fallback if hold is less than amount (e.g. admin error)
            await query.answer("❌ Insufficient Hold Balance!", show_alert=True)
            return

    # Update the admin message
    approved_text = f"""
✅ **Approval Completed!**

👤 **User:** {user_id}
💰 **Amount:** ${amount} USD
📈 **Hold → Main Balance Transferred**

⏳ **Current Hold:** {current_hold:.2f} USDT
💰 **Current Main:** {current_main:.2f} USDT
"""

    await query.edit_message_text(approved_text, parse_mode='Markdown')

    # Notify user
    try:
        # Get the number if available from context or user data
        sold_numbers = user_data[user_id].get('sold_numbers', [])
        number_info = f"\n📱 **Sold Number:** `{sold_numbers[-1]}`" if sold_numbers else ""

        success_text = (
            "🎊 **CONGRATULATIONS! SELL COMPLETED** 🎊\n\n"
            "Your account sale has been successfully approved by the administrator! ✅\n\n"
            f"💰 **Amount Added:** `${amount} USD`\n"
            f"{number_info}\n"
            "💳 **Status:** Successfully Completed\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✨ **Balance Update Details:**\n"
            "📥 **Hold Balance:** Amount has been deducted\n"
            "📤 **Main Balance:** Amount has been added\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "The funds are now available in your **Main Balance** for withdrawal. Even a beginner can understand that your hard-earned money is now ready to use! 🚀\n\n"
            "Thank you for choosing our service! 🙏"
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=success_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    # Notify referrer about commission
    if referrer_id and referral_commission > 0:
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"💰 **Referral Commission!**\n\nYou earned ${referral_commission:.4f} (3%) from your referral's income!",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify referrer {referrer_id}: {e}")

async def reject_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection for PIN submission"""
    query = update.callback_query
    await query.answer()

    admin_id = str(query.from_user.id)
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("Access Denied!", show_alert=True)
        return

    # Parse callback data: reject_pin_{user_id}_{price}
    data_parts = query.data.split('_')
    if len(data_parts) != 4:
        await query.answer("Invalid Data!", show_alert=True)
        return

    user_id = data_parts[2]
    price = float(data_parts[3])

    # Deduct the rejected amount from hold balance
    with user_data_lock:
        if user_id in user_data:
            user_data[user_id]['hold_balance_usdt'] = max(0, user_data[user_id]['hold_balance_usdt'] - price)
            current_hold = user_data[user_id]['hold_balance_usdt']
        else:
            current_hold = 0.0
    save_user_data()

    # Update admin message
    rejected_text = f"""
❌ **PIN Request Rejected!**

👤 **User:** {user_id}
💰 **Deducted:** ${price} USD
⏳ **Current Hold Balance:** ${current_hold:.2f} USD
🚫 **Status:** Rejected
"""

    await query.edit_message_text(rejected_text, parse_mode='Markdown')

    # Notify user with detailed message
    user_message = f"""
❌ **Account Rejected!**

Your account sell request has been rejected.
💰 **${price} USD** has been deducted from your Hold Balance.

⏳ Please try again after a few hours or try with a different number.

Use the buttons below to continue:
"""
    keyboard = [
        [InlineKeyboardButton("💰 Check Balance", callback_data="balance")],
        [InlineKeyboardButton("🔙 Sell Another Account", callback_data="sell_account")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

async def reject_pin_sms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection with SMS for PIN submission"""
    query = update.callback_query
    await query.answer()

    admin_id = str(query.from_user.id)
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("Access Denied!", show_alert=True)
        return

    # Parse callback data: reject_pin_sms_{user_id}_{price}
    data_parts = query.data.split('_')
    if len(data_parts) != 5:
        await query.answer("Invalid Data!", show_alert=True)
        return

    user_id = data_parts[3]
    price = float(data_parts[4])

    # Store user_id and price for SMS
    context.user_data['reject_pin_sms_user_id'] = user_id
    context.user_data['reject_pin_sms_price'] = price

    sms_text = f"""
📩 **Reject PIN with SMS**

👤 **User:** {user_id}
💰 **Price:** ${price} USD

Please write the rejection message to send to the user:
"""

    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(sms_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_reject_pin_sms_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin rejection PIN SMS message input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    user_id = context.user_data.get('reject_pin_sms_user_id')
    price = context.user_data.get('reject_pin_sms_price', 0.0)
    if not user_id:
        return

    message = update.message.text.strip()

    # Deduct the rejected amount from hold balance
    with user_data_lock:
        if user_id in user_data:
            user_data[user_id]['hold_balance_usdt'] = max(0, user_data[user_id]['hold_balance_usdt'] - price)
            current_hold = user_data[user_id]['hold_balance_usdt']
        else:
            current_hold = 0.0
    save_user_data()

    # Send rejection message to user with balance info
    user_message = f"""
❌ **Account Rejected!**

{message}

💰 **${price} USD** has been deducted from your Hold Balance.

⏳ Please try again after a few hours or try with a different number.
"""
    keyboard = [
        [InlineKeyboardButton("💰 Check Balance", callback_data="balance")],
        [InlineKeyboardButton("🔙 Sell Another Account", callback_data="sell_account")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        # Confirm to admin
        await update.message.reply_text(
            f"✅ **Rejection sent!**\n\n👤 User: {user_id}\n💰 Deducted: ${price} USD\n⏳ Current Hold: ${current_hold:.2f} USD\n📩 Message: {message}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message: {e}")
        logger.error(f"Failed to send reject PIN SMS to user {user_id}: {e}")

    # Clear context
    context.user_data.pop('reject_pin_sms_user_id', None)
    context.user_data.pop('reject_pin_sms_price', None)

async def admin_balance_control_start(update: Update, context: ContextTypes.DEFAULT_TYPE, balance_type: str) -> None:
    """Start admin balance control process"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ Access Denied!")
        return

    balance_name = "Main Balance" if balance_type == 'main' else "Hold Balance"

    control_text = f"""
🔧 **{balance_name} Control**

Please provide the user's **Chat ID**:

Example: 123456789

⚠️ **Note:** Chat ID must be correct.
"""

    keyboard = [[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Store balance type in context
    context.user_data['admin_balance_type'] = balance_type

    await query.edit_message_text(control_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_admin_user_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin user ID input for balance control"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    user_id = update.message.text.strip()

    # Validate user ID
    if not user_id.isdigit():
        await update.message.reply_text("❌ User ID must be a number!")
        return

    # Get or create user data (allows adding balance to users who haven't started bot yet)
    user_info = get_user_data(user_id)
    balance_type = context.user_data.get('admin_balance_type', 'main')
    balance_name = "Main Balance" if balance_type == 'main' else "Hold Balance"
    current_balance = user_info['main_balance_usdt'] if balance_type == 'main' else user_info['hold_balance_usdt']

    balance_info_text = f"""
💳 **{balance_name} Control**

👤 **User ID:** {user_id}
💰 **Current {balance_name}:** {current_balance:.2f} USDT

What would you like to do?
"""

    keyboard = [
        [
            InlineKeyboardButton("➕ Add Balance", callback_data=f"admin_add_{balance_type}_{user_id}"),
            InlineKeyboardButton("➖ Remove Balance", callback_data=f"admin_remove_{balance_type}_{user_id}")
        ],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(balance_info_text, reply_markup=reply_markup, parse_mode='Markdown')

async def admin_add_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin add/remove balance callback"""
    query = update.callback_query
    await query.answer()

    admin_id = str(query.from_user.id)
    if admin_id != ADMIN_CHAT_ID:
        await query.answer("❌ Access Denied!", show_alert=True)
        return

    # Parse callback data: admin_{action}_{balance_type}_{user_id}
    data_parts = query.data.split('_')
    if len(data_parts) != 4:
        await query.answer("❌ Invalid Data!", show_alert=True)
        return

    action = data_parts[1]  # add or remove
    balance_type = data_parts[2]  # main or hold
    user_id = data_parts[3]

    action_text = "Add" if action == 'add' else "Remove"
    balance_name = "Main Balance" if balance_type == 'main' else "Hold Balance"

    amount_request_text = f"""
💰 **{action_text} {balance_name}**

👤 **User ID:** {user_id}

Please enter amount (USD):

Example: 10.50
"""

    # Store operation details in context
    context.user_data['admin_operation'] = {
        'action': action,
        'balance_type': balance_type,
        'user_id': user_id
    }

    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(amount_request_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_admin_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin amount input for balance control"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    operation = context.user_data.get('admin_operation')
    if not operation:
        await update.message.reply_text("❌ Operation data not found!")
        return

    try:
        amount_input = update.message.text.strip()
        amount = float(amount_input)
        
        # Validate amount range
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than zero!")
            return
        if amount > 100000:
            await update.message.reply_text("❌ Amount cannot exceed $100,000 USD!")
            return
        if len(amount_input.split('.')) > 1 and len(amount_input.split('.')[1]) > 2:
            await update.message.reply_text("❌ Amount can have maximum 2 decimal places!")
            return
            
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number! Example: 100.50")
        return

    user_id = operation['user_id']
    action = operation['action']
    balance_type = operation['balance_type']

    # Get or create user data (allows adding balance to users who haven't started bot yet)
    get_user_data(user_id)
    
    # Update user balance with thread safety
    with user_data_lock:
        user_info = user_data[user_id]
            
        balance_field = 'main_balance_usdt' if balance_type == 'main' else 'hold_balance_usdt'
        balance_name = "Main Balance" if balance_type == 'main' else "Hold Balance"

        if action == 'add':
            user_info[balance_field] += amount
            action_text = "added"
        else:  # remove
            if user_info[balance_field] >= amount:
                user_info[balance_field] -= amount
                action_text = "removed"
            else:
                await update.message.reply_text(f"❌ Insufficient balance! Current: {user_info[balance_field]:.2f} USDT")
                return

    save_user_data()

    success_text = f"""
✅ **Operation Successful!**

👤 **User ID:** {user_id}
💰 **Amount:** ${amount:.2f} USD {action_text}
💳 **New {balance_name}:** {user_info[balance_field]:.2f} USDT
"""

    keyboard = [
        [InlineKeyboardButton("🔄 More Operations", callback_data=f"admin_{balance_type}_balance")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💰 Your {balance_name} has been updated!\n\n${amount:.2f} USD {action_text}\nNew balance: {user_info[balance_field]:.2f} USDT"
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")

    # Clear context
    context.user_data.pop('admin_operation', None)

async def handle_admin_price_control_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin price control country input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    country_input = update.message.text.strip().lower()

    # Determine if this is buy or sell price control
    is_sell_control = 'admin_sell_price_control' in context.user_data
    is_buy_control = 'admin_buy_price_control' in context.user_data
    
    # Validate country input
    if len(country_input) > 50 or not country_input.replace('_', '').replace(' ', '').isalpha():
        await update.message.reply_text("❌ Invalid country name format!")
        return
    
    # Find country in COUNTRIES_DATA
    found_country = None
    for country_key, country_data in COUNTRIES_DATA.items():
        if country_key == country_input or country_input in country_data['name'].lower():
            found_country = (country_key, country_data)
            break

    if found_country:
        country_key, country_data = found_country
        
        if is_sell_control:
            price_type = "Sell"
            current_price = country_data['sell_price']
            context.user_data['price_control_type'] = 'sell'
        elif is_buy_control:
            price_type = "Buy"
            current_price = country_data['buy_price']
            context.user_data['price_control_type'] = 'buy'
        else:
            # Legacy support
            price_type = "General"
            current_price = country_data.get('price', country_data['sell_price'])
            context.user_data['price_control_type'] = 'general'
            
        control_text = f"""
💰 **{price_type} Price Change**

🌍 **Country:** {country_data['name']}
💵 **Current {price_type} Price:** ${current_price} USD

Enter new {price_type.lower()} price (USD):

Example: 1.50
"""
        context.user_data['price_control_country'] = country_key
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(control_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        # Country not found, offer to add new country
        if is_sell_control:
            price_type = "Sell"
            context.user_data['price_control_type'] = 'sell'
        elif is_buy_control:
            price_type = "Buy"
            context.user_data['price_control_type'] = 'buy'
        else:
            price_type = "Sell"
            context.user_data['price_control_type'] = 'sell'
            
        add_country_text = f"""
🆕 **Add New Country for {price_type}**

🌍 **Country:** {country_input.title()}
❓ **Status:** New country (not in current list)

Enter the {price_type.lower()} price for this new country (USD):

Example: 1.50

Note: This will add '{country_input.title()}' to the available countries list.
"""
        # Store the new country data
        context.user_data['new_country_name'] = country_input
        context.user_data['price_control_country'] = 'new_country'
        
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(add_country_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_admin_price_change_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin price change input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    country_key = context.user_data.get('price_control_country')
    price_type = context.user_data.get('price_control_type', 'general')
    
    if not country_key:
        await update.message.reply_text("❌ Country data not found!")
        return

    try:
        price_input = update.message.text.strip()
        new_price = float(price_input)
        
        # Validate price range
        if new_price <= 0:
            await update.message.reply_text("❌ Price must be greater than zero!")
            return
        if new_price > 1000:
            await update.message.reply_text("❌ Price cannot exceed $1000 USD!")
            return
        if len(price_input.split('.')) > 1 and len(price_input.split('.')[1]) > 2:
            await update.message.reply_text("❌ Price can have maximum 2 decimal places!")
            return
            
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number! Example: 1.50")
        return

    # Check if this is a new country or existing country update
    if country_key == 'new_country':
        # Adding a new country
        new_country_name = context.user_data.get('new_country_name', 'Unknown')
        
        # Create appropriate emoji flag (simplified version)
        country_display_name = new_country_name.title()
        if '🇧🇩' not in country_display_name and 'bangladesh' in new_country_name.lower():
            country_display_name = f"Bangladesh 🇧🇩"
        elif not any(char in country_display_name for char in ['🇺🇸', '🇬🇧', '🇩🇪', '🇫🇷', '🇮🇳', '🇧🇩']):
            country_display_name = f"{country_display_name} 🌍"
        
        # Create new country key
        new_country_key = new_country_name.lower().replace(' ', '_')
        
        # Add to COUNTRIES_DATA
        if price_type == 'sell':
            COUNTRIES_DATA[new_country_key] = {
                'name': country_display_name,
                'sell_price': new_price,
                'buy_price': round(new_price * 1.3, 2)  # Auto-calculate buy price 30% higher
            }
            price_label = "Sell Price"
            next_callback = "admin_sell_price_control"
        elif price_type == 'buy':
            COUNTRIES_DATA[new_country_key] = {
                'name': country_display_name,
                'sell_price': round(new_price / 1.3, 2),  # Auto-calculate sell price 30% lower
                'buy_price': new_price
            }
            price_label = "Buy Price"
            next_callback = "admin_buy_price_control"
        else:
            COUNTRIES_DATA[new_country_key] = {
                'name': country_display_name,
                'sell_price': new_price,
                'buy_price': round(new_price * 1.3, 2)
            }
            price_label = "Price"
            next_callback = "admin_price_control"
        
        save_countries_data()
        
        success_text = f"""
✅ **New Country Added Successfully!**

🌍 **Country:** {country_display_name}
💰 **{price_label}:** ${new_price} USD
💰 **Auto-calculated {'Buy' if price_type == 'sell' else 'Sell'} Price:** ${COUNTRIES_DATA[new_country_key]['buy_price'] if price_type == 'sell' else COUNTRIES_DATA[new_country_key]['sell_price']} USD

This country is now available for users to buy/sell accounts!
"""
    else:
        # Update existing country price
        if price_type == 'sell':
            old_price = COUNTRIES_DATA[country_key]['sell_price']
            COUNTRIES_DATA[country_key]['sell_price'] = new_price
            price_label = "Sell Price"
            next_callback = "admin_sell_price_control"
        elif price_type == 'buy':
            old_price = COUNTRIES_DATA[country_key]['buy_price']
            COUNTRIES_DATA[country_key]['buy_price'] = new_price
            price_label = "Buy Price"
            next_callback = "admin_buy_price_control"
        else:
            # Legacy support - update sell_price for backward compatibility
            old_price = COUNTRIES_DATA[country_key].get('price', COUNTRIES_DATA[country_key]['sell_price'])
            COUNTRIES_DATA[country_key]['sell_price'] = new_price
            price_label = "Price"
            next_callback = "admin_price_control"

        save_countries_data()

        success_text = f"""
✅ **{price_label} Update Complete!**

🌍 **Country:** {COUNTRIES_DATA[country_key]['name']}
💰 **Old {price_label}:** ${old_price} USD
💰 **New {price_label}:** ${new_price} USD
"""

    keyboard = [
        [InlineKeyboardButton(f"🔄 More {price_label} Changes", callback_data=next_callback)],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Clear context
    context.user_data.pop('price_control_country', None)
    context.user_data.pop('price_control_type', None)
    context.user_data.pop('admin_sell_price_control', None)
    context.user_data.pop('admin_buy_price_control', None)
    context.user_data.pop('admin_price_control', None)
    context.user_data.pop('new_country_name', None)

async def handle_admin_sms_all_users_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin SMS all users message input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    message_text = update.message.text.strip()

    # Send message to all users
    sent_count = 0
    failed_count = 0

    for user_id in user_data.keys():
        try:
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"📩 **Message from Admin:**\n\n{message_text}",
                parse_mode='Markdown'
            )
            sent_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to send message to user {user_id}: {e}")

    success_text = f"""
✅ **SMS Sent Successfully!**

📊 **Statistics:**
• Messages sent: {sent_count}
• Failed to send: {failed_count}
• Total users: {len(user_data)}

📩 **Message sent:**
{message_text}
"""

    keyboard = [
        [InlineKeyboardButton("📩 Send More SMS", callback_data="admin_send_sms")],
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Clear context
    context.user_data.pop('admin_sms_all_users', None)

async def handle_admin_sms_single_user_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin SMS single user ID input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    try:
        target_user_id = int(update.message.text.strip())
        context.user_data['sms_target_user'] = target_user_id

        await update.message.reply_text(
            f"👤 **Target User ID:** {target_user_id}\n\n📝 **Now write the message:**\n\nExample: Hello! How are you doing?",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid numeric User ID!")

async def handle_admin_sms_single_user_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin SMS single user message input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    target_user_id = context.user_data.get('sms_target_user')
    message_text = update.message.text.strip()

    try:
        await context.bot.send_message(
            chat_id=target_user_id, 
            text=f"📩 **Message from Admin:**\n\n{message_text}",
            parse_mode='Markdown'
        )

        success_text = f"""
✅ **SMS Sent Successfully!**

👤 **Target User:** {target_user_id}
📩 **Message:** {message_text}
"""

        keyboard = [
            [InlineKeyboardButton("📩 Send More SMS", callback_data="admin_send_sms")],
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message to user {target_user_id}: {str(e)}")

    # Clear context
    context.user_data.pop('sms_target_user', None)
    context.user_data.pop('admin_sms_single_user', None)

async def handle_admin_chat_user_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin chat user ID input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    try:
        target_user_id = int(update.message.text.strip())
        context.user_data['chat_target_user'] = target_user_id

        await update.message.reply_text(
            f"💬 **Chat Started with User:** {target_user_id}\n\n📝 **Write your message:**\n\nExample: Hi there! I'm here to help you.",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid numeric User ID!")

async def handle_admin_chat_user_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin chat user message input"""
    if not update.message or not update.message.text:
        return

    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    target_user_id = context.user_data.get('chat_target_user')
    message_text = update.message.text.strip()

    try:
        # Create reply button for user
        keyboard = [[InlineKeyboardButton("💬 Reply to Admin", callback_data=f"reply_admin_{admin_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=target_user_id, 
            text=f"💬 **Message from Admin:**\n\n{message_text}",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

        await update.message.reply_text(
            f"✅ **Message sent to user {target_user_id}**\n\n📩 **Your message:** {message_text}\n\n💬 **Chat is active - send more messages or go back to admin panel.**",
            parse_mode='Markdown'
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message to user {target_user_id}: {str(e)}")
        # Clear context on error
        context.user_data.pop('chat_target_user', None)
        context.user_data.pop('admin_chat_user', None)

async def reply_to_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user reply to admin"""
    query = update.callback_query
    await query.answer()

    # Extract admin ID from callback data
    admin_id = query.data.split('_')[-1]

    reply_text = """
💬 **Reply to Admin**

Write your message to send to the admin:

Example: Thank you for your help! I have a question about...

Please type your reply:
"""

    context.user_data['replying_to_admin'] = admin_id
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(reply_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_reply_to_admin_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user reply to admin message input"""
    if not update.message or not update.message.text:
        return

    admin_id = context.user_data.get('replying_to_admin')
    if not admin_id:
        return

    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "User"
    message_text = update.message.text.strip()

    try:
        # Send message to admin
        await context.bot.send_message(
            chat_id=admin_id, 
            text=f"💬 **Reply from User:**\n\n👤 **User:** {user_name} (ID: {user_id})\n📩 **Message:** {message_text}",
            parse_mode='Markdown'
        )

        # Confirm to user
        await update.message.reply_text(
            "✅ **Your reply has been sent to the admin!**\n\nThey will get back to you soon.",
            parse_mode='Markdown'
        )

    except Exception as e:
        await update.message.reply_text("❌ Failed to send your reply. Please try again later.")
        logger.error(f"Failed to send reply to admin {admin_id}: {e}")

    # Clear context
    context.user_data.pop('replying_to_admin', None)

async def admin_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route admin messages based on context"""
    admin_id = str(update.effective_user.id)
    if admin_id != ADMIN_CHAT_ID:
        return

    text = update.message.text.strip() if update.message and update.message.text else ""
    
    # Handle Reply Keyboard buttons for admin
    reply_keyboard_buttons = ["💸 Sell Account", "🏦 Withdrawal", "💰 Balance", "ℹ️ Safety & Terms"]
    if text in reply_keyboard_buttons:
        # Forward to handle_reply_keyboard logic
        logger.info(f"Reply Keyboard pressed: '{text}' by admin {admin_id}")
        
        class FakeQuery:
            def __init__(self, original_update):
                self.from_user = original_update.effective_user
                self.message = original_update.message
                self.data = None

            async def answer(self, text=None, show_alert=False):
                pass

            async def edit_message_text(self, text, **kwargs):
                await update.message.reply_text(text, **kwargs)

            async def edit_message_reply_markup(self, reply_markup=None):
                await update.message.reply_text("Choose an option:", reply_markup=reply_markup)

        class FakeUpdate:
            def __init__(self, original_update, fake_query):
                self.effective_user = original_update.effective_user
                self.effective_chat = original_update.effective_chat
                self.callback_query = fake_query

        fake_query = FakeQuery(update)
        fake_update = FakeUpdate(update, fake_query)

        if text == "💸 Sell Account":
            await sell_account_callback(fake_update, context)
        elif text == "🏦 Withdrawal":
            await withdrawal_callback(fake_update, context)
        elif text == "💰 Balance":
            await balance_callback(fake_update, context)
        elif text == "ℹ️ Safety & Terms":
            await terms_command(update, context)
        return

    # Check if admin is in operation mode
    if 'admin_operation' in context.user_data:
        await handle_admin_amount_input(update, context)
    elif 'admin_balance_type' in context.user_data:
        await handle_admin_user_id_input(update, context)
    elif 'admin_add_new_country' in context.user_data and 'new_country_name' not in context.user_data:
        await handle_admin_new_country_name_input(update, context)
    elif 'admin_add_new_country' in context.user_data and 'new_country_name' in context.user_data:
        await handle_admin_new_country_price_input(update, context)
    elif 'price_control_country' in context.user_data:
        await handle_admin_price_change_input(update, context)
    elif 'admin_sms_all_users' in context.user_data:
        await handle_admin_sms_all_users_input(update, context)
    elif 'admin_sms_single_user' in context.user_data and 'sms_target_user' not in context.user_data:
        await handle_admin_sms_single_user_id_input(update, context)
    elif 'sms_target_user' in context.user_data:
        await handle_admin_sms_single_user_message_input(update, context)
    elif 'admin_chat_user' in context.user_data and 'chat_target_user' not in context.user_data:
        await handle_admin_chat_user_id_input(update, context)
    elif 'chat_target_user' in context.user_data:
        await handle_admin_chat_user_message_input(update, context)
    elif 'admin_link_add' in context.user_data:
        await handle_admin_link_add_input(update, context)
    elif 'replying_to_admin' in context.user_data:
        await handle_reply_to_admin_message_input(update, context)
    elif 'admin_withdrawal_all_set' in context.user_data:
        await handle_admin_withdrawal_all_set_input(update, context)
    elif 'admin_withdrawal_custom_user' in context.user_data and 'withdrawal_limit_target_user' not in context.user_data:
        await handle_admin_withdrawal_custom_user_id_input(update, context)
    elif 'withdrawal_limit_target_user' in context.user_data:
        await handle_admin_withdrawal_custom_user_limit_input(update, context)
    elif 'reject_sms_user_id' in context.user_data:
        await handle_reject_sms_message_input(update, context)
    elif 'reject_pin_sms_user_id' in context.user_data:
        await handle_reject_pin_sms_message_input(update, context)
    # If no specific context, ignore the message

async def handle_buy_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle buying account from specific country"""
    query = update.callback_query
    await query.answer()

    # Extract country key from callback data: buy_country_{country_key}
    country_key = query.data.split('_', 2)[2]

    if country_key not in COUNTRIES_DATA:
        await query.edit_message_text("❌ Country data not found!")
        return

    country_data = COUNTRIES_DATA[country_key]
    # Calculate 30% higher price for buying
    buy_price = country_data['buy_price']

    user_id = str(query.from_user.id)
    user_info = get_user_data(user_id)

    # Check Top-Up balance (as per user requirement)
    if user_info['topup_balance_usdt'] >= buy_price:
        # Deduct from Top-Up balance and increment bought accounts
        user_info['topup_balance_usdt'] -= buy_price
        user_info['accounts_bought'] += 1
        save_user_data()

        success_text = f"""
✅ **Purchase Successful!**

🌍 **Country:** {country_data['name']}
💰 **Cost:** ${buy_price} USD
💳 **Current Top-Up Balance:** {user_info['topup_balance_usdt']:.2f} USDT

📧 Account details will be sent to your inbox soon.

🎉 Thank you for using our service!
"""
        keyboard = [
            [InlineKeyboardButton("🛒 Buy More", callback_data="buy_account")],
            [InlineKeyboardButton("💰 View Balance", callback_data="balance")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
    else:
        needed = buy_price - user_info['topup_balance_usdt']
        success_text = f"""
❌ **Insufficient Top-Up Balance!**

🌍 **Country:** {country_data['name']}
💰 **Required:** ${buy_price} USD
💳 **Your Top-Up Balance:** {user_info['topup_balance_usdt']:.2f} USDT
🔺 **Additional Required:** ${needed:.2f} USD

💳 Please top-up your balance first.
"""
        keyboard = [
            [InlineKeyboardButton("💳 Top-Up Balance", callback_data="topup")],
            [InlineKeyboardButton("💰 View Balance", callback_data="balance")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

async def placeholder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Placeholder for features under development"""
    query = update.callback_query
    await query.answer("This feature is coming soon! 🚧", show_alert=True)

async def handle_reply_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Reply Keyboard button presses"""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    logger.info(f"Reply Keyboard pressed: '{text}' by user {update.effective_user.id}")

    # Create a fake callback query object for compatibility with existing handlers
    class FakeQuery:
        def __init__(self, user_id):
            self.from_user = update.effective_user
            self.message = update.message
            self.data = None  # Add data attribute

        async def answer(self, text=None, show_alert=False):
            pass

        async def edit_message_text(self, text, **kwargs):
            await update.message.reply_text(text, **kwargs)

        async def edit_message_reply_markup(self, reply_markup=None):
            await update.message.reply_text("Choose an option:", reply_markup=reply_markup)

    # Create a simple fake update object
    class FakeUpdate:
        def __init__(self, original_update, fake_query):
            self.effective_user = original_update.effective_user
            self.effective_chat = original_update.effective_chat
            self.callback_query = fake_query

    fake_query = FakeQuery(update.effective_user.id)
    fake_update = FakeUpdate(update, fake_query)

    # Map Reply Keyboard buttons to callback functions
    if text == "💸 Sell Account":
        await sell_account_callback(fake_update, context)
    elif text == "🏦 Withdrawal":
        await withdrawal_callback(fake_update, context)
    elif text == "💰 Balance":
        await balance_callback(fake_update, context)
    elif text == "ℹ️ Safety & Terms":
        await terms_command(update, context)
    elif text == "👥 Refer & Earn":
        await refer_callback(fake_update, context)
    elif text == "📜 My History":
        await my_history_callback(fake_update, context)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main callback query handler"""
    query = update.callback_query
    data = query.data

    # Handle admin approval callbacks
    if data and data.startswith('approve_sell_'):
        await approve_sell_callback(update, context)
        return
    
    if data == 'cancel_sale_otp':
        context.user_data.pop('admin_approved', None)
        context.user_data.pop('user_number', None)
        context.user_data.pop('country_data', None)
        await query.edit_message_text("❌ Sale cancelled by user.")
        return
    if data and data.startswith('reject_sell_'):
        await reject_sell_callback(update, context)
        return
    if data and data.startswith('approve_'):
        await approve_callback(update, context)
        return

    # Handle admin add/remove balance callbacks
    if data and (data.startswith('admin_add_') or data.startswith('admin_remove_')):
        await admin_add_remove_callback(update, context)
        return

    # Handle buy country callbacks
    if data and data.startswith('buy_country_'):
        await handle_buy_country_callback(update, context)
        return
    
    # Handle admin edit sell price callbacks
    if data and data.startswith('admin_edit_sell_'):
        await admin_edit_sell_price_callback(update, context)
        return

    # Handle reply to admin callbacks
    if data and data.startswith('reply_admin_'):
        await reply_to_admin_callback(update, context)
        return

    handlers = {
        'balance': balance_callback,
        'my_history': my_history_callback,
        'buy_account': buy_account_callback,
        'sell_account': sell_account_callback,
        'topup': topup_callback,
        'withdrawal': withdrawal_callback,
        'buy_premium': buy_premium_callback,
        'buy_standard': buy_standard_callback,
        'buy_basic': buy_basic_callback,
        'main_menu': main_menu_callback,

        # Country region handlers
        'countries_europe': countries_europe_callback,
        'countries_asia': countries_asia_callback,
        'countries_africa': countries_africa_callback,
        'countries_america': countries_america_callback,
        'countries_others': countries_others_callback,

        # Admin handlers
        'admin_panel': admin_panel_callback,
        'admin_main_balance': lambda u, c: admin_balance_control_start(u, c, 'main'),
        'admin_hold_balance': lambda u, c: admin_balance_control_start(u, c, 'hold'),
        'admin_price_control': admin_price_control_callback,
        'admin_sell_price_control': admin_sell_price_control_callback,
        'admin_buy_price_control': admin_buy_price_control_callback,
        'admin_topup_info': admin_topup_info_callback,
        'admin_send_sms': admin_send_sms_callback,
        'admin_chat_user': admin_chat_user_callback,
        'admin_sms_all_users': admin_sms_all_users_callback,
        'admin_sms_single_user': admin_sms_single_user_callback,
        'admin_add_new_country': admin_add_new_country_callback,
        'admin_withdrawal_set': admin_withdrawal_set_callback,
        'admin_withdrawal_all_set': admin_withdrawal_all_set_callback,
        'admin_withdrawal_custom_user': admin_withdrawal_custom_user_callback,
        'admin_link_add': admin_link_add_callback,

        # Reply to admin handler  
        'reply_admin': reply_to_admin_callback,

        # Withdrawal method handlers
        'withdraw_binance': withdraw_binance_callback,
        'withdraw_payeer': withdraw_payeer_callback,
        'withdraw_trc20': withdraw_trc20_callback,
        'withdraw_bep20': withdraw_bep20_callback,
        'withdraw_paypal': withdraw_paypal_callback,
        'withdraw_bitcoin': withdraw_bitcoin_callback,
        'withdraw_cashapp': withdraw_cashapp_callback,
        'withdraw_upi': withdraw_upi_callback,
        'withdraw_bank': withdraw_bank_callback,

        # Top-up payment method handlers
        'topup_binance': topup_binance_callback,
        'topup_payeer': topup_payeer_callback,
        'topup_trc20': topup_trc20_callback,
        'topup_bep20': topup_bep20_callback,
        'topup_arbitrum': topup_arbitrum_callback,

        # Terms handler  
        'terms': lambda u, c: terms_command(u, c),

        # Refer handler
        'refer': refer_callback,

        # Placeholder handlers for other sub-features
        'submit_account': placeholder_callback,
    }

    handler = handlers.get(data, placeholder_callback)
    await handler(update, context)

async def pii_guard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guard against users accidentally sharing phone numbers or verification codes"""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Patterns to detect phone numbers and verification codes
    phone_patterns = [
        r'\+?\d{10,15}',  # Phone numbers with optional +
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # US format
        r'\(\d{3}\)\s?\d{3}[-.\s]?\d{4}',  # (xxx) xxx-xxxx format
    ]

    code_patterns = [
        r'^[0-9]{4,8}$',  # 4-8 digit codes
        r'\b[0-9]{4,8}\b',  # 4-8 digit codes in text
    ]

    # BGT Wallet exception - do not block codes/numbers if in sale flow
    if context.user_data.get('user_number') or context.user_data.get('admin_approved'):
        return

    # Check for phone numbers
    for pattern in phone_patterns:
        if re.search(pattern, text):
            warning_text = """
⚠️ **Security Warning!**

We do not collect phone numbers.

🚫 **Please do not share phone numbers.**

💡 This is a demo/test bot. All activities are for testing purposes only.

Return to main menu with /start.
"""
            await update.message.reply_text(warning_text, parse_mode='Markdown')
            return

    # Check for verification codes
    for pattern in code_patterns:
        if re.search(pattern, text):
            warning_text = """
⚠️ **Security Warning!**

We do not collect verification codes.

🚫 **Please do not share any codes.**

💡 This is a demo/test bot. No OTP or verification required.

Return to main menu with /start.
"""
            await update.message.reply_text(warning_text, parse_mode='Markdown')
            return

async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show safety terms and conditions"""
    terms_text = """
ℹ️ **Safety & Terms of Use for the Bot**

Thank you for using our bot! Before you proceed, please carefully read the following safety guidelines and terms of service. By using the bot, you are considered to have agreed to these terms.

🛡️ **Safety Guidelines**

We have established some rules to ensure a safe and positive environment for all users. Adherence to these rules is mandatory:

• **No Spamming:** Refrain from sending any form of spam or unnecessary messages using the bot.
• **Hate Speech and Harassment are Prohibited:** The bot must not be used to attack any race, religion, ethnicity, gender, or group, or to harass any individual.
• **Illegal Activities:** Using the bot for any illegal activities, such as making threats, engaging in fraud, or sharing illegal information, is strictly forbidden.
• **Abuse of the Bot:** Do not exploit any bugs or glitches in the bot or attempt to crash it.
• **Protection of Personal Information:** Do not attempt to collect or share the personal information of other users through the bot.

Violation of these rules may result in you being banned from using the bot.

📜 **Terms of Service**

**1. Acceptance of Terms:**
By using this bot, you fully agree to our Terms of Service. If you do not agree with these terms, you are requested not to use the bot.

**2. Data and Privacy:**
• **Data Collection:** To function correctly, the bot may collect some basic information, such as your User ID and Server ID. We do not collect your personal messages or any sensitive information.
• **Use of Data:** The collected data is used solely to improve the bot's functionality and enhance the user experience. We do not sell or share your data with any third parties.

**3. Changes and Termination of Service:**
We reserve the right to modify, suspend, or completely terminate the bot's services at any time without prior notice.

**4. Limitation of Liability:**
The bot is provided on an "as is" basis. The bot developer will not be liable for any direct or indirect damages to you or your server resulting from its use. We do not guarantee the bot's constant availability or accuracy.

**5. Changes to Terms:**
We reserve the right to change these terms from time to time. We will attempt to notify you of any major changes. Your continued use of the bot after any modifications will be considered your acceptance of the new terms.

Thank you again for using our bot. For any questions or feedback, please contact us.

Return to main menu with /start.
"""

    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(terms_text, reply_markup=reply_markup, parse_mode='Markdown')

async def check_broadcast_queue(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check for pending notifications from the web admin panel"""
    queue_file = 'broadcast_queue.json'
    if not os.path.exists(queue_file):
        return

    try:
        with open(queue_file, 'r') as f:
            queue = json.load(f)
            if not queue or not isinstance(queue, list):
                return
        
        # Clear the queue immediately to avoid double sending
        with open(queue_file, 'w') as f:
            json.dump([], f)
            
        for notification in queue:
            notify_type = notification.get('type', 'all')
            message = notification.get('message', '')
            if not message:
                continue
                
            if notify_type == 'custom':
                chat_id = notification.get('chat_id')
                if chat_id:
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                        logger.info(f"Custom notification sent to {chat_id}")
                    except Exception as e:
                        logger.error(f"Failed to send custom notification to {chat_id}: {e}")
            else:
                # Broadcast to all users
                user_ids = list(user_data.keys())
                success_count = 0
                for uid in user_ids:
                    try:
                        await context.bot.send_message(chat_id=int(uid), text=message, parse_mode='Markdown')
                        success_count += 1
                        # Small delay to avoid rate limiting
                        await asyncio.sleep(0.05)
                    except Exception:
                        continue
                logger.info(f"Broadcast sent to {success_count} users")
                
    except Exception as e:
        logger.error(f"Error in check_broadcast_queue: {e}")

def main() -> None:
    """Start the bot"""
    # Load all persistent data
    # Bot token - hardcoded for portability
    token = "8198086071:AAFi4JAb8t8dLN9fxn0Jidh_KlwV2jyYhA8"

    # Load data at startup
    load_user_data()
    load_withdrawal_settings()
    load_countries_data()
    
    # Verify countries data
    if not COUNTRIES_DATA:
        logger.error("COUNTRIES_DATA is empty at startup!")
    else:
        logger.info(f"COUNTRIES_DATA loaded with {len(COUNTRIES_DATA)} countries")

    # Create application
    application = Application.builder().token(token).build()

    # Manual background check since JobQueue might be missing or complex to install
    async def notification_worker():
        while True:
            try:
                # Create a fake context for the worker
                class FakeContext:
                    def __init__(self, bot):
                        self.bot = bot
                
                await check_broadcast_queue(FakeContext(application.bot))
            except Exception as e:
                logger.error(f"Error in notification_worker: {e}")
            await asyncio.sleep(10)

    # We'll start this task in the main loop or as a background task if possible
    # But since PTB 20+ uses asyncio, we can just spawn it
    import asyncio
    asyncio.get_event_loop().create_task(notification_worker())

    # Create conversation handler for sell account flow
    sell_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(country_selection_handler, pattern=r'^select_')],
        states={
            WAITING_FOR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number_input)],
            WAITING_FOR_ADMIN_APPROVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pin_input)],
            WAITING_FOR_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pin_input)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_sell_conversation, pattern=r'^sell_account$'),
            CommandHandler('start', start)
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
    )

    # Add pagination handler
    application.add_handler(CallbackQueryHandler(sell_pagination_handler, pattern=r'^sell_page_'))
    
    # Add handler for bot status buttons
    application.add_handler(CallbackQueryHandler(admin_bot_status_callback, pattern="^admin_bot_"))

    # Create conversation handler for withdrawal flow
    withdraw_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_method_selection, pattern=r'^withdraw_usdt_')],
        states={
            WAITING_FOR_WITHDRAW_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_address)],
            WAITING_FOR_WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_withdraw_amount)],
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(withdrawal_callback, pattern=r'^withdrawal$')
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("terms", terms_command))
    application.add_handler(sell_conversation)
    application.add_handler(withdraw_conversation)
    
    # Add explicit admin callback handlers (higher priority - before generic callback handler)
    application.add_handler(CallbackQueryHandler(admin_download_data_callback, pattern="^admin_download_data$"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: admin_balance_control_start(u, c, 'main'), pattern="^admin_main_balance$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: admin_balance_control_start(u, c, 'hold'), pattern="^admin_hold_balance$"))
    application.add_handler(CallbackQueryHandler(approve_sell_callback, pattern="^approve_sell_"))
    application.add_handler(CallbackQueryHandler(reject_sell_callback, pattern="^reject_sell_"))
    application.add_handler(CallbackQueryHandler(reject_sms_callback, pattern="^reject_sms_"))
    application.add_handler(CallbackQueryHandler(reject_pin_callback, pattern="^reject_pin_"))
    application.add_handler(CallbackQueryHandler(reject_pin_sms_callback, pattern="^reject_pin_sms_"))
    application.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_\d+_\d+(\.\d+)?$"))
    application.add_handler(CallbackQueryHandler(admin_sell_price_control_callback, pattern="^admin_sell_price_control$"))
    application.add_handler(CallbackQueryHandler(admin_buy_price_control_callback, pattern="^admin_buy_price_control$"))
    application.add_handler(CallbackQueryHandler(admin_topup_info_callback, pattern="^admin_topup_info$"))
    application.add_handler(CallbackQueryHandler(admin_send_sms_callback, pattern="^admin_send_sms$"))
    application.add_handler(CallbackQueryHandler(admin_chat_user_callback, pattern="^admin_chat_user$"))
    application.add_handler(CallbackQueryHandler(admin_link_add_callback, pattern="^admin_link_add$"))
    application.add_handler(CallbackQueryHandler(admin_add_new_country_callback, pattern="^admin_add_new_country$"))
    application.add_handler(CallbackQueryHandler(admin_delete_country_callback, pattern="^admin_delete_country$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_delete_country_callback, pattern="^admin_del_country_"))
    application.add_handler(CallbackQueryHandler(admin_withdrawal_set_callback, pattern="^admin_withdrawal_set$"))
    application.add_handler(CallbackQueryHandler(admin_withdrawal_all_set_callback, pattern="^admin_withdrawal_all_set$"))
    application.add_handler(CallbackQueryHandler(admin_withdrawal_custom_user_callback, pattern="^admin_withdrawal_custom_user$"))
    
    # Add OTP confirmation handlers
    application.add_handler(CallbackQueryHandler(confirm_otp_callback, pattern="^confirm_otp_"))
    application.add_handler(CallbackQueryHandler(wrong_otp_callback, pattern="^wrong_otp_"))
    application.add_handler(CallbackQueryHandler(final_approve_callback, pattern="^final_approve_"))
    application.add_handler(CallbackQueryHandler(final_reject_callback, pattern="^final_reject_"))
    
    # Generic callback handler (lower priority - catches remaining callbacks)
    application.add_handler(CallbackQueryHandler(callback_handler))

    # Add Reply Keyboard handler (higher priority - before other text handlers, but exclude admin messages)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Chat(ADMIN_CHAT_ID_INT), handle_reply_keyboard))

    # Add admin message router (medium priority)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Chat(ADMIN_CHAT_ID_INT), admin_message_router))

    # Add PII guard for all text messages (but not commands) - lower priority
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pii_guard_handler))

    # Log startup
    logger.info("Starting Telegram Account Trading Bot...")
    logger.info(f"Loaded data for {len(user_data)} existing users")

    # Start the bot
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
