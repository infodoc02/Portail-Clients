# config.py
APP_CONFIG = {
    "NAME": "InfoDoc",
    "TIMEZONE": "Africa/Algiers",
    "SUPPORTED_DEVICE_TYPES": [
        "PC Portable", "PC Bureau", "Carte Mère", "Carte Graphique", "Écran", "Autre"
    ],
    "STATUS_TYPES": {
        "En attente": "في الانتظار",
        "En Cours": "قيد الإصلاح",
        "Réparable": "قابل للإصلاح",
        "Prêt": "جاهز",
        "Livré & Payé": "تم التسليم",
        "Annulé": "ملغي"
    },
    "STATUS_COLORS": {
        "En attente": "#f59e0b",
        "En Cours": "#3b82f6",
        "Réparable": "#10b981",
        "Prêt": "#8b5cf6",
        "Livré & Payé": "#6b7280",
        "Annulé": "#ef4444"
    },
    "STATUS_PRIORITY": {
        "Prêt": 1, "Réparable": 2, "En Cours": 3,
        "En attente": 4, "Livré & Payé": 5, "Annulé": 6
    }
}

# مسارات Firebase - نفس قاعدة البيانات، جداول مختلفة
FIREBASE_PATHS = {
    "ATELIER": "atelier",           # جدول الورشة (موجود)
    "CLIENTS": "clients",           # 🆕 جدول العملاء الجديد
    "DEMANDES": "demandes",         # 🆕 جدول طلبات الصيانة
    "STATS_VISITORS": "stats/daily_visitors"
}

THEME_COLORS = {
    "PRIMARY": "#2563eb",
    "SUCCESS": "#10b981",
    "WARNING": "#f59e0b",
    "DANGER": "#ef4444"
}
