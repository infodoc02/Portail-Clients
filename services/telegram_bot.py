# services/telegram_bot.py
"""بوت Telegram مع قفل ملف آمن وإعادة محاولة تلقائية"""

import threading
import time
import random
import os
import tempfile
import requests
import streamlit as st
import telebot
from telebot import types
from datetime import datetime

from services.firebase_service import get_firebase_service
from services.phone_utils import PhoneUtils

# ===== متغيرات عامة =====
_BOT_THREAD = None
_LOCK_FILE = os.path.join(tempfile.gettempdir(), "infodoc_bot.lock")

def _acquire_lock() -> bool:
    """محاولة الحصول على القفل، مع انتظار حتى 10 ثوانٍ إذا كان القفل موجوداً"""
    for _ in range(10):
        try:
            if os.path.exists(_LOCK_FILE):
                with open(_LOCK_FILE, "r") as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 0)
                    time.sleep(1)
                    continue
                except (OSError, ProcessLookupError):
                    os.remove(_LOCK_FILE)
            with open(_LOCK_FILE, "w") as f:
                f.write(str(os.getpid()))
            return True
        except Exception as e:
            print(f"⚠️ فشل الحصول على القفل: {e}")
            time.sleep(1)
    return False

def _release_lock():
    try:
        if os.path.exists(_LOCK_FILE):
            os.remove(_LOCK_FILE)
    except:
        pass

# ===== دوال البوت الأساسية =====
def _get_token() -> str:
    return st.secrets.get("TELEGRAM_TOKEN", "")

