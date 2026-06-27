# app.py
"""بوابة العملاء - InfoDoc (النسخة المحسّنة)"""

import streamlit as st
import sys, os, pytz, json, requests, time, random
from datetime import datetime
import qrcode
from io import BytesIO
import base64
from PIL import Image  # لضغط الصور

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import APP_CONFIG
from static.styles import get_main_css
from services.firebase_service import get_firebase_service
from services.phone_utils import PhoneUtils
from services.telegram_bot import start_telegram_bot, notify_customer_status_change

st.set_page_config(page_title="InfoDoc - Portail Client", page_icon="🛠️", layout="wide", initial_sidebar_state="collapsed")

# ===== ضغط الصورة تلقائياً عند التحميل (مرة واحدة) =====
def compress_background():
    bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "background.jpg")
    if os.path.exists(bg_path):
        size = os.path.getsize(bg_path)
        # إذا كان حجمها أكبر من 500 كيلوبايت، نضغطها
        if size > 500 * 1024:
            try:
                img = Image.open(bg_path)
                img = img.convert("RGB")
                # تغيير الحجم لـ 1920 عرض مع الحفاظ على النسبة
                if img.width > 1920:
                    ratio = 1920 / img.width
                    new_size = (1920, int(img.height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                # حفظ بجودة 75%
                img.save(bg_path, format="JPEG", quality=75, optimize=True)
                print("✅ تم ضغط background.jpg تلقائياً")
            except Exception as e:
                print(f"⚠️ فشل ضغط الصورة: {e}")

compress_background()

# ===== إعدادات الأدمن =====
ADMIN_ID = st.secrets.get("MY_ADMIN_ID", "")
BOT_USERNAME = st.secrets.get("BOT_USERNAME", "Portail_Clients_bot")

def bot_link(start_param: str = "") -> str:
    base = f"https://t.me/{BOT_USERNAME}"
    return f"{base}?start={start_param}" if start_param else base

def notify_admin(text):
    if ADMIN_ID:
        try:
            token = st.secrets.get("TELEGRAM_TOKEN", "")
            if token:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": ADMIN_ID, "text": text},
                    timeout=5,
                )
        except Exception:
            pass

def init_session():
    defaults = {
        "page": "accueil", "user_phone": "", "user_name": "", "logged_in": False,
        "pending_phone": "", "pending_name": "", "login_otp": "", "login_otp_sent": False,
        "editing_req_id": "",
        "terms_accepted": False,
        "show_terms": False,
        "reg_name": "",
        "reg_phone": "",
        "visitor_counted": False,  # ✅ جديد: لمنع تكرار عداد الزوار
        "data_loaded": False,      # ✅ جديد: لمنع تكرار جلب البيانات الثقيلة
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def get_db(): return get_firebase_service()

def generate_qr(data: str):
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()

def send_otp_to_client(telegram_id, otp):
    try:
        token = st.secrets.get("TELEGRAM_TOKEN", "")
        if token and telegram_id:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": telegram_id, "text": f"🔐 *رمز التحقق:* `{otp}`\n\n🛠️ InfoDoc", "parse_mode": "Markdown"},
                timeout=5
            )
            return True
    except: pass
    return False

# ================================================================
# 🔥 دوال التخزين المؤقت (Caching) - حل البطء رقم 1
# ================================================================
@st.cache_data(ttl=600)  # 10 دقائق
def get_cached_shop_settings():
    db = get_db()
    return db.get_data("shop_settings") or {}

@st.cache_data(ttl=600)
def get_cached_annonces():
    db = get_db()
    return db.get_data("annonces") or {}

@st.cache_data(ttl=600)
def get_cached_offres():
    db = get_db()
    return db.get_data("offres") or {}

@st.cache_data(ttl=300)
def get_cached_atelier_devices(phone: str):
    """جلب أجهزة الورشة الخاصة بعميل معين مع تخزين مؤقت"""
    db = get_db()
    return db.get_user_devices(phone)

@st.cache_data(ttl=300)
def get_cached_client_demandes(phone: str):
    db = get_db()
    return db.get_client_demandes(phone)

def clear_cache():
    """مسح الكاش عند تسجيل الخروج أو تغيير كبير"""
    get_cached_shop_settings.clear()
    get_cached_annonces.clear()
    get_cached_offres.clear()
    get_cached_atelier_devices.clear()
    get_cached_client_demandes.clear()

# ================================================================
# دوال مساعدة (غير متغيرة)
# ================================================================
def get_warranty_stats(date_sortie_str):
    if not date_sortie_str or str(date_sortie_str).strip() in ["", "---", "None", "nan"]:
        return None
    date_formats = ["%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]
    tz = pytz.timezone(APP_CONFIG["TIMEZONE"])
    now = datetime.now(tz).replace(tzinfo=None)
    date_s = None
    for fmt in date_formats:
        try:
            date_s = datetime.strptime(str(date_sortie_str).strip(), fmt)
            break
        except ValueError: continue
    if date_s:
        diff_days = (now - date_s).days
        remaining_days = 30 - diff_days
        percent = max(0, min((remaining_days / 30) * 100, 100))
        return {"percent": int(percent), "is_expired": diff_days > 30, "days_left": remaining_days, "actual_date": date_s.strftime("%d/%m/%Y")}
    return None

def get_repair_progress(status):
    progress_map = {
        "En attente": (10, "#f59e0b", "⏳ في الانتظار"),
        "En Cours": (40, "#3b82f6", "🔧 قيد الفحص"),
        "Réparable": (65, "#10b981", "✅ قابل للإصلاح"),
        "Non Réparable": (80, "#ef4444", "❌ غير قابل للإصلاح"),
        "Prêt": (95, "#8b5cf6", "🎉 جاهز للتسليم"),
        "Livré & Payé": (100, "#6b7280", "📦 تم التسليم"),
        "Livré (Dette)": (100, "#f97316", "📦 تم التسليم بدين"),
        "Annulé": (100, "#6b7280", "🚫 ملغي"),
    }
    return progress_map.get(status, (0, "#94a3b8", status))

# ===== الصفحة الرئيسية (مع استخدام الكاش) =====
def render_accueil():
    db = get_db()
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ico.ico")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        logo_img = f'<img src="data:image/x-icon;base64,{logo_b64}" style="width:45px;height:45px;vertical-align:middle;">'
    else:
        logo_img = '<span style="font-size:2.5rem;">💻</span>'

    # ✅ استخدام البيانات المخزنة مؤقتاً
    shop_status = get_cached_shop_settings()
    is_open = shop_status.get("is_open", True)

    if is_open:
        status_badge = '<span style="background:#22c55e;color:white;padding:4px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;">🟢 مفتوح</span>'
    else:
        status_badge = '<span style="background:#ef4444;color:white;padding:4px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse 2s infinite;">🔴 مغلق</span>'

    # ✅ عداد الزوار (مرة واحدة لكل جلسة)
    if not st.session_state.get("visitor_counted"):
        db.increment_total_visitors()
        st.session_state["visitor_counted"] = True

    try:
        total_visits = db.get_data("stats/total_visitors") or 0
    except:
        total_visits = 0

    st.markdown(f"""
    <style>@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.5}}}}</style>
    <div style="background:rgba(30,58,138,0.55);backdrop-filter:blur(15px);-webkit-backdrop-filter:blur(15px);border:1px solid rgba(255,255,255,0.2);border-radius:20px;padding:20px 15px;margin-bottom:20px;color:white;">
        <div style="display:flex;align-items:center;justify-content:center;gap:15px;flex-wrap:wrap;margin-bottom:12px;">
            {logo_img}
            <div style="text-align:center;">
                <h1 style="margin:0;font-size:2rem;font-weight:900;color:white;">InfoDoc</h1>
                <p style="margin:2px 0 0 0;font-size:0.9rem;opacity:0.9;color:white;"> عيادة الإعلام الآلي - بيع، صيانة محترفة وخدمات</p>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">{status_badge}</div>
        </div>
        <div style="display:flex;justify-content:center;gap:30px;flex-wrap:wrap;font-size:0.9rem;opacity:0.85;">
            <span>📱 0798 66 19 00</span>
            <span>📍 الشلف - حي بن سونة بجانب المسبح</span>
            <span>🕐 8:00 - 17:00 (السبت - الخميس)</span>
            <span>👥 {total_visits} :زوار المنصة</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["🏠 الرئيسية", "🛠️ خدماتنا"])
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔑 دخول إلى حسابي", use_container_width=True, type="primary"): st.session_state["page"] = "login"; st.rerun()
        with c2:
            if st.button("✨ إنشاء حساب جديد", use_container_width=True): st.session_state["page"] = "register"; st.rerun()
        st.markdown("---")

        # ✅ الإعلانات من الكاش
        annonces = get_cached_annonces()
        if annonces:
            ann_list = []
            for key, val in annonces.items():
                if val: val["_id"] = key; ann_list.append(val)
            ann_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            if ann_list:
                first = ann_list[0]
                bg = first.get('bg_color', '#fef3c7')
                text_c = first.get('text_color', '#1e293b')
                border = first.get('border_color', '#f59e0b')
                ann_texts = []
                for ann in ann_list[:5]:
                    ann_texts.append(f'📢 {ann.get("title", "")}: {ann.get("content", "")}')
                full_text = '   |   '.join(ann_texts)
                ann_js = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><style>body{{margin:0;padding:0;background:transparent;}}.marquee-container{{overflow:hidden;white-space:nowrap;background:{bg};border:2px solid {border};border-radius:10px;padding:10px 0;margin-bottom:15px;}}.marquee-content{{display:inline-block;white-space:nowrap;color:{text_c};font-weight:bold;font-size:1rem;position:relative;will-change:transform;}}.marquee-content span{{margin:0 60px;}}</style></head><body><div class="marquee-container"><div class="marquee-content" id="marquee"><span>{full_text}</span><span>{full_text}</span></div></div><script>(function(){{var marquee=document.getElementById("marquee");var container=marquee.parentElement;var speed=0.5;var pos=-marquee.offsetWidth/2;function step(){{pos+=speed;if(pos>=container.offsetWidth){{pos=-marquee.offsetWidth/2;}}marquee.style.transform="translateX("+pos+"px)";requestAnimationFrame(step);}}step();}})();</script></body></html>'
                st.components.v1.html(ann_js, height=70, scrolling=False)

        # ✅ العروض من الكاش
        offres = get_cached_offres()
        if offres:
            off_list = []
            for key, val in offres.items():
                if val: val["_id"] = key; off_list.append(val)
            off_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            if off_list:
                st.markdown(f"<h3 style='text-align:right; direction:rtl;'> 🎉 عـروض خاصـة</h3>", unsafe_allow_html=True)
                cols = st.columns(min(len(off_list), 4))
                for i, off in enumerate(off_list[:4]):
                    badge_color = off.get('badge_color', '#dc2626')
                    with cols[i]:
                        st.markdown(f"""<div style="background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.2);padding:18px;border-radius:15px;text-align:center;min-height:110px;animation:bounce-{i} 2s ease-in-out infinite;"><span style="background:{badge_color};color:white;padding:5px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse-badge 1.5s ease-in-out infinite;">{off.get('badge','🔥')}</span><h4 style="margin:10px 0 5px 0;font-size:0.95rem;color:#f1f5f9;">{off.get('title','')}</h4><p style="font-weight:bold;margin:0;font-size:0.9rem;color:#4ade80;">{off.get('price','')}</p></div><style>@keyframes bounce-{i}{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-8px)}}}}@keyframes pulse-badge{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.08)}}}}</style>""", unsafe_allow_html=True)
        else:
            # عرض افتراضي
            st.markdown(f"<h3 style='text-align:right; direction:rtl;'> 🎉 عـروض خاصـة</h3>", unsafe_allow_html=True)
            o1, o2 = st.columns(2)
            with o1: st.markdown("""<div style="background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.2);padding:18px;border-radius:15px;text-align:center;min-height:110px;animation:bounce-1 2s ease-in-out infinite;"><span style="background:#dc2626;color:white;padding:5px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse-badge 1.5s ease-in-out infinite;">🔥 عرض خاص</span><h4 style="margin:10px 0 5px 0;color:#f1f5f9;">خصم 20% على الصيانة</h4><p style="font-weight:bold;color:#4ade80;">2500 دج بدلاً من 3500 دج</p></div><style>@keyframes bounce-1{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}@keyframes pulse-badge{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}</style>""", unsafe_allow_html=True)
            with o2: st.markdown("""<div style="background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.2);padding:18px;border-radius:15px;text-align:center;min-height:110px;animation:bounce-2 2.5s ease-in-out infinite;"><span style="background:#2563eb;color:white;padding:5px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse-badge 1.5s ease-in-out infinite;">💎 عرض VIP</span><h4 style="margin:10px 0 5px 0;color:#f1f5f9;">فحص مجاني + تنظيف</h4><p style="font-weight:bold;color:#4ade80;">مع كل خدمة</p></div><style>@keyframes bounce-2{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}@keyframes pulse-badge{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}</style>""", unsafe_allow_html=True)

        # تابعنا
        st.markdown(f"<h3 style='text-align:right; direction:rtl;'> 🌐 تـابعنـا على</h3>", unsafe_allow_html=True)
        s1, s2, s3, s4 = st.columns(4)
        with s1: st.markdown("""<a href="https://facebook.com/InfoDoc" target="_blank" style="text-decoration:none;"><div style="background:#1877f2;color:white;padding:12px;border-radius:10px;text-align:center;"><span style="font-size:1.3rem;">📘</span><p style="margin:3px 0 0 0;font-weight:bold;">Facebook</p></div></a>""", unsafe_allow_html=True)
        with s2: st.markdown(f"""<a href="{bot_link()}" target="_blank" style="text-decoration:none;"><div style="background:#0088cc;color:white;padding:12px;border-radius:10px;text-align:center;"><span style="font-size:1.3rem;">✈️</span><p style="margin:3px 0 0 0;font-weight:bold;">Telegram</p></div></a>""", unsafe_allow_html=True)
        with s3: st.markdown("""<a href="https://maps.app.goo.gl/f28XHG59jX62TfTRA" target="_blank" style="text-decoration:none;"><div style="background:#34a853;color:white;padding:12px;border-radius:10px;text-align:center;"><span style="font-size:1.3rem;">📍</span><p style="margin:3px 0 0 0;font-weight:bold;">Google Maps</p></div></a>""", unsafe_allow_html=True)
        with s4: st.markdown("""<a href="https://tiktok.com/@InfoDoc" target="_blank" style="text-decoration:none;"><div style="background:#000;color:white;padding:12px;border-radius:10px;text-align:center;"><span style="font-size:1.3rem;">🎵</span><p style="margin:3px 0 0 0;font-weight:bold;">TikTok</p></div></a>""", unsafe_allow_html=True)

    with tab2:
        st.markdown("### 🛠️ جميع خدماتنا")
        sections = [
            ("🔧 خدمات التصليح والصيانة", [("🖥️","صيانة الحواسيب","تشخيص وإصلاح جميع أعطال الحواسيب"),("⚡","تحديث البيوس","فلاش وإصلاح مشاكل البيوس"),("🔩","البطاقات الأم","تصليح Motherboard"),("💾","استبدال القطع","شاشات، بطاريات، مراوح"),("🧹","تنظيف دوري","تنظيف عميق ومعجون حراري"),("🔐","فك كلمات المرور","إزالة كلمة مرور البيوس")]),
            ("🛒 بيع الحواسيب وعتاد الإعلام الآلي", [("💻","حواسيب محمولة","جديدة ومستعملة"),("🖥️","حواسيب مكتبية","تجميع حسب الطلب"),("🖨️","طابعات وملحقات","أحبار وقطع غيار"),("⌨️","أكسسوارات","لوحات مفاتيح، فئران"),("💿","أقراص وفلاشات","SSD، HDD"),("🔌","كوابل ومحولات","شواحن، توصيلات")]),
            ("💿 خدمات البرمجة والسوفتوير", [("💿","تنصيب الأنظمة","Windows، Linux"),("🛡️","الحماية","إزالة الفيروسات"),("💾","استرجاع البيانات","استعادة الملفات"),("📦","نسخ احتياطي","حفظ ونقل البيانات"),("🔧","حلول تقنية","شبكات، استشارات")]),
            ("🎮 خدمات ألعاب الفيديو", [("🎮","بيع الألعاب","جميع المنصات"),("🕹️","أكسسوارات Gaming","أذرعة، سماعات"),("🖥️","حواسيب Gaming","تجميع مخصص"),("🔧","صيانة الأجهزة","PS4، PS5، Xbox")]),
            ("📋 الخدمات المكتبية", [("📄","الطباعة والنسخ","مستندات، تصوير"),("📝","الخدمات الإدارية","سير ذاتية، ترجمة"),("📊","خدمات رقمية","PowerPoint، إدخال"),("📧","خدمات الإنترنت","Emails، تحميل")]),
        ]
        for section_title, services in sections:
            st.markdown(f"<h4 style='text-align:right; direction:rtl;'>{section_title}</h4>", unsafe_allow_html=True)
            cols = st.columns(3)
            for i, (icon, title, desc) in enumerate(services):
                with cols[i % 3]:
                    st.markdown(f"""<div style="background:rgba(255,255,255,0.08);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.12);padding:10px 8px;border-radius:10px;margin-bottom:6px;text-align:center;transition:transform 0.3s,background 0.3s;direction:rtl;" onmouseover="this.style.transform='translateY(-3px)';this.style.background='rgba(255,255,255,0.15)';" onmouseout="this.style.transform='translateY(0)';this.style.background='rgba(255,255,255,0.08)';"><span style="font-size:1.3rem;">{icon}</span><h6 style="color:#f1f5f9;margin:3px 0;font-size:0.8rem;font-weight:700;">{title}</h6><p style="color:#cbd5e1;font-size:0.7rem;margin:0;line-height:1.3;">{desc}</p></div>""", unsafe_allow_html=True)

# ================================================================
# دوال تسجيل الدخول والتسجيل (كما هي، لكن مع تعديلات بسيطة)
# ================================================================
def render_login():
    st.markdown("### 🔑 دخول إلى حسابك")
    if not st.session_state.get("login_otp_sent"):
        with st.form("login_form"):
            phone = st.text_input("📱 رقم الهاتف", placeholder="07XX XX XX XX")
            if st.form_submit_button("دخول", use_container_width=True, type="primary"):
                if not phone: st.error("❌ أدخل رقم الهاتف")
                else:
                    n = PhoneUtils.normalize(phone)
                    if len(n) < 10: st.error("❌ رقم غير صالح")
                    else:
                        db = get_db()
                        client = db.get_client_by_phone(n)
                        if client:
                            tg_id = client.get("Telegram_ID", client.get("telegram_id", ""))
                            if tg_id and tg_id not in ["", "nan", "None"]:
                                otp = str(random.randint(1000, 9999))
                                db.update_data(f"clients/{client['_id']}", {"otp": otp})
                                send_otp_to_client(tg_id, otp)
                                st.session_state["user_phone"] = n
                                st.session_state["login_otp"] = otp
                                st.session_state["login_otp_sent"] = True
                                st.toast("✅ تم إرسال رمز التحقق", icon="✈️")
                                st.rerun()
                            else:
                                st.warning(f"⚠️ حسابك غير مربوط بـ Telegram. افتح @{BOT_USERNAME} وارسل /start لربطه.")
                        else:
                            st.error("❌ لا يوجد حساب. أنشئ حساباً جديداً.")
        if st.button("⬅️ العودة", key="back_login1", use_container_width=True):
            st.session_state["page"] = "accueil"; st.rerun()
    else:
        st.toast("📱 تم إرسال رمز إلى Telegram", icon="✈️")
        with st.form("login_otp_form"):
            otp_input = st.text_input("🔐 رمز التحقق (4 أرقام)", max_chars=4, placeholder="XXXX", key="login_otp_inp")
            c1, c2 = st.columns(2)
            with c1:
                confirm = st.form_submit_button("✅ تأكيد", use_container_width=True)
            with c2:
                resend = st.form_submit_button("🔄 إعادة", use_container_width=True)
            if confirm:
                db = get_db()
                client = db.get_client_by_phone(st.session_state["user_phone"])
                stored_otp = str(client.get("otp", "")) if client else ""
                entered_otp = str(otp_input).strip()
                if entered_otp and (entered_otp == stored_otp or entered_otp == st.session_state.get("login_otp")):
                    st.session_state["user_name"] = client.get("Client", client.get("name", ""))
                    st.session_state["logged_in"] = True
                    st.session_state["page"] = "dashboard"
                    st.session_state["login_otp"] = ""
                    st.session_state["login_otp_sent"] = False
                    if client:
                        db.update_data(f"clients/{client['_id']}", {"otp": ""})
                    notify_admin(f"🔑 دخول عميل\n👤 {st.session_state['user_name']}\n📱 {st.session_state['user_phone']}")
                    clear_cache()  # مسح الكاش عند الدخول لجلب بيانات حديثة
                    st.rerun()
                else:
                    st.error("❌ رمز غير صحيح")
            if resend:
                db = get_db()
                client = db.get_client_by_phone(st.session_state["user_phone"])
                if client:
                    tg_id = client.get("Telegram_ID", client.get("telegram_id", ""))
                    if tg_id and tg_id not in ["", "nan", "None"]:
                        new_otp = str(random.randint(1000, 9999))
                        db.update_data(f"clients/{client['_id']}", {"otp": new_otp})
                        send_otp_to_client(tg_id, new_otp)
                        st.session_state["login_otp"] = new_otp
                        st.toast("✅ تم إرسال رمز جديد", icon="📩")
                        st.rerun()
        col_cancel, col_back = st.columns(2)
        with col_cancel:
            if st.button("❌ إلغاء", key="cancel_login", use_container_width=True):
                st.session_state["login_otp_sent"] = False; st.session_state["user_phone"] = ""; st.rerun()
        with col_back:
            if st.button("⬅️ العودة", key="back_login2", use_container_width=True):
                st.session_state["page"] = "accueil"; st.rerun()

# ===== التسجيل =====
@st.dialog("⚠️ شروط التسجيل")
def terms_dialog():
    st.markdown("""
        <div style="background: #ffffff; padding: 20px; border-radius: 12px; direction: rtl; text-align: right;">
            <h4>📋 شروط التسجيل والخدمة</h4>
            <ol style="line-height: 2; font-size: 0.95rem;">
                <li><strong>تكاليف الفحص :</strong> إن كان الجهاز قابل للإصلاح ولكن العميل يرفض، فهو ملزم بدفع مبلغ <strong style="color: #dc2626;">1000 دج</strong> كرسوم الفحص .</li>
                <li><strong>أسعار العمل على البطاقة الأم:</strong> تبدأ تكاليفها من <strong style="color: #dc2626;">3000 دج</strong> و تزداد حسب نوع العطل.</li>
                <li><strong>أعمال البرمجة والبيوس:</strong> خدمات فلاش البيوس وفك التشفير  تبدأ من <strong style="color: #dc2626;">2000 دج</strong>.</li>
                <li><strong>الموافقة التلقائية:</strong> للتكاليف التي  تكون قيمتها <strong style="color: #dc2626;">4000 دج</strong>، نقوم بالإصلاح مباشرة دون الرجوع للعميل توفيرًا للوقت.</li>
                <li><strong>الضمان:</strong> نقدم ضمانًا لمدة <strong style="color: #16a34a;">30 يومًا</strong> على العيب الذي تم إصلاحه فقط، ولا يشمل أي عطل يظهر لاحقا.</li>
                <li><strong>الصبر :</strong> التشخيص الدقيق يستغرق وقتًا كافيًا، لذلك نرجو التحلي بالصبر وتجنب الإكثار من الإتصال من أجل الإستفسار عن تقدم الصيانة فهذه المنصة وضعت من أجل خدمتكم في هذا الشأن, .</li>
                <li><strong>الخصوصية:</strong> جميع بياناتك محمية بالكامل وتستخدم فقط لأغراض التواصل والخدمة.</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)

    accept = st.checkbox("✅ أوافق على جميع الشروط والأحكام", key="terms_checkbox")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ موافق", use_container_width=True, type="primary"):
            if accept:
                st.session_state.terms_accepted = True
                st.session_state.show_terms = False
                name = st.session_state.get("reg_name")
                phone = st.session_state.get("reg_phone")
                if name and phone:
                    db = get_db()
                    existing_client = db.get_client_by_phone(phone)
                    atelier_devices = db.get_user_devices(phone)
                    if existing_client and (existing_client.get("Telegram_ID") or existing_client.get("telegram_id")):
                        st.warning("⚠️ هذا الرقم مسجل بالفعل ومربوط. يمكنك الدخول مباشرة.")
                    elif existing_client or atelier_devices:
                        st.info("ℹ️ الرقم موجود لكنه غير مربوط. امسح الكود للربط.")
                        st.session_state["pending_phone"] = phone
                        st.session_state["pending_name"] = name
                    else:
                        st.session_state["pending_phone"] = phone
                        st.session_state["pending_name"] = name
                st.rerun()
            else:
                st.error("يجب الموافقة على الشروط")
    with col2:
        if st.button("❌ إلغاء", use_container_width=True):
            st.session_state.show_terms = False
            st.rerun()

