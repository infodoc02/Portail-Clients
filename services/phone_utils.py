# services/phone_utils.py
"""
أدوات معالجة أرقام الهواتف الجزائرية
"""

import re
from typing import Tuple, Optional


class PhoneUtils:
    """فئة معالجة أرقام الهواتف"""
    
    @staticmethod
    def normalize(phone: str) -> str:
        """
        توحيد تنسيق رقم الهاتف
        - يزيل +213 ويستبدلها بـ 0
        - يزيل المسافات والنقاط
        """
        if not phone:
            return ""
        
        # إزالة كل شيء ما عدا الأرقام
        cleaned = re.sub(r"\D", "", str(phone))
        
        # تحويل الصيغ الدولية إلى محلية
        if cleaned.startswith("213"):
            cleaned = "0" + cleaned[3:]
        elif cleaned.startswith("00213"):
            cleaned = "0" + cleaned[5:]
        
        # إضافة 0 إذا كان 9 أرقام ويبدأ بأحد رموز الجزائر
        if len(cleaned) == 9 and cleaned[0] in "2345679":
            cleaned = "0" + cleaned
        
        return cleaned
    
    @staticmethod
    def validate(phone: str) -> Tuple[bool, str]:
        """التحقق من صحة الرقم"""
        if not phone:
            return False, "الرجاء إدخال رقم الهاتف"
        
        cleaned = re.sub(r"\D", "", str(phone))
        
        if len(cleaned) < 9:
            return False, "رقم الهاتف قصير جداً"
        
        if len(cleaned) > 13:
            return False, "رقم الهاتف طويل جداً"
        
        return True, "رقم هاتف صالح"
    
    @staticmethod
    def mask_phone(phone: str) -> str:
        """إخفاء جزء من الرقم للخصوصية (0XX****XX)"""
        normalized = PhoneUtils.normalize(phone)
        if len(normalized) >= 10:
            return f"{normalized[:3]}****{normalized[-2:]}"
        return "***"
    
    @staticmethod
    def compare(phone1: str, phone2: str) -> bool:
        """مقارنة رقمين (آخر 9 أرقام)"""
        n1 = PhoneUtils.normalize(phone1)[-9:]
        n2 = PhoneUtils.normalize(phone2)[-9:]
        return n1 == n2


# دوال مساعدة للاستخدام المباشر
def normalize_phone(phone: str) -> str:
    return PhoneUtils.normalize(phone)

def validate_phone(phone: str) -> Tuple[bool, str]:
    return PhoneUtils.validate(phone)