# app.py
"""بوابة العملاء - InfoDoc"""

import streamlit as st
import sys, os, pytz, json, requests, time, random
from datetime import datetime
import qrcode
from io import BytesIO
import base64  # أضفه مع الاستيرادات الأخرى

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import APP_CONFIG
from static.styles import get_main_css
from services.firebase_service import get_firebase_service
from services.phone_utils import PhoneUtils

st.set_page_config(page_title="InfoDoc - Portail Client", page_icon="🛠️", layout="wide", initial_sidebar_state="collapsed")

# ===== تهيئة =====
def init_session():
    defaults = {
        "page": "accueil", "user_phone": "", "user_name": "", "logged_in": False,
        "pending_phone": "", "pending_name": "", "login_otp": "", "login_otp_sent": False
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def get_db(): return get_firebase_service()

def main():
    st.markdown(get_main_css(), unsafe_allow_html=True)
    init_session()
    
    # ✅ تتبع الزائر
    try:
        from services.visitor_tracker import init_visitor_tracking, get_visitor_stats
        init_visitor_tracking()
        
        # 🎉 نافذة ترحيبية (تظهر مرة واحدة فقط)
        if not st.session_state.get("welcome_shown"):
            stats = get_visitor_stats()
            total_visits = stats["total_visits"] if stats else 0
            
            st.markdown(f"""
            <style>
                .welcome-overlay {{
                    position: fixed;
                    top: 0; left: 0;
                    width: 100%; height: 100%;
                    background: rgba(0, 0, 0, 0.7);
                    z-index: 9999;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    animation: fadeOut 4s forwards;
                }}
                @keyframes fadeOut {{
                    0% {{ opacity: 1; }}
                    80% {{ opacity: 1; }}
                    100% {{ opacity: 0; visibility: hidden; }}
                }}
                .welcome-card {{
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    text-align: center;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
                    animation: scaleIn 0.5s ease;
                }}
                @keyframes scaleIn {{
                    0% {{ transform: scale(0.5); opacity: 0; }}
                    100% {{ transform: scale(1); opacity: 1; }}
                }}
            </style>
            <div class="welcome-overlay" onclick="this.style.display='none'">
                <div class="welcome-card">
                    <h2 style="font-family: 'Cairo', sans-serif; color: #1e293b;">👋 مرحباً بك في InfoDoc</h2>
                    <p style="font-size: 1.5rem; color: #334155;">
                        📊 إجمالي زوار المنصة: <strong style="color: #2563eb;">{total_visits}</strong>
                    </p>
                    <p style="color: #94a3b8; font-size: 0.9rem;">(اضغط للمتابعة أو ستغلق تلقائياً)</p>
                </div>
            </div>
            <script>
                setTimeout(function(){{
                    var overlay = document.querySelector('.welcome-overlay');
                    if(overlay) overlay.style.display = 'none';
                }}, 4000);
            </script>
            """, unsafe_allow_html=True)
            
            st.session_state.welcome_shown = True
    except ImportError:
        st.warning("⚠️ نظام تتبع الزوار غير متاح حالياً.")
    
    if not get_db().is_connected:
        st.error("❌ تعذر الاتصال"); st.stop()
    
    page = st.session_state.get("page", "accueil")
    pages = {"accueil":render_accueil,"login":render_login,"register":render_register,"dashboard":render_dashboard}
    pages.get(page, render_accueil)()
    
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

# ===== تسجيل الدخول =====
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
                            tg_id = client.get("telegram_id", "")
                            if not tg_id or tg_id in ["", "nan", "None"]:
                                st.warning("⚠️ حسابك غير مربوط بـ Telegram.")
                            else:
                                otp = str(random.randint(1000, 9999))
                                db.update_data(f"clients/{client['_id']}", {"otp": otp})
                                send_otp_to_client(tg_id, otp)
                                st.session_state["user_phone"] = n
                                st.session_state["login_otp"] = otp
                                st.session_state["login_otp_sent"] = True
                                st.success("✅ تم إرسال رمز التحقق"); st.rerun()
                        else: st.error("❌ لا يوجد حساب.")
        
        if st.button("⬅️ العودة", key="back_login1", use_container_width=True):
            st.session_state["page"] = "accueil"; st.rerun()
    
    else:
        st.success("📱 تم إرسال رمز إلى Telegram")
        with st.form("login_otp_form"):
            otp_input = st.text_input("🔐 رمز التحقق (4 أرقام)", max_chars=4, placeholder="XXXX", key="login_otp_inp")
            
            c1, c2 = st.columns(2)
            with c1:
                confirm = st.form_submit_button("✅ تأكيد", use_container_width=True)
            with c2:
                resend = st.form_submit_button("🔄 إعادة", use_container_width=True)
            
            if confirm:
                if otp_input == st.session_state.get("login_otp"):
                    db = get_db()
                    client = db.get_client_by_phone(st.session_state["user_phone"])
                    st.session_state["user_name"] = client.get("name", "") if client else ""
                    st.session_state["logged_in"] = True
                    st.session_state["page"] = "dashboard"
                    st.session_state["login_otp"] = ""; st.session_state["login_otp_sent"] = False
                    st.rerun()
                else: st.error("❌ رمز غير صحيح")
            
            if resend:
                db = get_db()
                client = db.get_client_by_phone(st.session_state["user_phone"])
                if client and client.get("telegram_id"):
                    new_otp = str(random.randint(1000, 9999))
                    db.update_data(f"clients/{client['_id']}", {"otp": new_otp})
                    send_otp_to_client(client["telegram_id"], new_otp)
                    st.session_state["login_otp"] = new_otp
                    st.success("✅ تم إرسال رمز جديد"); st.rerun()
        
        col_cancel, col_back = st.columns(2)
        with col_cancel:
            if st.button("❌ إلغاء", key="cancel_login", use_container_width=True):
                st.session_state["login_otp_sent"] = False
                st.session_state["user_phone"] = ""
                st.rerun()
        with col_back:
            if st.button("⬅️ العودة", key="back_login2", use_container_width=True):
                st.session_state["page"] = "accueil"
                st.rerun()
# ===== الصفحة الرئيسية (نسخة كاملة ومحدثة) =====
def render_accueil():
    db = get_db()

    # ===== تحضير الأيقونة =====
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ico.ico")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        logo_img = f'<img src="data:image/x-icon;base64,{logo_b64}" style="width:45px;height:45px;vertical-align:middle;">'
    else:
        logo_img = '<span style="font-size:2.5rem;">💻</span>'

    # حالة المحل
    try:
        shop_status = db.get_data("shop_settings") or {}
        is_open = shop_status.get("is_open", True)
    except:
        is_open = True

    if is_open:
        status_badge = '<span style="background:#22c55e;color:white;padding:4px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;">🟢 مفتوح</span>'
    else:
        status_badge = '<span style="background:#ef4444;color:white;padding:4px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse 2s infinite;">🔴 مغلق</span>'

    # ===== الشريط العلوي المحسّن (الأيقونة والاسم في الوسط) =====
    st.markdown(f"""
    <style>
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.5}} }}
    </style>
    <div style="background:rgba(30,58,138,0.55);backdrop-filter:blur(15px);
                -webkit-backdrop-filter:blur(15px);
                border:1px solid rgba(255,255,255,0.2);
                border-radius:20px;padding:20px 15px;margin-bottom:20px;color:white;">
        <!-- الصف الأول: الأيقونة + الاسم + حالة المحل -->
        <div style="display:flex;align-items:center;justify-content:center;gap:15px;flex-wrap:wrap;margin-bottom:12px;">
            {logo_img}
            <div style="text-align:center;">
                <h1 style="margin:0;font-size:2rem;font-weight:900;color:white;">InfoDoc</h1>
                <p style="margin:2px 0 0 0;font-size:0.9rem;opacity:0.9;color:white;">ورشة صيانة الحواسيب المحترفة</p>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
                {status_badge}
            </div>
        </div>
        <!-- الصف الثاني: معلومات التواصل -->
        <div style="display:flex;justify-content:center;gap:30px;flex-wrap:wrap;font-size:0.9rem;opacity:0.85;">
            <span>📱 0798 66 19 00</span>
            <span>📍 الشلف - تنس</span>
            <span>🕐 8:00 - 17:00 (السبت - الخميس)</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ===== التبويبات =====
    tab1, tab2 = st.tabs(["🏠 الرئيسية", "🛠️ خدماتنا"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔑 دخول إلى حسابي", use_container_width=True, type="primary"):
                st.session_state["page"] = "login"; st.rerun()
        with c2:
            if st.button("✨ إنشاء حساب جديد", use_container_width=True):
                st.session_state["page"] = "register"; st.rerun()

        st.markdown("---")

        # ===== إعلانات متحركة (حل جافاسكريبت مضمون) =====
        annonces = db.get_data("annonces") or {}
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
                
                # بناء النص
                ann_texts = []
                for ann in ann_list[:5]:
                    ann_texts.append(f'📢 {ann.get("title", "")}: {ann.get("content", "")}')
                full_text = '   |   '.join(ann_texts)
                
                # استخدام HTML + جافاسكريبت داخل components.html لضمان البدء الفوري
                ann_js = f'''
                <!DOCTYPE html>
                <html>
                <head>
                <meta charset="UTF-8">
                <style>
                    body {{
                        margin: 0;
                        padding: 0;
                        background: transparent;
                    }}
                    .marquee-container {{
                        overflow: hidden;
                        white-space: nowrap;
                        background: {bg};
                        border: 2px solid {border};
                        border-radius: 10px;
                        padding: 10px 0;
                        margin-bottom: 15px;
                    }}
                    .marquee-content {{
                        display: inline-block;
                        white-space: nowrap;
                        color: {text_c};
                        font-weight: bold;
                        font-size: 1rem;
                        position: relative;
                        will-change: transform;
                    }}
                    .marquee-content span {{
                        margin: 0 60px;
                    }}
                </style>
                </head>
                <body>
                <div class="marquee-container">
                    <div class="marquee-content" id="marquee">
                        <span>{full_text}</span>
                        <span>{full_text}</span>
                    </div>
                </div>
                <script>
                    (function() {{
                        var marquee = document.getElementById('marquee');
                        var container = marquee.parentElement;
                        var speed = 0.5; // بكسل لكل إطار (كلما قل كان أبطأ)
                        var pos = -marquee.offsetWidth / 2; // ابدأ من منتصف النص لليسار
                        
                        function step() {{
                            pos += speed;
                            if (pos >= container.offsetWidth) {{
                                pos = -marquee.offsetWidth / 2;
                            }}
                            marquee.style.transform = 'translateX(' + pos + 'px)';
                            requestAnimationFrame(step);
                        }}
                        
                        // بدء فوري بعد تحميل الصفحة
                        step();
                    }})();
                </script>
                </body>
                </html>
                '''
                st.components.v1.html(ann_js, height=70, scrolling=False)
        # ===== عروض خاصة (من قاعدة البيانات) =====
        offres = db.get_data("offres") or {}
        if offres:
            off_list = []
            for key, val in offres.items():
                if val: val["_id"] = key; off_list.append(val)
            off_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            if off_list:
                st.markdown("### 🎉 عروض خاصة")
                cols = st.columns(min(len(off_list), 4))
                for i, off in enumerate(off_list[:4]):
                    badge_color = off.get('badge_color', '#dc2626')
                    with cols[i]:
                        st.markdown(f"""<div style="background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.2);padding:18px;border-radius:15px;text-align:center;min-height:110px;animation:bounce-{i} 2s ease-in-out infinite;">
                            <span style="background:{badge_color};color:white;padding:5px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse-badge 1.5s ease-in-out infinite;">{off.get('badge','🔥')}</span>
                            <h4 style="margin:10px 0 5px 0;font-size:0.95rem;color:#f1f5f9;">{off.get('title','')}</h4>
                            <p style="font-weight:bold;margin:0;font-size:0.9rem;color:#4ade80;">{off.get('price','')}</p>
                        </div>
                        <style>
                        @keyframes bounce-{i} {{ 0%,100%{{transform:translateY(0)}} 50%{{transform:translateY(-8px)}} }}
                        @keyframes pulse-badge {{ 0%,100%{{transform:scale(1)}} 50%{{transform:scale(1.08)}} }}
                        </style>""", unsafe_allow_html=True)
        else:
            # عروض افتراضية
            st.markdown("### 🎉 عروض خاصة")
            o1, o2 = st.columns(2)
            with o1:
                st.markdown("""<div style="background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.2);padding:18px;border-radius:15px;text-align:center;min-height:110px;animation:bounce-1 2s ease-in-out infinite;">
                    <span style="background:#dc2626;color:white;padding:5px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse-badge 1.5s ease-in-out infinite;">🔥 عرض خاص</span>
                    <h4 style="margin:10px 0 5px 0;color:#f1f5f9;">خصم 20% على الصيانة</h4>
                    <p style="font-weight:bold;color:#4ade80;">2500 دج بدلاً من 3500 دج</p>
                </div>
                <style>@keyframes bounce-1{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}@keyframes pulse-badge{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}</style>""", unsafe_allow_html=True)
            with o2:
                st.markdown("""<div style="background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.2);padding:18px;border-radius:15px;text-align:center;min-height:110px;animation:bounce-2 2.5s ease-in-out infinite;">
                    <span style="background:#2563eb;color:white;padding:5px 14px;border-radius:20px;font-size:0.8rem;font-weight:bold;animation:pulse-badge 1.5s ease-in-out infinite;">💎 عرض VIP</span>
                    <h4 style="margin:10px 0 5px 0;color:#f1f5f9;">فحص مجاني + تنظيف</h4>
                    <p style="font-weight:bold;color:#4ade80;">مع كل خدمة</p>
                </div>
                <style>@keyframes bounce-2{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}@keyframes pulse-badge{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}</style>""", unsafe_allow_html=True)

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
            st.markdown(f"#### {section_title}")
            cols = st.columns(3)
            for i, (icon, title, desc) in enumerate(services):
                with cols[i % 3]:
                    st.markdown(f"""<div style="background:rgba(255,255,255,0.08);backdrop-filter:blur(8px);
                        -webkit-backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.12);
                        padding:10px 8px;border-radius:10px;margin-bottom:6px;text-align:center;
                        transition:transform 0.3s,background 0.3s;"
                        onmouseover="this.style.transform='translateY(-3px)';this.style.background='rgba(255,255,255,0.15)';"
                        onmouseout="this.style.transform='translateY(0)';this.style.background='rgba(255,255,255,0.08)';">
                        <span style="font-size:1.3rem;">{icon}</span>
                        <h6 style="color:#f1f5f9;margin:3px 0;font-size:0.8rem;font-weight:700;">{title}</h6>
                        <p style="color:#cbd5e1;font-size:0.7rem;margin:0;line-height:1.3;">{desc}</p></div>""", unsafe_allow_html=True)
# ===== التسجيل =====
def render_register():
    st.markdown("### ✨ إنشاء حساب جديد")
    st.markdown("""<div style="background:#fef3c7;border:1px solid #f59e0b;padding:15px;border-radius:10px;margin-bottom:20px;text-align:right;">
        <strong style="color:#92400e;">⚠️ شروط:</strong><ul style="color:#92400e;font-size:.9rem;"><li>يجب أن يكون لديك Telegram</li><li>سيتم إرسال كود تأكيد</li></ul></div>""", unsafe_allow_html=True)
    
    if st.session_state.get("pending_phone"):
        n = st.session_state["pending_phone"]; name = st.session_state.get("pending_name", "")
        link = f"https://t.me/infodoc02_bot?start={n}"; qr = generate_qr(link)
        st.success(f"✅ رقم الهاتف: {n}")
        st.markdown("### 📱 الخطوة 1: اربط Telegram")
        c1, c2 = st.columns([1, 2])
        with c1: st.image(qr, width=150)
        with c2: st.markdown(f"""<div style="text-align:right;padding-top:20px;"><p>1️⃣ افتح بوت InfoDoc</p><p>2️⃣ اضغط <strong>/start</strong></p><p>3️⃣ ستصلك رسالة برمز OTP</p><p>4️⃣ ارجع هنا وأدخل الرمز</p><a href="{link}" target="_blank" style="display:inline-block;background:#0088cc;color:white;padding:12px 30px;border-radius:10px;text-decoration:none;font-weight:bold;margin-top:15px;">📱 فتح Telegram</a></div>""", unsafe_allow_html=True)
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
                        db.update_data(f"clients/{client['_id']}", {"name": name, "verified": True, "otp": ""})
                        st.success("✅ تم التسجيل!")
                        st.session_state.update({"user_phone": n, "user_name": name, "logged_in": True, "page": "dashboard", "pending_phone": "", "pending_name": ""})
                        st.balloons(); time.sleep(1); st.rerun()
                    else: st.error("❌ رمز غير صحيح")
            
            if resend_reg:
                db = get_db(); client = db.get_client_by_phone(n)
                if client and client.get("telegram_id"):
                    new_otp = str(random.randint(1000, 9999))
                    db.update_data(f"clients/{client['_id']}", {"otp": new_otp})
                    send_otp_to_client(client["telegram_id"], new_otp)
                    st.success("✅ تم إرسال رمز جديد"); st.rerun()
                else: st.error("❌ لم يتم ربط Telegram بعد")
        
        col_cancel, col_back = st.columns(2)
        with col_cancel:
            if st.button("❌ إلغاء", key="cancel_reg", use_container_width=True):
                st.session_state["pending_phone"] = ""; st.session_state["pending_name"] = ""; st.session_state["page"] = "accueil"; st.rerun()
        with col_back:
            if st.button("⬅️ العودة", key="back_reg", use_container_width=True):
                st.session_state["page"] = "accueil"; st.rerun()
    
    else:
        with st.form("reg"):
            name = st.text_input("👤 الاسم *"); phone = st.text_input("📱 الهاتف *")
            if st.form_submit_button("📱 متابعة", use_container_width=True, type="primary"):
                if not name or not phone: st.error("❌ املأ الحقول")
                else:
                    n = PhoneUtils.normalize(phone)
                    if len(n) < 10: st.error("❌ رقم غير صالح")
                    else: st.session_state["pending_phone"] = n; st.session_state["pending_name"] = name; st.rerun()
        if st.button("⬅️ العودة", key="back_reg2", use_container_width=True):
            st.session_state["page"] = "accueil"; st.rerun()

# ===== لوحة التحكم =====
def render_dashboard():
    phone = st.session_state.get("user_phone", "")
    name = st.session_state.get("user_name", "")
    
    col_title, col_logout = st.columns([4, 1])
    with col_title:
        st.markdown(f"### 👋 مرحباً {name}")
    with col_logout:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 خروج", use_container_width=True, type="secondary"):
            for k in ["user_phone","user_name","logged_in","login_otp","login_otp_sent"]:
                st.session_state[k] = "" if k != "logged_in" else False
            st.session_state["page"] = "accueil"
            st.rerun()
    
    db = get_db()
    client = db.get_client_by_phone(phone)
    telegram_id = client.get("telegram_id", "") if client else ""
    my_demandes = db.get_client_demandes(phone)
    my_atelier = db.get_user_devices(phone)
    
    # تجميع كل الأجهزة
    all_devices = []
    for d in my_demandes:
        d["source"] = "demande"
        if d.get("ticket_id"):
            for a in my_atelier:
                if str(a.get("ID")) == str(d.get("ticket_id")):
                    d["atelier_status"] = a.get("Statut", "")
                    d["atelier_prix"] = a.get("Prix", 0)
                    d["atelier_date_sortie"] = a.get("Date_Sortie", "")
                    d["atelier_diagnostic"] = a.get("Diagnostic", "")
                    d["atelier_marque"] = a.get("Appareil", "")
                    break
        all_devices.append(d)
    
    # فصل الأجهزة: نشطة / منتهية الضمان
    active_devices = []
    historique_devices = []
    
    for d in all_devices:
        at_status = d.get("atelier_status", "")
        if at_status in ["Livré & Payé", "Livré (Dette)"]:
            w_stats = get_warranty_stats(d.get("atelier_date_sortie", ""))
            if w_stats and w_stats.get("is_expired"):
                historique_devices.append(d)
                continue
        active_devices.append(d)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💻 نشطة", len(active_devices))
    c2.metric("⏳ لم يدفع", sum(1 for d in all_devices if d.get("status")=="en_attente"))
    c3.metric("📦 أرشيف", len(historique_devices))
    
    if telegram_id: st.success("✅ Telegram مربوط - ستتلقى إشعارات")
    else: st.warning("⚠️ Telegram غير مربوط")
    
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["💻 أجهزتي", "📜 الأرشيف", "➕ طلب جديد"])
    
    # ===== TAB 1: أجهزتي النشطة =====
    with tab1:
        if not active_devices:
            st.info("لا توجد أجهزة نشطة.")
        else:
            for dev in active_devices:
                s = dev.get("status", "en_attente")
                at_status = dev.get("atelier_status", "")
                raw_id = dev.get("ticket_id", dev.get("_id", "---"))
                dev_id = str(raw_id)[:8] if raw_id else "---"
                brand = dev.get("brand", dev.get("atelier_marque", ""))
                model = dev.get("model", "")
                fault = dev.get("fault", "")
                prix = int(dev.get("atelier_prix", 0) or 0)
                created = dev.get("created_at", "")

                if s == "confirme" and at_status:
                    progress, color, label = get_repair_progress(str(at_status))
                    status_text = label
                    status_color = color
                    is_livre = at_status in ["Livré & Payé", "Livré (Dette)"]
                    w_stats = get_warranty_stats(dev.get("atelier_date_sortie", "")) if is_livre else None
                elif s == "confirme":
                    status_text = "✅ مؤكد - قيد المعالجة"
                    status_color = "#10b981"
                    progress = 20
                    is_livre = False
                    w_stats = None
                else:
                    status_text = "⏳ لم يدفع بعد"
                    status_color = "#f59e0b"
                    progress = 5
                    is_livre = False
                    w_stats = None

                fault_short = str(fault)[:50] + ('...' if len(str(fault)) > 50 else '')

                # بناء HTML في متغير
                card_html = f'''<div style="background:rgba(255,255,255,0.06);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:15px;margin-bottom:12px;transition:transform 0.3s,box-shadow 0.3s;" onmouseover="this.style.transform='translateY(-3px)';this.style.boxShadow='0 8px 25px rgba(0,0,0,0.3)';" onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='none';">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
<div><strong style="color:#f1f5f9;font-size:1rem;">💻 {brand} - {model}</strong><span style="color:#94a3b8;font-size:0.75rem;display:block;">🎫 {dev_id}</span></div>
<span style="background:{status_color}25;color:{status_color};padding:5px 12px;border-radius:15px;font-weight:bold;font-size:0.8rem;">{status_text}</span></div>
<div style="margin-bottom:10px;"><div style="display:flex;justify-content:space-between;margin-bottom:3px;"><span style="color:#94a3b8;font-size:0.7rem;">تقدم الإصلاح</span><span style="color:{status_color};font-weight:bold;font-size:0.75rem;">{progress}%</span></div>
<div style="background:rgba(255,255,255,0.1);height:6px;border-radius:3px;overflow:hidden;"><div style="background:{status_color};width:{progress}%;height:100%;border-radius:3px;transition:width 0.5s;"></div></div></div>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="color:#cbd5e1;font-size:0.85rem;">📌 {fault_short}</span><span style="color:#4ade80;font-weight:bold;font-size:0.9rem;">💰 {prix:,} دج</span></div>
<span style="color:#64748b;font-size:0.7rem;">📅 {created}</span>'''

                # الضمان
                if is_livre and w_stats:
                    if w_stats["is_expired"]:
                        card_html += f'''<div style="margin-top:10px;padding:8px 12px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:8px;text-align:center;"><span style="color:#ef4444;font-weight:bold;font-size:0.8rem;">🔴 انتهى الضمان</span><span style="color:#94a3b8;font-size:0.7rem;display:block;">منذ {abs(w_stats['days_left'])} يوم</span></div>'''
                    else:
                        card_html += f'''<div style="margin-top:10px;padding:8px 12px;background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);border-radius:8px;text-align:center;"><span style="color:#22c55e;font-weight:bold;font-size:0.8rem;">🟢 الضمان ساري</span><span style="color:#94a3b8;font-size:0.7rem;display:block;">متبقي {w_stats['days_left']} يوم</span><div style="background:rgba(255,255,255,0.1);height:4px;border-radius:2px;overflow:hidden;margin-top:5px;"><div style="background:#22c55e;width:{w_stats['percent']}%;height:100%;border-radius:2px;"></div></div></div>'''

                card_html += '</div>'
                
                st.markdown(card_html, unsafe_allow_html=True)
    
    # ===== TAB 2: الأرشيف =====
    with tab2:
        if not historique_devices:
            st.info("📭 لا توجد أجهزة في الأرشيف. الأجهزة المنتهية ضمانها تظهر هنا.")
        else:
            for dev in historique_devices:
                dev_id = dev.get("ticket_id", "---")
                brand = dev.get("brand", dev.get("atelier_marque", ""))
                model = dev.get("model", "")
                fault = dev.get("fault", "")
                prix = dev.get("atelier_prix", 0)
                date_sortie = dev.get("atelier_date_sortie", "")
                w_stats = get_warranty_stats(date_sortie)
                
                st.markdown(f"""<div style="background:#fff;border:1px solid #e5e7eb;border-right:4px solid #6b7280;padding:15px;border-radius:8px;margin-bottom:10px;opacity:0.8;">
                    <div style="display:flex;justify-content:space-between;"><strong style="color:#6b7280;">💻 {brand} - {model}</strong><span style="color:#6b7280;font-weight:bold;">📦 أرشيف</span></div>
                    <p style="color:#64748b;margin:5px 0;">📌 {fault} | 🎫 #{dev_id}</p>
                    <p style="color:#94a3b8;font-size:0.8rem;">💰 {prix:,} دج | 📅 سلم: {date_sortie} | انتهى الضمان منذ {abs(w_stats['days_left']) if w_stats else '?'} يوم</p>
                </div>""", unsafe_allow_html=True)
    
    # ===== TAB 3: طلب جديد =====
    with tab3:
        st.markdown("### ➕ طلب صيانة جديد")
        with st.form("new_req"):
            brand = st.text_input("العلامة *"); model = st.text_input("الموديل *")
            dtype = st.selectbox("النوع", APP_CONFIG["SUPPORTED_DEVICE_TYPES"])
            fault = st.text_area("المشكلة *", height=80)
            if st.form_submit_button("📤 إرسال", use_container_width=True, type="primary"):
                if not all([brand, model, fault]): st.error("❌ املأ الحقول")
                else:
                    db.save_demande({"phone":phone,"client_name":name,"telegram_id":telegram_id,"brand":brand,"model":model,"device_type":dtype,"fault":fault,"status":"en_attente","created_at":datetime.now(pytz.timezone(APP_CONFIG["TIMEZONE"])).strftime("%Y-%m-%d %H:%M")})
                    st.success("✅ تم! الحالة: لم يدفع بعد"); st.balloons(); time.sleep(1); st.rerun()

# ===== رئيسي =====
def main():
    st.markdown(get_main_css(), unsafe_allow_html=True)
    init_session()
    if not get_db().is_connected: st.error("❌ تعذر الاتصال"); st.stop()
    page = st.session_state.get("page", "accueil")
    pages = {"accueil":render_accueil,"login":render_login,"register":render_register,"dashboard":render_dashboard}
    pages.get(page, render_accueil)()

if __name__ == "__main__":
    main()