def render_register():
    st.markdown(f"<h3 style='text-align:right; direction:rtl;'> ✨ إنشاء حساب جديد</h3>", unsafe_allow_html=True)
    st.markdown("""<div style="background:#fef3c7;border:1px solid #f59e0b;padding:15px;border-radius:10px;margin-bottom:20px;text-align:right;"><strong style="color:#92400e;">⚠️ شروط:</strong><ul style="color:#92400e;font-size:.9rem;"><li>يجب أن يكون لديك Telegram</li><li>سيتم إرسال كود تأكيد</li></ul></div>""", unsafe_allow_html=True)

    if st.session_state.get("show_terms"):
        terms_dialog()
        return

    if st.session_state.get("pending_phone"):
        n = st.session_state["pending_phone"]; name = st.session_state.get("pending_name", "")
        link = bot_link(n); qr = generate_qr(link)
        st.toast(f"✅ رقم الهاتف: {n}", icon="📱")
        st.markdown("### 📱 الخطوة 1: اربط Telegram")
        c1, c2 = st.columns([1, 2])
        with c1: st.image(qr, width=150)
        with c2: st.markdown(f"""<div style="text-align:right;padding-top:20px;"><p>1️⃣ افتح بوت @{BOT_USERNAME}</p><p>2️⃣ اضغط <strong>/start</strong></p><p>3️⃣ ستصلك رسالة برمز OTP</p><p>4️⃣ ارجع هنا وأدخل الرمز</p><a href="{link}" target="_blank" style="display:inline-block;background:#0088cc;color:white;padding:12px 30px;border-radius:10px;text-decoration:none;font-weight:bold;margin-top:15px;">📱 فتح Telegram</a></div>""", unsafe_allow_html=True)
        st.markdown("---"); st.markdown("### 🔐 الخطوة 2: أدخل رمز التأكيد")
        with st.form("otp_reg_form"):
            otp_input = st.text_input("رمز OTP (4 أرقام)", max_chars=4, placeholder="XXXX", key="otp_reg_inp")
            ca, cb = st.columns(2)
            with ca:
                confirm_reg = st.form_submit_button("✅ تأكيد التسجيل", use_container_width=True)
            with cb:
                resend_reg = st.form_submit_button("🔄 إعادة إرسال", use_container_width=True)
            if confirm_reg:
                if not otp_input or len(otp_input) != 4: st.error("❌ أدخل الرمز")
                else:
                    db = get_db(); client = db.get_client_by_phone(n)
                    if client and client.get("otp") == otp_input:
                        db.update_data(f"clients/{client['_id']}", {"Client": name, "verified": True, "otp": ""})
                        st.toast("✅ تم التسجيل بنجاح!", icon="🎉")
                        st.session_state.update({"user_phone": n, "user_name": name, "logged_in": True, "page": "dashboard", "pending_phone": "", "pending_name": ""})
                        st.balloons()
                        notify_admin(f"🆕 تسجيل جديد\n👤 {name}\n📱 {n}")
                        clear_cache()
                        time.sleep(1); st.rerun()
                    else: st.error("❌ رمز غير صحيح أو لم يتم الربط بعد")
            if resend_reg:
                db = get_db(); client = db.get_client_by_phone(n)
                if client:
                    tg_id = client.get("Telegram_ID", client.get("telegram_id", ""))
                    if tg_id and tg_id not in ["", "nan", "None"]:
                        new_otp = str(random.randint(1000, 9999))
                        db.update_data(f"clients/{client['_id']}", {"otp": new_otp})
                        send_otp_to_client(tg_id, new_otp)
                        st.toast("✅ تم إرسال رمز جديد", icon="📩")
                        st.rerun()
                    else: st.error("❌ لم يتم ربط Telegram بعد")
                else: st.error("❌ لم يتم العثور على حساب. تأكد من فتح البوت أولاً.")
        col_cancel, col_back = st.columns(2)
        with col_cancel:
            if st.button("❌ إلغاء", key="cancel_reg", use_container_width=True):
                st.session_state["pending_phone"] = ""; st.session_state["pending_name"] = ""; st.session_state["page"] = "accueil"; st.rerun()
        with col_back:
            if st.button("⬅️ العودة", key="back_reg", use_container_width=True):
                st.session_state["page"] = "accueil"; st.rerun()
    else:
        st.markdown("""
        <style>
        div[data-testid="stForm"] label {
            direction: rtl !important;
            text-align: right !important;
            display: block !important;
            width: 100% !important;
        }
        </style>
        """, unsafe_allow_html=True)
        with st.form("reg"):
            name = st.text_input("👤 الاســم "); phone = st.text_input("📱 الهـاتـف ")
            if st.form_submit_button("📱 متـابـعة", use_container_width=True, type="primary"):
                if not name or not phone: st.error("❌ امـلأ الحقـول")
                else:
                    n = PhoneUtils.normalize(phone)
                    if len(n) < 10: st.error("❌ رقـم غيـر صـالح")
                    else:
                        if not st.session_state.get("terms_accepted"):
                            st.session_state["show_terms"] = True
                            st.session_state["reg_name"] = name
                            st.session_state["reg_phone"] = n
                            st.rerun()
                        else:
                            db = get_db()
                            existing_client = db.get_client_by_phone(n)
                            atelier_devices = db.get_user_devices(n)
                            if existing_client and (existing_client.get("Telegram_ID") or existing_client.get("telegram_id")):
                                st.warning("⚠️ هذا الرقم مسجل بالفعل ومربوط. يمكنك الدخول مباشرة من صفحة الدخول.")
                            elif existing_client or atelier_devices:
                                st.info("ℹ️ الرقم موجود لكنه غير مربوط. امسح الكود للربط.")
                                st.session_state["pending_phone"] = n; st.session_state["pending_name"] = name; st.rerun()
                            else:
                                st.session_state["pending_phone"] = n; st.session_state["pending_name"] = name; st.rerun()
        if st.button("⬅️ العودة", key="back_reg2", use_container_width=True):
            st.session_state["page"] = "accueil"; st.rerun()

