# static/styles.py
"""أنماط CSS لبوابة العملاء"""
import base64
import os

def get_main_css() -> str:
    bg_image_base64 = ""
    bg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "background.jpg")
    
    if os.path.exists(bg_path):
        with open(bg_path, "rb") as f:
            bg_image_base64 = base64.b64encode(f.read()).decode()
    
    if bg_image_base64:
        bg_css = f"""
        .stApp {{
            background-image: url('data:image/jpeg;base64,{bg_image_base64}');
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}
        """
    else:
        bg_css = """
        .stApp {
            background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #1e1b4b 100%);
            background-attachment: fixed;
        }
        """
    
    return f"""
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
    
    <style>
        {bg_css}
        
        .stApp::before {{
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(15, 23, 42, 0.75);
            z-index: 0;
        }}
        
        .stMain, [data-testid="stHeader"] {{ position: relative; z-index: 1; }}
        * {{ font-family: 'Cairo', sans-serif !important; }}
        
        h1, h2, h3, h4, h5, h6, p, span, label {{ color: #f1f5f9 !important; }}
        [data-testid="stMetricValue"] {{ color: #f1f5f9 !important; }}
        [data-testid="stMetricLabel"] {{ color: #94a3b8 !important; }}
        
        /* أزرار عامة */
        .stButton > button {{
            width: 100% !important; border-radius: 12px !important; height: 3em !important;
            background: linear-gradient(90deg, #3b82f6 0%, #2563eb 100%) !important;
            color: white !important; font-weight: 700 !important; border: none !important;
        }}
        
        /* أزرار الفورم - تأكيد (أخضر) */
        div[data-testid="stFormSubmitButton"]:first-of-type button {{
            background: linear-gradient(90deg, #16a34a, #22c55e) !important;
            color: white !important; font-weight: 700 !important; border: none !important;
            width: 100% !important; border-radius: 12px !important; height: 3em !important;
        }}
        
        /* أزرار الفورم - إعادة (برتقالي) */
        div[data-testid="stFormSubmitButton"]:nth-of-type(2) button {{
            background: linear-gradient(90deg, #d97706, #f59e0b) !important;
            color: white !important; font-weight: 700 !important; border: none !important;
            width: 100% !important; border-radius: 12px !important; height: 3em !important;
        }}
        
        /* تبويبات */
        div[data-testid="stTabs"] {{ direction: rtl !important; }}
        button[data-testid="stMarkdownContainer"] p {{
            font-size: 1.2rem !important; font-weight: 700 !important;
            color: #94a3b8 !important; transition: all 0.3s ease !important;
        }}
        button[aria-selected="true"] p {{
            color: #ffffff !important; font-size: 1.3rem !important;
            text-shadow: 0 0 10px rgba(96,165,250,0.5);
        }}
        div[data-testid="stTab"] {{
            padding: 12px 24px !important; background: rgba(255,255,255,0.03) !important;
            border-radius: 12px 12px 0 0 !important; margin: 0 4px !important;
            transition: all 0.3s ease !important; border: 1px solid transparent !important;
        }}
        div[data-testid="stTab"]:hover {{
            background: rgba(59,130,246,0.15) !important; border-color: rgba(59,130,246,0.3) !important;
            transform: translateY(-2px);
        }}
        div[data-testid="stTab"][aria-selected="true"] {{
            background: rgba(59,130,246,0.25) !important; border: 1px solid rgba(96,165,250,0.5) !important;
            border-bottom: 3px solid #60a5fa !important; box-shadow: 0 -4px 15px rgba(59,130,246,0.2);
        }}
        div[stTabs] {{ border-bottom: 2px solid rgba(255,255,255,0.1) !important; }}
        
        /* مدخلات */
        div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea {{
            direction: rtl !important; text-align: right !important;
            background: rgba(255,255,255,0.9) !important; color: #1e293b !important;
            border-radius: 10px !important;
        }}
        div[data-testid="stSelectbox"] > div {{
            background: rgba(255,255,255,0.9) !important; color: #1e293b !important;
            border-radius: 10px !important;
        }}
        .stAlert {{ background: rgba(30,41,59,0.8) !important; color: #f1f5f9 !important; }}
        .streamlit-expanderHeader {{ color: #f1f5f9 !important; }}
    </style>
    """