def _send_status_notification(bot, chat_id, device_data, status):
    try:
        device_id = device_data.get("ID", "غير معروف")
        appareil = device_data.get("Appareil", "")
        panne = device_data.get("Panne", "")
        prix = device_data.get("Prix", "0")

        status_messages = {
            "En attente": "⏳ في الانتظار",
            "En Cours": "🔧 قيد الفحص",
            "Réparable": "✅ قابل للإصلاح",
            "Non Réparable": "❌ غير قابل للإصلاح",
            "Prêt": "🎉 جاهز للتسليم",
            "Livré & Payé": "📦 تم التسليم",
            "Livré (Dette)": "📦 تم التسليم بدين",
            "Annulé": "🚫 ملغي",
        }
        status_text = status_messages.get(status, status)

        message = (
            f"📱 *تحديث حالة الجهاز*\n\n"
            f"💻 {appareil}\n"
            f"🎫 Ticket: {device_id}\n"
            f"📌 المشكلة: {panne}\n"
            f"📊 الحالة الجديدة: {status_text}\n"
        )

        markup = None
        if status == "Réparable":
            message += f"💰 السعر التقديري: {prix} دج\n\n"
            message += (
                f"🔔 *ملاحظة:* الجهاز قابل للصيانة. يرجى اختيار القبول أو الرفض من الأزرار أدناه أو من حسابك بالمنصة، "
                f"وليكن في علمك أنه في حالة الرفض ستكون ملزماً بدفع 1000 دج تكاليف الوقت و الفحص.\n"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            accept_btn = types.InlineKeyboardButton("✅ قبول التصليح", callback_data=f"ACCEPT_REPAIR_{device_id}")
            reject_btn = types.InlineKeyboardButton("❌ رفض التصليح", callback_data=f"REJECT_REPAIR_{device_id}")
            markup.add(accept_btn, reject_btn)

        if markup:
            bot.send_message(chat_id, message, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.send_message(chat_id, message, parse_mode="Markdown")
    except Exception as e:
        print(f"❌ خطأ في إرسال الإشعار: {e}")

def notify_customer_status_change(device_id, new_status, db_service):
    """إرسال إشعار للعميل بتغيير الحالة (يمكن استخدامها من لوحة الإدارة)"""
    try:
        token = _get_token()
        if not token:
            return False
        bot = telebot.TeleBot(token)
        ref_at = db_service.get_reference("atelier")
        if not ref_at:
            return False
        data_at = ref_at.get()
        if not data_at:
            return False
        device_data = None
        telegram_id = None
        for k, v in data_at.items():
            if v and v.get("ID") == device_id:
                device_data = v
                phone = v.get("Telephone", "")
                if phone:
                    ref_cl = db_service.get_reference("clients")
                    if ref_cl:
                        data_cl = ref_cl.get() or {}
                        for ck, cv in data_cl.items():
                            if cv and PhoneUtils.compare(cv.get("Telephone", ""), phone):
                                telegram_id = cv.get("Telegram_ID", cv.get("telegram_id", ""))
                                break
                break
        if not device_data or not telegram_id:
            return False
        _send_status_notification(bot, telegram_id, device_data, new_status)
        return True
    except Exception as e:
        print(f"❌ خطأ في notify_customer_status_change: {e}")
        return False

# ===== تسجيل المعالجات =====
def _register_handlers(bot, db_service):
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback(call):
        try:
            chat_id = str(call.message.chat.id)
            data = call.data

            if data.startswith("ACCEPT_REPAIR_"):
                device_id = data.replace("ACCEPT_REPAIR_", "")
                admin_id = st.secrets.get("MY_ADMIN_ID", "")

                ref_at = db_service.get_reference("atelier")
                if ref_at:
                    at_data = ref_at.get()
                    if at_data:
                        for k, v in at_data.items():
                            if v and str(v.get("ID")) == device_id:
                                client = v.get("Client", "غير معروف")
                                app = v.get("Appareil", "")
                                prix = v.get("Prix", "0")

                                # ✅ تحديث القرار في قاعدة البيانات
                                ref_at.child(k).update({"Decision": "accept"})

                                bot.answer_callback_query(call.id, "✅ تم إرسال موافقتك")
                                bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=call.message.message_id,
                                    text=f"✅ *تم قبول التصليح*\n\n💻 {app}\n🎫 Ticket: {device_id}\n💰 السعر: {prix} دج\n\nسيتم إبلاغ الورشة بموافقتك.",
                                    parse_mode="Markdown",
                                )
                                if admin_id:
                                    bot.send_message(
                                        admin_id,
                                        f"✅ *موافقة على التصليح*\n👤 {client}\n🎫 {device_id}\n💻 {app}\n💰 {prix} دج",
                                        parse_mode="Markdown",
                                    )
                                return

            elif data.startswith("REJECT_REPAIR_"):
                device_id = data.replace("REJECT_REPAIR_", "")
                admin_id = st.secrets.get("MY_ADMIN_ID", "")

                ref_at = db_service.get_reference("atelier")
                if ref_at:
                    at_data = ref_at.get()
                    if at_data:
                        for k, v in at_data.items():
                            if v and str(v.get("ID")) == device_id:
                                client = v.get("Client", "غير معروف")
                                app = v.get("Appareil", "")

                                # ✅ تحديث القرار في قاعدة البيانات
                                ref_at.child(k).update({"Decision": "reject", "Statut": "Annulé", "Prix": 1000})

                                bot.answer_callback_query(call.id, "ℹ️ تم إبلاغ الورشة برفضك")
                                bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=call.message.message_id,
                                    text=f"❌ *تم رفض التصليح*\n\n💻 {app}\n🎫 Ticket: {device_id}\n\n⚠️ *ملاحظة مهمة:* ستكون ملزماً بدفع 1000 دج حق الفحص.\n\nسيتم إبلاغ الورشة برفضك.",
                                    parse_mode="Markdown",
                                )
                                if admin_id:
                                    bot.send_message(
                                        admin_id,
                                        f"❌ *رفض التصليح*\n👤 {client}\n🎫 {device_id}\n💻 {app}",
                                        parse_mode="Markdown",
                                    )
                                return

            bot.answer_callback_query(call.id, "❌ لم يتم العثور على الجهاز")
        except Exception as e:
            print(f"Callback error: {e}")

    @bot.message_handler(commands=["start"])
    def handle_start(message):
        try:
            text_parts = message.text.split()
            chat_id = str(message.chat.id)
            if len(text_parts) > 1:
                phone = PhoneUtils.normalize(text_parts[1])
                if not phone or len(phone) < 10:
                    bot.send_message(chat_id, "❌ رقم الهاتف غير صالح")
                    return
                otp = str(random.randint(1000, 9999))
                otp_expiry = (datetime.now().replace(microsecond=0) + timedelta(minutes=5)).isoformat()
                found = False

                ref_at = db_service.get_reference("atelier")
                if ref_at:
                    data_at = ref_at.get()
                    if data_at:
                        for k, v in data_at.items():
                            if v and PhoneUtils.compare(v.get("Telephone", ""), phone):
                                ref_at.child(k).update({"Telegram_ID": chat_id})
                                found = True

                ref_cl = db_service.get_reference("clients")
                if ref_cl:
                    data_cl = ref_cl.get() or {}
                    existing = None
                    for k, v in data_cl.items():
                        if v and PhoneUtils.compare(v.get("Telephone", ""), phone):
                            existing = (k, v)
                            break
                    if existing:
                        ref_cl.child(existing[0]).update({
                            "Telegram_ID": chat_id,
                            "otp": otp,
                            "otp_expiry": otp_expiry,
                            "verified": False,
                            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        })
                        found = True
                    else:
                        ref_cl.push({
                            "Telephone": phone,
                            "Telegram_ID": chat_id,
                            "Client": "",
                            "otp": otp,
                            "otp_expiry": otp_expiry,
                            "verified": False,
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        })
                        found = True

                if found:
                    bot.send_message(
                        chat_id,
                        f"🔐 *رمز التحقق:* `{otp}`\n\n📱 ارجع إلى البوابة وأدخل الرمز (صالحة 5 دقائق).",
                        parse_mode="Markdown",
                    )
                else:
                    bot.send_message(chat_id, "❌ فشلت العملية.")
            else:
                markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
                markup.add(types.KeyboardButton("📲 Partager mon Numéro", request_contact=True))
                bot.send_message(
                    chat_id,
                    "👋 أهلاً بك! شارك رقم هاتفك للربط التلقائي.",
                    reply_markup=markup,
                )
        except Exception as e:
            print(f"Bot start error: {e}")

    @bot.message_handler(content_types=["contact"])
    def handle_contact(message):
        try:
            chat_id = str(message.chat.id)
            phone = PhoneUtils.normalize(message.contact.phone_number)
            if not phone or len(phone) < 10:
                bot.send_message(chat_id, "❌ رقم غير صالح")
                return
            otp = str(random.randint(1000, 9999))
            otp_expiry = (datetime.now().replace(microsecond=0) + timedelta(minutes=5)).isoformat()
            found = False

            ref_at = db_service.get_reference("atelier")
            if ref_at:
                data_at = ref_at.get()
                if data_at:
                    for k, v in data_at.items():
                        if v and PhoneUtils.compare(v.get("Telephone", ""), phone):
                            ref_at.child(k).update({"Telegram_ID": chat_id})
                            found = True

            ref_cl = db_service.get_reference("clients")
            if ref_cl:
                data_cl = ref_cl.get() or {}
                existing = None
                for k, v in data_cl.items():
                    if v and PhoneUtils.compare(v.get("Telephone", ""), phone):
                        existing = (k, v)
                        break
                if existing:
                    ref_cl.child(existing[0]).update({
                        "Telegram_ID": chat_id,
                        "otp": otp,
                        "otp_expiry": otp_expiry,
                        "verified": False,
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
                    found = True
                else:
                    ref_cl.push({
                        "Telephone": phone,
                        "Telegram_ID": chat_id,
                        "Client": "",
                        "otp": otp,
                        "otp_expiry": otp_expiry,
                        "verified": False,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
                    found = True

            if found:
                bot.send_message(
                    chat_id,
                    f"🔐 *رمز التحقق:* `{otp}`\n\n📱 ارجع إلى البوابة وأدخل الرمز (صالحة 5 دقائق).",
                    parse_mode="Markdown",
                )
            else:
                bot.send_message(chat_id, "❌ فشلت العملية.")
        except Exception as e:
            print(f"Contact error: {e}")

# ===== الوظيفة الرئيسية للبوت (مع إعادة محاولة 409) =====
def _bot_main():
    token = _get_token()
    if not token:
        print("⚠️ TELEGRAM_TOKEN مفقود")
        return

    # حذف webhook
    try:
        requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true", timeout=5)
        time.sleep(1)
    except:
        pass

    db_service = get_firebase_service()
    bot = telebot.TeleBot(token)
    _register_handlers(bot, db_service)

    # المستمع الداخلي
    previous_statuses = {}
    current_data = db_service.get_data("atelier")
    if current_data:
        for k, v in current_data.items():
            if v and v.get("ID"):
                previous_statuses[v["ID"]] = v.get("Statut", "")

    stop_event = threading.Event()

    def listener():
        nonlocal previous_statuses
        while not stop_event.is_set():
            try:
                time.sleep(5)
                current = db_service.get_data("atelier")
                if not current:
                    continue
                for k, v in current.items():
                    if not v:
                        continue
                    device_id = v.get("ID", "")
                    if not device_id:
                        continue
                    new_status = v.get("Statut", "")
                    old = previous_statuses.get(device_id, "")
                    if new_status and new_status != old:
                        previous_statuses[device_id] = new_status
                        print(f"🔔 تغيير الحالة: {device_id} -> {new_status}")
                        phone = v.get("Telephone", "")
                        if phone:
                            ref_cl = db_service.get_reference("clients")
                            if ref_cl:
                                data_cl = ref_cl.get() or {}
                                for ck, cv in data_cl.items():
                                    if cv and PhoneUtils.compare(cv.get("Telephone", ""), phone):
                                        tg_id = cv.get("Telegram_ID", cv.get("telegram_id", ""))
                                        if tg_id:
                                            _send_status_notification(bot, tg_id, v, new_status)
                                        break
            except Exception as e:
                print(f"❌ Listener error: {e}")
                time.sleep(10)

    threading.Thread(target=listener, daemon=True).start()
    print("🤖 بوت InfoDoc مع المستمع يعمل...")

    # حلقة polling مع إعادة محاولة 409
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            if "409" in str(e) or "Conflict" in str(e):
                print("⚠️ تعارض 409 - سيتم إعادة المحاولة بعد 30 ثانية...")
                time.sleep(30)
                try:
                    requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true", timeout=5)
                except:
                    pass
            else:
                print(f"Polling error: {e}")
                time.sleep(5)

    stop_event.set()

# ===== دالة بدء البوت الآمنة =====
def start_telegram_bot():
    """تشغيل البوت مرة واحدة فقط مع قفل ملف"""
    if not _acquire_lock():
        print("ℹ️ بوت Telegram يعمل بالفعل (قفل موجود).")
        return
    threading.Thread(target=_bot_main, daemon=True, name="InfoDocBot").start()
    print("✅ Bot thread started.")