# ================================================================
# ✅ لوحة التحكم (المصححة بالكامل وإزالة الأخطاء)
# ================================================================
def render_dashboard():
    phone = st.session_state.get("user_phone", "")
    name = st.session_state.get("user_name", "")
    
    col_title, col_logout = st.columns([4, 1])
    with col_title:
        st.markdown(f"<h3 style='text-align:right; direction:rtl;'>👋 مرحباً {name}</h3>", unsafe_allow_html=True)
    with col_logout:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 خروج", use_container_width=True, type="secondary"):
            notify_admin(f"🚪 خروج عميل\n👤 {name}\n📱 {phone}")
            for k in ["user_phone","user_name","logged_in","login_otp","login_otp_sent"]:
                st.session_state[k] = "" if k != "logged_in" else False
            st.session_state["page"] = "accueil"
            clear_cache()
            st.rerun()
    
    db = get_db()
    client = db.get_client_by_phone(phone)
    telegram_id = client.get("Telegram_ID", client.get("telegram_id", "")) if client else ""
    
    # ✅ استخدام الكاش لجلب البيانات
    atelier_devices = get_cached_atelier_devices(phone)
    my_demandes = get_cached_client_demandes(phone)
    
    # فصل الأجهزة
    active_workshop = []
    historique_workshop = []
    for d in atelier_devices:
        if d.get("Statut") in ["Livré & Payé", "Livré (Dette)"]:
            w = get_warranty_stats(d.get("Date_Sortie", ""))
            if w and w.get("is_expired"):
                historique_workshop.append(d)
                continue
        active_workshop.append(d)
    
    pending_demandes = [d for d in my_demandes if d.get("status") == "en_attente"]
    confirmed_demandes = [d for d in my_demandes if d.get("status") == "confirme"]
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔧 ورشة نشطة", len(active_workshop))
    c2.metric("📦 أرشيف", len(historique_workshop))
    c3.metric("⏳ طلبات معلقة", len(pending_demandes))
    c4.metric("✅ طلبات مؤكدة", len(confirmed_demandes))
    
    if telegram_id:
        st.success("✅ Telegram مربوط - ستتلقى إشعارات")
    else:
        st.warning("⚠️ Telegram غير مربوط")
    
    st.markdown("---")
    tab1, tab2, tab3, tab4 = st.tabs(["💻 أجهزة الورشة", "📝 طلباتي", "📜 أرشيف الورشة", "➕ طلب جديد"])
    
    with tab1:
        if not active_workshop:
            st.info("لا توجد أجهزة نشطة في الورشة.")
        else:
            for dev in active_workshop:
                dev_id = dev.get("ID", "0000")
                brand = dev.get("Marque", "")
                model = dev.get("Appareil", "جهاز غير معروف")
                status = dev.get("Statut", "En attente")
                panne = dev.get("Panne", "غير محدد")
                prix = dev.get("Prix", "0")
                doc_id = dev.get("_id", "")
                decision = dev.get("Decision")

                status_colors = {"prêt": "#2ecc71", "en cours": "#f1c40f", "en attente": "#e67e22", "annulé": "#e74c3c"}
                col_status = status_colors.get(status.lower().strip(), "#3498db")

                progress_html = ""
                status_lower = status.lower().strip()
                if status_lower in ["livré & payé", "livré (dette)"]:
                    w_stats = get_warranty_stats(dev.get("Date_Sortie", ""))
                    if w_stats and not w_stats["is_expired"]:
                        progress_html = f'<div style="color:#2ecc71;font-weight:bold;">🟢 الضمان ساري: {w_stats["days_left"]} يوم</div>'
                else:
                    repair_steps = {
                        "en attente": (10, "#e67e22", "⏳ في الانتظار"),
                        "en cours": (40, "#f1c40f", "🔧 قيد الفحص"),
                        "réparable": (66, "#3498db", "✅ قابل للإصلاح"),
                        "non réparable": (80, "#e74c3c", "❌ غير قابل للإصلاح"),
                        "prêt": (100, "#2ecc71", "🎉 جاهز للتسليم"),
                        "annulé": (66, "#e74c3c", "❌ ملغي"),
                    }
                    if status_lower in repair_steps:
                        pct, color, label = repair_steps[status_lower]
                        progress_html = f'''<div style="color:{color};font-weight:bold;">{label}</div>
                        <div style="background:rgba(255,255,255,0.1);height:6px;border-radius:3px;margin:5px 0;">
                            <div style="background:{color};width:{pct}%;height:100%;border-radius:3px;"></div>
                        </div>'''

                card_html = f"""
                <div style="background:rgba(255,255,255,0.06);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:15px;margin-bottom:12px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div><strong style="color:#f1f5f9;">💻 {brand} - {model}</strong><br><span style="color:#94a3b8;">🎫 {dev_id}</span></div>
                        <span style="background:{col_status}20;color:{col_status};padding:5px 12px;border-radius:15px;font-weight:bold;">{status}</span>
                    </div>
                    <div style="margin-top:10px; color:#cbd5e1;">📌 {panne}</div>
                    <div style="color:#4ade80;font-weight:bold;">💰 {prix} دج</div>
                    {progress_html}
                """
                st.markdown(card_html, unsafe_allow_html=True)

                if status_lower == "réparable" and decision is None:
                    col1, col2 = st.columns(2, gap="small")
                    with col1:
                        if st.button("✅ قبول التصليح", key=f"accept_{doc_id}"):
                            db.update_data(f"atelier/{doc_id}", {"Decision": "accept"})
                            notify_admin(f"🔧 العميل {name} وافق على تصليح {model} (تذكرة #{dev_id})")
                            clear_cache()  # تحديث الكاش بعد التغيير
                            st.rerun()
                    with col2:
                        if st.button("❌ رفض التصليح", key=f"reject_{doc_id}"):
                            db.update_data(f"atelier/{doc_id}", {"Decision": "reject", "Statut": "Annulé", "Prix": 1000})
                            notify_admin(f"🔴 العميل {name} رفض تصليح {model} (تذكرة #{dev_id}) – يجب دفع 1000 دج")
                            clear_cache()
                            st.rerun()

                if decision == "accept":
                    st.success("✅ تم قبول التصليح – سيتم متابعة الجهاز")
                elif decision == "reject":
                    st.error("❌ تم رفض التصليح – عليك دفع 1000 دج تكاليف الفحص والوقت")

                st.markdown("</div>", unsafe_allow_html=True)
    
    with tab2:
        if not my_demandes:
            st.info("لا توجد طلبات صيانة حالياً.")
        else:
            for req in my_demandes:
                req_id = req.get("_id", "")
                dev_id = req.get("ticket_id", req_id[:8])
                brand = req.get("brand", "")
                model = req.get("model", "")
                fault = req.get("fault", "")
                status = req.get("status", "en_attente")
                created = req.get("created_at", "")
                
                if status == "en_attente":
                    status_text = "⏳ لم يدفع بعد"
                    status_color = "#f59e0b"
                    can_modify = True
                elif status == "confirme":
                    status_text = "✅ مؤكد"
                    status_color = "#10b981"
                    can_modify = False
                else:
                    status_text = status
                    status_color = "#94a3b8"
                    can_modify = False
                
                st.markdown(f"""
                <div style="background:rgba(255,255,255,0.06);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:15px;margin-bottom:12px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div><strong style="color:#f1f5f9;">💻 {brand} - {model}</strong><br><span style="color:#94a3b8;">🎫 {dev_id}</span></div>
                        <span style="background:{status_color}20;color:{status_color};padding:5px 12px;border-radius:15px;font-weight:bold;">{status_text}</span>
                    </div>
                    <div style="margin-top:10px; color:#cbd5e1;">📌 {fault}</div>
                    <div style="color:#94a3b8;font-size:0.8rem;">📅 {created}</div>
                """, unsafe_allow_html=True)
                
                if can_modify:
                    if st.session_state.get("editing_req_id") == req_id:
                        with st.form(f"edit_req_{req_id}"):
                            e_brand = st.text_input("العلامة", value=brand, key=f"eb_{req_id}")
                            e_model = st.text_input("الموديل", value=model, key=f"em_{req_id}")
                            e_fault = st.text_area("المشكلة", value=fault, height=80, key=f"ef_{req_id}")
                            c_save, c_cancel = st.columns(2)
                            with c_save:
                                save_edit = st.form_submit_button("💾 حفظ وإرسال", use_container_width=True)
                            with c_cancel:
                                cancel_edit = st.form_submit_button("❌ إلغاء", use_container_width=True)
                            if save_edit:
                                if not all([e_brand, e_model, e_fault]):
                                    st.error("❌ املأ الحقول")
                                else:
                                    db.update_data(f"demandes/{req_id}", {
                                        "brand": e_brand,
                                        "model": e_model,
                                        "fault": e_fault,
                                        "updated_at": datetime.now(pytz.timezone(APP_CONFIG["TIMEZONE"])).strftime("%Y-%m-%d %H:%M"),
                                    })
                                    st.session_state["editing_req_id"] = ""
                                    notify_admin(f"✏️ تعديل طلب صيانة\n👤 {name}\n📱 {phone}\n💻 {e_brand} {e_model}\n📌 {e_fault}")
                                    st.toast("✅ تم تحديث الطلب وإرساله!", icon="✏️")
                                    clear_cache()
                                    time.sleep(1)
                                    st.rerun()
                            if cancel_edit:
                                st.session_state["editing_req_id"] = ""
                                st.rerun()
                    else:
                        col_edit, col_delete = st.columns(2)
                        with col_edit:
                            if st.button("✏️ تعديل", key=f"edit_{req_id}"):
                                st.session_state["editing_req_id"] = req_id
                                st.rerun()
                        with col_delete:
                            if st.button("🗑️ إلغاء", key=f"cancel_{req_id}"):
                                db.delete_data(f"demandes/{req_id}")
                                notify_admin(f"🗑️ إلغاء طلب\n👤 {name}\n📱 {phone}\n💻 {brand} {model}")
                                st.toast("تم إلغاء الطلب", icon="🗑️")
                                clear_cache()
                                time.sleep(1)
                                st.rerun()
    
    with tab3:
        if not historique_workshop:
            st.info("لا توجد أجهزة في الأرشيف.")
        else:
            for dev in historique_workshop:
                dev_id = dev.get("ID", "---")
                brand = dev.get("Marque", "")
                model = dev.get("Appareil", "")
                fault = dev.get("Panne", "")
                prix_val = dev.get("Prix", 0)
                try:
                    prix_fmt = f"{int(float(str(prix_val).replace(',', '').replace(' ', ''))):,}"
                except (ValueError, TypeError):
                    prix_fmt = str(prix_val)
                date_sortie = dev.get("Date_Sortie", "")
                w_stats = get_warranty_stats(date_sortie)
                days_text = abs(w_stats['days_left']) if w_stats else '?'
                st.markdown(f"""<div style="background:#fff;border:1px solid #e5e7eb;border-right:4px solid #6b7280;padding:15px;border-radius:8px;margin-bottom:10px;opacity:0.8;"><div style="display:flex;justify-content:space-between;"><strong style="color:#6b7280;">💻 {brand} - {model}</strong><span style="color:#6b7280;font-weight:bold;">📦 أرشيف</span></div><p style="color:#64748b;margin:5px 0;">📌 {fault} | 🎫 #{dev_id}</p><p style="color:#94a3b8;font-size:0.8rem;">💰 {prix_fmt} دج | 📅 سلم: {date_sortie} | انتهى الضمان منذ {days_text} يوم</p></div>""", unsafe_allow_html=True)
    
    with tab4:
        st.markdown("### ➕ طلب صيانة جديد")
        with st.form("new_req"):
            brand = st.text_input("العلامة *")
            model = st.text_input("الموديل *")
            dtype = st.selectbox("النوع", APP_CONFIG["SUPPORTED_DEVICE_TYPES"])
            fault = st.text_area("المشكلة *", height=80)
            if st.form_submit_button("📤 إرسال", use_container_width=True, type="primary"):
                if not all([brand, model, fault]): st.error("❌ املأ الحقول")
                else:
                    db.save_demande({
                        "phone": phone,
                        "client_name": name,
                        "telegram_id": telegram_id,
                        "brand": brand,
                        "model": model,
                        "device_type": dtype,
                        "fault": fault,
                        "status": "en_attente",
                        "created_at": datetime.now(pytz.timezone(APP_CONFIG["TIMEZONE"])).strftime("%Y-%m-%d %H:%M")
                    })
                    st.toast("✅ تم إرسال الطلب! الحالة: لم يدفع بعد", icon="📥")
                    st.balloons()
                    notify_admin(f"📥 طلب صيانة جديد\n👤 {name}\n📱 {phone}\n💻 {brand} {model}\n📌 {fault}")
                    clear_cache()
                    time.sleep(1); st.rerun()
    
    # ✅ زر العودة للرئيسية
    if st.button("⬅️ العودة للرئيسية"):
        st.session_state["page"] = "accueil"
        st.rerun()

# ================================================================
# تشغيل البوت (مرة واحدة)
# ================================================================
@st.cache_resource
def init_bot_and_listener():
    start_telegram_bot()
    return True

# ===== الرئيسي =====
def main():
    st.markdown(get_main_css(), unsafe_allow_html=True)
    init_session()
    
    # ❌ تم حذف st_autorefresh نهائياً - حل البطء الأساسي
    
    db = get_db()
    if db.is_connected:
        # ✅ زيادة العداد تتم مرة واحدة فقط بفضل المتغير visitor_counted (يتم داخل render_accueil)
        init_bot_and_listener()
    if not db.is_connected:
        st.error("❌ تعذر الاتصال"); st.stop()
    
    page = st.session_state.get("page", "accueil")
    pages = {
        "accueil": render_accueil,
        "login": render_login,
        "register": render_register,
        "dashboard": render_dashboard
    }
    pages.get(page, render_accueil)()

if __name__ == "__main__":
    main()
