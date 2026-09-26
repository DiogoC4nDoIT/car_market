"""Global CSS for the Stand dashboard. Kept separate from app.py so the visual
theme can be reviewed/edited without wading through page logic.

Palette/type follow the "OTTO/Lynx" design tokens from the Aug 2026 redesign
mockup (SIXT's internal MUI-based design system) — primary orange #ff5000,
Roboto/Roboto Mono, 4px radii, light MUI greys. Defined as CSS custom
properties so every inline style string across dashboard/ references
var(--token) instead of hardcoded hex, matching how the source design system
itself is tokenized."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@100;300;400;500;700&family=Roboto+Mono:wght@400;500;700&display=swap');

:root {
  --primary-main:#ff5000; --primary-light:#ff6d29; --primary-dark:#d64400; --primary-tint:#ffe9e0;
  --primary-tint-alpha:rgba(255,80,0,.16);
  --secondary-main:#757575;
  --success-main:#76b94e; --success-light:#8dc56d; --success-dark:#63a040; --success-tint:#eef7e7;
  --error-main:#d32f2f;   --error-dark:#b52626;   --error-tint:#fbe9e9;
  --warning-main:#eca72c; --warning-light:#efb652; --warning-dark:#db9214;  --warning-tint:#fdf3e2;
  --info-main:#559ec8;   --info-light:#65a9d4;  --info-dark:#458ec0;
  --bg-default:#ebebf0; --bg-paper:#ffffff; --app-tab-bar:#212121; --app-tab-bar-contrast:#ffffff;
  --divider:rgba(0,0,0,.12);
  /* MUI's own "outlined" inputs/buttons never use a solid black border — resting state
     is text-primary at 23% opacity, darkening on hover, and the brand color on focus.
     A flat #000 border here is what made every select/number/text box look like a stray
     plain HTML form control instead of part of this theme. */
  --input-border:rgba(0,0,0,.23); --input-border-hover:rgba(0,0,0,.45);
  --text-primary:rgba(0,0,0,.87); --text-secondary:rgba(0,0,0,.60); --text-disabled:rgba(0,0,0,.38);
  --grey-100:#f5f5f5; --grey-200:#eeeeee; --grey-300:#e0e0e0;
  --radius:4px;
  --font-family:'Roboto',sans-serif;
  --font-family-monospace:'Roboto Mono',monospace;
}

.stApp { background:var(--bg-default); }
.stApp, .stApp p, .stApp span, .stApp div, .stApp label { font-family:var(--font-family); }
span[data-testid="stIconMaterial"] { font-family:'Material Symbols Rounded' !important; }
h1, h2, h3 { font-family:var(--font-family); font-weight:100; color:var(--text-primary); }
div[data-testid="stMetricValue"] { font-family:var(--font-family); font-weight:400; color:var(--text-primary); }
div[data-testid="stMetricLabel"] { font-family:var(--font-family-monospace); font-size:10px !important;
  letter-spacing:.5px; color:var(--text-secondary) !important; text-transform:uppercase; }
div[data-testid="stButton"] button {
  border-radius:var(--radius); border:1px solid var(--input-border); background:var(--bg-paper); color:var(--text-primary);
  font-family:var(--font-family); font-weight:500;
}
/* Icon + label buttons (Reset, Save search, …) sit in narrow flex columns whose
   width depends on viewport/sidebar state — without this they wrap mid-word
   ("Res et") the moment the column gets tight instead of just clipping cleanly. */
div[data-testid="stButton"] button p { white-space:nowrap; }
div[data-testid="stButton"] button:hover { background:var(--grey-100); border-color:var(--input-border-hover); color:var(--text-primary); }
div[data-testid="stLinkButton"] a {
  background:var(--primary-main) !important; color:#fff !important; border:none !important; font-weight:500 !important;
}

/* Filter controls (selects/number/text inputs/checkbox/sliders): give them the
   same soft-outline + hover/focus treatment as everything else, instead of the
   flat black border + unstyled native browser look they had before — this is
   what made the "white" filter row read as odd/off-theme against the rest of
   the page. */
div[data-baseweb="select"] > div, div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
  background:var(--bg-paper) !important; border-color:var(--primary-main) !important;
}
div[data-testid="stSelectbox"]:hover div[data-baseweb="select"] > div,
div[data-testid="stSelectbox"]:focus-within div[data-baseweb="select"] > div { border-color:var(--primary-main) !important; }

/* Streamlit >=1.62 dropped the BaseWeb select for a react-aria ComboBox — the
   bordered box is now the input's parent div, unreachable by [data-baseweb]
   at all, which is why Brand/Model/Region silently lost their border while
   only the momentarily-focused control (default focus ring) looked outlined. */
div[data-testid="stSelectbox"] div:has(> input[role="combobox"]) {
  background:var(--bg-paper) !important; border-color:var(--primary-main) !important;
}
div[data-testid="stSelectbox"]:hover div:has(> input[role="combobox"]),
div[data-testid="stSelectbox"]:focus-within div:has(> input[role="combobox"]) { border-color:var(--primary-main) !important; }

div[data-testid="stNumberInput"] input, div[data-testid="stTextInput"] input {
  background:var(--bg-paper) !important; border-color:var(--primary-main) !important;
}
div[data-testid="stNumberInput"]:hover input, div[data-testid="stTextInput"]:hover input,
div[data-testid="stNumberInput"] input:focus, div[data-testid="stTextInput"] input:focus {
  border-color:var(--primary-main) !important; box-shadow:0 0 0 1px var(--primary-main);
}

div[data-testid="stCheckbox"] input[type="checkbox"] {
  accent-color:var(--primary-main); width:16px; height:16px; border-radius:3px; cursor:pointer;
}

div[data-testid="stSlider"] div[data-baseweb="slider"] > div > div { background:var(--grey-300); }
div[data-testid="stSlider"] div[role="slider"] { background-color:var(--primary-main) !important; border-color:var(--primary-main) !important; }
div[data-testid="stSlider"] div[data-testid="stThumbValue"] { color:var(--primary-dark); font-family:var(--font-family-monospace); }
div[data-testid="stSlider"] div[data-testid="stTickBar"] { color:var(--text-disabled); }

/* Sidebar nav: flat borderless rows (icon + label), not bordered buttons — matches
   the source design's menuItems (bg rgba(255,80,0,.16) + orange icon when active,
   transparent + grey icon otherwise), not Streamlit's default button chrome. */
section[data-testid="stSidebar"] { background:var(--bg-default); border-right:1px solid var(--divider); }
section[data-testid="stSidebar"] div[data-testid="stButton"] button {
  border:none; background:transparent; border-radius:var(--radius); min-height:44px;
  justify-content:flex-start; padding:0 12px; color:var(--text-primary); font-weight:400;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
  background:var(--grey-200); border:none; color:var(--text-primary);
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button span[data-testid="stIconMaterial"] {
  color:var(--secondary-main);
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button:disabled {
  background:var(--primary-tint-alpha); color:var(--text-primary); font-weight:500; opacity:1; cursor:default;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button:disabled span[data-testid="stIconMaterial"] {
  color:var(--primary-main);
}
.stand-mono { font-family:var(--font-family-monospace); }
.stand-row-title { font-family:var(--font-family); font-weight:500; font-size:15px; color:var(--text-primary); }
.stand-row-title a { color:inherit; text-decoration:none; }
.stand-row-title a:hover { color:var(--primary-main); text-decoration:underline; }
.stand-meta { font-size:12px; color:var(--text-secondary); margin-top:2px; }
.stand-label { font-family:var(--font-family-monospace); font-size:10px; color:var(--text-disabled); letter-spacing:.5px; text-transform:uppercase; }
.stand-badge { font:600 10px var(--font-family-monospace); padding:4px 8px; border-radius:var(--radius); letter-spacing:.4px; }
.stand-bar-bg { height:6px; border-radius:3px; background:var(--grey-200); overflow:hidden; margin-top:6px; }
.stand-bar-fill { height:100%; border-radius:3px; background:var(--text-secondary); }
.stand-photo-wrap { position:relative; }
.stand-photo-img { width:100%; aspect-ratio:4/3; border-radius:6px; object-fit:cover; display:block;
  box-shadow:0 1px 3px rgba(0,0,0,.15); transition:transform .15s ease, box-shadow .15s ease; }
.stand-photo-img:hover { transform:scale(1.04); box-shadow:0 4px 10px rgba(0,0,0,.25); }
.stand-photo { width:100%; aspect-ratio:4/3; border-radius:6px;
  background:repeating-linear-gradient(135deg,var(--grey-100) 0 7px,var(--grey-200) 7px 14px);
  display:flex; align-items:center; justify-content:center;
  font:400 9px var(--font-family-monospace); color:var(--text-disabled); }
.stand-photo a { display:flex; width:100%; height:100%; align-items:center; justify-content:center; }
.stand-photo-badge { position:absolute; top:6px; left:6px; z-index:2; }
.stand-card {
  background:var(--bg-paper); border:1px solid var(--divider); border-radius:var(--radius); padding:16px 18px;
  box-shadow:0 1px 2px rgba(0,0,0,.06), 0 1px 4px rgba(0,0,0,.06);
}
.stand-card-row { display:flex; justify-content:space-between; font-size:13px; color:var(--text-secondary); padding:4px 0; }

/* st.container(border=True) (the filter panels, save-search box, KPI row) has no
   elevation at all by default — just a near-invisible border, same white as the
   inputs inside it, on a barely-darker grey page. Real MUI "paper" cards always
   carry a soft shadow; without it these read as a flat, undifferentiated white
   smear rather than an intentional card. Matching .stand-card's radius/border too
   so hand-built and native cards look like one consistent system.
   Streamlit has changed the DOM for border=True containers across versions —
   `stVerticalBlockBorderWrapper` (confirmed still current as of early 2025) vs.
   `stLayoutWrapper` > `stVerticalBlock` in newer releases — and requirements.txt
   only pins a floor (streamlit>=1.36), so both selectors are covered here since
   which one applies depends on the exact version actually installed. */
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stVerticalBlockBorderWrapper"] > div,
div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stVerticalBlock"]) {
  background:var(--bg-paper) !important; border:1px solid var(--divider) !important;
  border-radius:var(--radius) !important;
}
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stVerticalBlock"]) {
  box-shadow:0 1px 2px rgba(0,0,0,.06), 0 1px 4px rgba(0,0,0,.06);
}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)
