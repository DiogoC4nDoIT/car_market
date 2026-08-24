"""Global CSS for the Stand dashboard. Kept separate from app.py so the visual
theme can be reviewed/edited without wading through page logic."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

.stApp { background:#efeadd; }
.stApp, .stApp p, .stApp span, .stApp div, .stApp label { font-family:'Instrument Sans',system-ui,sans-serif; }
span[data-testid="stIconMaterial"] { font-family:'Material Symbols Rounded' !important; }
h1, h2, h3 { font-family:'Newsreader',serif !important; color:#22201a; }
div[data-testid="stMetricValue"] { font-family:'Newsreader',serif; color:#22201a; }
div[data-testid="stMetricLabel"] { font-family:'JetBrains Mono',monospace; font-size:10px !important;
  letter-spacing:.5px; color:#8c856f !important; text-transform:uppercase; }
div[data-testid="stButton"] button {
  border-radius:9px; border:1px solid #ddd4bd; background:#faf7ef; color:#5b5647;
  font-family:'Instrument Sans',sans-serif; font-weight:500;
}
div[data-testid="stButton"] button:hover { background:#f1e9d8; border-color:#c9bf9f; color:#3a3626; }
div[data-testid="stLinkButton"] a {
  background:#e8c07a !important; color:#3a2f16 !important; border:none !important; font-weight:600 !important;
}
div[data-testid="stSlider"] div[role="slider"] { background-color:#1c3d2e !important; border-color:#1c3d2e !important; }
div[data-testid="stSlider"] div[data-baseweb="slider"] > div > div { background:#1c3d2e !important; }
div[data-testid="stSlider"] span { color:#c99a3f !important; }
div[data-baseweb="select"] > div, div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
  background:#fff !important; border-color:#d8cfb8 !important;
}
div[data-testid="stNumberInput"] input, div[data-testid="stTextInput"] input { background:#fff !important; border-color:#d8cfb8 !important; }
div[data-testid="stCheckbox"] input[type="checkbox"] { accent-color:#1c3d2e; }
.stand-mono { font-family:'JetBrains Mono',monospace; }
.stand-row-title { font-family:'Newsreader',serif; font-weight:500; font-size:15px; color:#22201a; }
.stand-meta { font-size:12px; color:#8c856f; margin-top:2px; }
.stand-label { font-family:'JetBrains Mono',monospace; font-size:10px; color:#a09a84; letter-spacing:.5px; }
.stand-badge { font:600 10px 'JetBrains Mono',monospace; padding:4px 8px; border-radius:6px; letter-spacing:.4px; }
.stand-bar-bg { height:6px; border-radius:3px; background:#e8dfca; overflow:hidden; margin-top:6px; }
.stand-bar-fill { height:100%; border-radius:3px; background:linear-gradient(90deg,#2f6b47,#3f8659); }
.stand-photo { width:100%; height:64px; border-radius:7px;
  background:repeating-linear-gradient(135deg,#eae2d0 0 7px,#e2d9c4 7px 14px);
  display:flex; align-items:center; justify-content:center;
  font:400 9px 'JetBrains Mono',monospace; color:#a89e83; }
.stand-card { background:#f2ecdc; border:1px solid #e7dfca; border-radius:11px; padding:16px 18px; }
.stand-card-row { display:flex; justify-content:space-between; font-size:13px; color:#5b5647; padding:4px 0; }
.st-key-save_search_card > div { background:#f2ecdc; border-color:#e7dfca; }
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)
