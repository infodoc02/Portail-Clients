# services/firebase_service.py
"""
خدمة Firebase - نفس قاعدة بيانات التطبيق الرئيسي
جداول جديدة: clients, demandes
"""

import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from typing import Optional, Dict, List
from datetime import datetime
import pytz
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import APP_CONFIG, FIREBASE_PATHS
from services.phone_utils import PhoneUtils


class FirebaseService:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self.db_url = None
        self._connect()
        self._initialized = True
    
    def _connect(self) -> bool:
        try:
            if not firebase_admin._apps:
                # ✅ طريقة مضمونة 100% لقراءة المفتاح
                private_key = st.secrets["firebase"]["private_key"]
                
                # إصلاح المفتاح إذا كان فيه \\n
                if "\\n" in private_key:
                    private_key = private_key.replace("\\n", "\n")
                
                cred_dict = {
                    "type": st.secrets["firebase"]["type"],
                    "project_id": st.secrets["firebase"]["project_id"],
                    "private_key_id": st.secrets["firebase"]["private_key_id"],
                    "private_key": private_key,
                    "client_email": st.secrets["firebase"]["client_email"],
                    "client_id": st.secrets["firebase"]["client_id"],
                    "auth_uri": st.secrets["firebase"]["auth_uri"],
                    "token_uri": st.secrets["firebase"]["token_uri"],
                    "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
                    "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"]
                }
                
                cred = credentials.Certificate(cred_dict)
                self.db_url = st.secrets["DB_URL"]
                firebase_admin.initialize_app(cred, {'databaseURL': self.db_url})
            
            return True
            
        except KeyError as e:
            st.error(f"❌ مفتاح ناقص في secrets.toml: {e}")
            st.write("المفاتيح المتوفرة:", list(st.secrets.keys()))
            if "firebase" in st.secrets:
                st.write("مفاتيح firebase:", list(st.secrets["firebase"].keys()))
            return False
        except Exception as e:
            st.error(f"❌ Erreur connexion Firebase: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return False
    
    @property
    def is_connected(self) -> bool:
        return self.db_url is not None and bool(firebase_admin._apps)
    
    def get_reference(self, path: str):
        if not self.is_connected:
            return None
        return db.reference(path, url=self.db_url)
    
    def get_data(self, path: str) -> Optional[Dict]:
        if not self.is_connected:
            return None
        try:
            ref = self.get_reference(path)
            return ref.get() if ref else None
        except Exception as e:
            st.error(f"❌ Erreur lecture {path}: {e}")
            return None
    
    def push_data(self, path: str, data: Dict) -> Optional[str]:
        if not self.is_connected:
            return None
        try:
            ref = self.get_reference(path)
            if ref:
                new_ref = ref.push(data)
                return new_ref.key
            return None
        except Exception as e:
            st.error(f"❌ Erreur ajout {path}: {e}")
            return None
    
    def update_data(self, path: str, data: Dict) -> bool:
        if not self.is_connected:
            return False
        try:
            ref = self.get_reference(path)
            if ref:
                ref.update(data)
                return True
            return False
        except Exception as e:
            st.error(f"❌ Erreur mise à jour {path}: {e}")
            return False
    
    def delete_data(self, path: str) -> bool:
        if not self.is_connected:
            return False
        try:
            ref = self.get_reference(path)
            if ref:
                ref.delete()
                return True
            return False
        except Exception as e:
            st.error(f"❌ Erreur suppression {path}: {e}")
            return False
    
    # ===== دوال خاصة بالبوابة =====

    @staticmethod
    def _extract_phone(record: Dict) -> str:
        for key in ("Telephone", "telephone", "phone", "Phone"):
            val = record.get(key)
            if val not in (None, "", "nan", "None"):
                return str(val)
        return ""

    def get_client_by_phone(self, phone: str) -> Optional[Dict]:
        """البحث عن عميل في جدول clients - تطابق تام أو آخر 9 أرقام"""
        clients = self.get_data(FIREBASE_PATHS["CLIENTS"]) or {}
        for key, val in clients.items():
            if not val:
                continue
            db_phone = self._extract_phone(val)
            if db_phone and PhoneUtils.compare(db_phone, phone):
                val["_id"] = key
                return val
        return None
    
    def save_client(self, phone: str, name: str, telegram_id: str = "") -> str:
        """حفظ أو تحديث عميل في جدول clients"""
        existing = self.get_client_by_phone(phone)
        if existing and existing.get("_id"):
            self.update_data(f"{FIREBASE_PATHS['CLIENTS']}/{existing['_id']}", {
                "Client": name,
                "Telegram_ID": telegram_id or existing.get("telegram_id", ""),
                "updated_at": datetime.now(pytz.timezone(APP_CONFIG["TIMEZONE"])).strftime("%Y-%m-%d %H:%M")
            })
            return existing["_id"]
        else:
            return self.push_data(FIREBASE_PATHS["CLIENTS"], {
                "Telephone": phone,
                "Client": name,
                "Telegram_ID": telegram_id,
                "created_at": datetime.now(pytz.timezone(APP_CONFIG["TIMEZONE"])).strftime("%Y-%m-%d %H:%M")
            })
    
    def get_client_demandes(self, phone: str) -> List[Dict]:
        """جلب طلبات عميل من جدول demandes"""
        demandes = self.get_data(FIREBASE_PATHS["DEMANDES"]) or {}
        result = []
        for key, val in demandes.items():
            if not val:
                continue
            db_phone = self._extract_phone(val)
            if db_phone and PhoneUtils.compare(db_phone, phone):
                val["_id"] = key
                result.append(val)
        result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return result
    
    def save_demande(self, data: Dict) -> Optional[str]:
        """حفظ طلب صيانة جديد"""
        payload = dict(data)
        if "Role" not in payload:
            payload["Role"] = "admin"
        if payload.get("phone") and not payload.get("Telephone"):
            payload["Telephone"] = payload["phone"]
        return self.push_data(FIREBASE_PATHS["DEMANDES"], payload)
    
    def get_user_devices(self, phone: str) -> List[Dict]:
        """جلب أجهزة الورشة الخاصة بعميل"""
        all_data = self.get_data(FIREBASE_PATHS["ATELIER"])
        devices = []
        if all_data:
            search = str(phone).replace(" ", "").strip()[-9:]
            for key, value in all_data.items():
                if not value:
                    continue
                db_phone = str(value.get("Telephone", "")).replace(" ", "").strip()
                if db_phone[-9:] == search:
                    device = dict(value)
                    device["_id"] = key
                    device["Decision"] = value.get("Decision")
                    devices.append(device)
        return devices
    
    def increment_total_visitors(self):
        """زيادة عداد الزوار الإجمالي (يُستدعى مع كل تحميل للصفحة)"""
        if not self.is_connected:
            return
        try:
            ref = self.get_reference("stats/total_visitors")
            ref.transaction(lambda current: (current or 0) + 1)
        except Exception:
            pass

# ============================================================
# ✅ الدالة المطلوبة لاستيرادها من app.py (مع التخزين المؤقت)
# ============================================================
@st.cache_resource
def get_firebase_service() -> FirebaseService:
    """إرجاع كائن الخدمة مع التخزين المؤقت (يتم إنشاؤه مرة واحدة فقط)"""
    return FirebaseService()
