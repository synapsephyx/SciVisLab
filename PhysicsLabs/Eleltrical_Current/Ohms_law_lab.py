"""
Ohm's Law lab — interactive simulation with analog gauges (ไม่ใช้ matplotlib)
รันด้วยคำสั่ง:  streamlit run ohms_law_lab_no_matplotlib.py

ต้องติดตั้ง:  pip install streamlit numpy pandas
(Altair มากับ Streamlit อยู่แล้ว ไม่ต้องติดตั้งเพิ่ม)

สิ่งที่เปลี่ยนจากเวอร์ชัน matplotlib:
  - วงจร + หน้าปัด analog วาดเป็น SVG แล้วแสดงด้วย components.html
    เข็มเคลื่อนด้วย JavaScript (ease-out) ในเบราว์เซอร์ ไม่ต้องวาดทีละเฟรมจาก Python
  - กราฟ scatter + เส้น fit ใช้ Altair
  - ฟอนต์ไทยแสดงด้วยเบราว์เซอร์ ไม่ต้องตั้งค่า THAI_FONT อีกต่อไป
"""

import json
import random

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

WIRE_COLOR = "#5F5E5A"
NEEDLE_COLOR = "#C0392B"
FACE_COLOR = "#F7F8FC"

COL_V = "V (โวลต์)"
COL_I = "I (mA)"

# แถบที่ 4 (tolerance) สุ่มได้ 3 แบบ: ทอง ±5%, เงิน ±10%, ไม่มีสี ±20%
TOLERANCE_OPTIONS = [
    ("ทอง", "#C9A227", 0.05),
    ("เงิน", "#B0B0B0", 0.10),
    ("ไม่มีสี", "#D9D5C9", 0.20),
]

BATTERY_OPTIONS = [1.5, 3.0, 4.5, 6.0, 9.0, 12.0]  # โวลต์ (จำลองการสลับก้อนแบต)

# ----------------------------------------------------------------------
# ตารางสีแถบตัวต้านทานมาตรฐาน (สี, hex) ตามรหัสเลข 0-9 และตัวคูณ 10^0..10^3
# ----------------------------------------------------------------------
BAND_COLOR_TABLE = {
    0: ("ดำ", "#1A1A1A"),
    1: ("น้ำตาล", "#6F4A2A"),
    2: ("แดง", "#C0392B"),
    3: ("ส้ม", "#D2691E"),
    4: ("เหลือง", "#D4AC0D"),
    5: ("เขียว", "#2E7D32"),
    6: ("น้ำเงิน", "#1F5FA8"),
    7: ("ม่วง", "#6C3483"),
    8: ("เทา", "#7F8C8D"),
    9: ("ขาว", "#E8E6E1"),
}

# ค่าฐาน E12 (สองหลักแรกของตัวต้านทาน) — คูณด้วย 10^ทศนิยม เพื่อสุ่มค่าจริง
E12_BASES = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]
DECADE_CHOICES = [1, 2]  # จำกัดช่วง 100Ω–8.2kΩ ให้เหมาะกับแบตเตอรี่ 1.5–12V

LBL_DATA = "ข้อมูลที่วัดได้"
LBL_FIT = "เส้น fit"

st.set_page_config(page_title="Ohm's Law Lab", layout="wide")


def empty_data():
    return pd.DataFrame(
        {COL_V: pd.Series(dtype="float64"), COL_I: pd.Series(dtype="float64")}
    )


def randomize_resistor():
    """สุ่มตัวต้านทานปริศนาใหม่ พร้อมคำนวณแถบสีให้ตรงกับค่าที่สุ่มได้"""
    base = random.choice(E12_BASES)
    decade = random.choice(DECADE_CHOICES)
    nominal = base * (10 ** decade)  # ค่าที่ระบุจากแถบสี (โอห์ม)
    d1, d2 = base // 10, base % 10
    tol_name, tol_color, tol_pct = random.choice(TOLERANCE_OPTIONS)
    st.session_state.nominal_R = nominal
    st.session_state.bands = [
        BAND_COLOR_TABLE[d1][1], BAND_COLOR_TABLE[d2][1], BAND_COLOR_TABLE[decade][1], tol_color
    ]
    st.session_state.band_names = [
        BAND_COLOR_TABLE[d1][0], BAND_COLOR_TABLE[d2][0], BAND_COLOR_TABLE[decade][0], tol_name
    ]
    st.session_state.tolerance_pct = tol_pct
    # ค่าความต้านทานจริง คลาดเคลื่อนจากค่าที่พิมพ์ได้ไม่เกิน ±tolerance ของแถบที่ 4 ที่สุ่มได้
    st.session_state.R_true = nominal * (1 + random.uniform(-tol_pct, tol_pct))
    # สเกลเครื่องวัดต้องปรับตามค่า R ที่สุ่มได้ในรอบนี้เสมอ
    st.session_state.max_I_gauge = (max(BATTERY_OPTIONS) / nominal * 1000) * 1.3  # mA, เผื่อ 30%
    st.session_state.data = empty_data()
    st.session_state.last_I = 0.0
    st.session_state.last_V = 0.0
    st.session_state.from_I = 0.0  # ค่าเริ่มต้นของเข็มตอน animate
    st.session_state.from_V = 0.0
    st.session_state.measured = False
    # เปลี่ยน key ของตารางทุกครั้งที่สุ่มใหม่ เพื่อล้างการแก้ไขเก่าที่ค้างอยู่
    st.session_state.editor_ver = st.session_state.get("editor_ver", 0) + 1


# ----------------------------------------------------------------------
# state เริ่มต้น
# ----------------------------------------------------------------------
if "R_true" not in st.session_state:
    randomize_resistor()

MAX_V_GAUGE = max(BATTERY_OPTIONS) * 1.15
MAX_I_GAUGE = st.session_state.max_I_gauge  # ปรับตามค่าตัวต้านทานที่สุ่มได้ในรอบนี้


# ----------------------------------------------------------------------
# ฟิสิกส์: จำลองการวัดค่า (มี noise เล็กน้อยให้สมจริง)
# ----------------------------------------------------------------------
def measure(battery_voltage, R_true, r_internal=8.0):
    V_measured_ideal = battery_voltage * (R_true / (R_true + r_internal))
    V_measured = V_measured_ideal * (1 + random.uniform(-0.01, 0.01))
    I_measured = (V_measured / R_true) * 1000 * (1 + random.uniform(-0.015, 0.015))  # mA
    return round(V_measured, 3), round(I_measured, 3)


# ----------------------------------------------------------------------
# callbacks (รันก่อนสคริปต์ rerun ทำให้หน้าปัดได้ค่าใหม่ในรอบเดียวกัน)
# ----------------------------------------------------------------------
def on_randomize():
    randomize_resistor()


def on_measure():
    new_V, new_I = measure(st.session_state.battery_v, st.session_state.R_true)
    st.session_state.from_I = st.session_state.last_I
    st.session_state.from_V = st.session_state.last_V
    st.session_state.last_I = new_I
    st.session_state.last_V = new_V
    st.session_state.measured = True


def on_record():
    new_row = pd.DataFrame([{COL_V: st.session_state.last_V, COL_I: st.session_state.last_I}])
    st.session_state.data = pd.concat([st.session_state.data, new_row], ignore_index=True)
    st.toast("บันทึกค่าแล้ว")


# ----------------------------------------------------------------------
# วงจร + หน้าปัด (SVG)
# ----------------------------------------------------------------------
def circuit_svg(bands, band_names):
    band_rects = ""
    for y, color, name in zip([116, 130, 144, 172], bands, band_names):
        if name == "ไม่มีสี":  # ไม่มีแถบที่ 4 เลย
            continue
        band_rects += f'<rect x="305" y="{y}" width="30" height="7" fill="{color}"/>'
    w = WIRE_COLOR
    return f"""
<svg viewBox="0 0 460 320" class="circuit" xmlns="http://www.w3.org/2000/svg">
  <g stroke="{w}" stroke-width="2" stroke-linecap="round">
    <line x1="80" y1="60" x2="320" y2="60"/>
    <line x1="80" y1="60" x2="80" y2="260"/>
    <line x1="320" y1="60" x2="320" y2="110"/>
    <line x1="320" y1="190" x2="320" y2="260"/>
    <line x1="320" y1="260" x2="220" y2="260"/>
    <line x1="180" y1="260" x2="80" y2="260"/>
  </g>
  <!-- แบตเตอรี่ -->
  <line x1="62" y1="165" x2="98" y2="165" stroke="{w}" stroke-width="2" stroke-linecap="round"/>
  <line x1="71" y1="185" x2="89" y2="185" stroke="{w}" stroke-width="5" stroke-linecap="round"/>
  <text x="105" y="160" font-size="14" dominant-baseline="central">+</text>
  <text x="105" y="190" font-size="14" dominant-baseline="central">-</text>
  <text x="10" y="150" font-size="13" dominant-baseline="central">แบตเตอรี่</text>
  <text x="10" y="168" font-size="11" fill="#5B6478" dominant-baseline="central">(เปลี่ยนได้)</text>
  <!-- ตัวต้านทาน -->
  <rect x="305" y="110" width="30" height="80" rx="4" fill="#E8D9B0" stroke="{w}" stroke-width="1"/>
  {band_rects}
  <text x="345" y="104" font-size="11" dominant-baseline="central">ตัวต้านทาน</text>
  <text x="345" y="118" font-size="11" dominant-baseline="central">ปริศนา</text>
  <!-- แอมมิเตอร์ -->
  <circle cx="200" cy="260" r="18" fill="white" stroke="{w}" stroke-width="1.5"/>
  <text x="200" y="260" font-size="13" font-weight="bold" text-anchor="middle" dominant-baseline="central">A</text>
  <!-- โวลต์มิเตอร์ (ขนาน) -->
  <path d="M320,110 L385,110 L385,190 L320,190" fill="none" stroke="{w}" stroke-width="1.2" stroke-dasharray="4 4"/>
  <circle cx="385" cy="150" r="16" fill="white" stroke="{w}" stroke-width="1.5"/>
  <text x="385" y="150" font-size="13" font-weight="bold" text-anchor="middle" dominant-baseline="central">V</text>
</svg>"""


G_CX, G_CY, G_R = 150, 150, 120


def gauge_svg(gid, label, max_value, n_ticks=6):
    """หน้าปัดครึ่งวงกลม: ขีดสเกล + เข็ม (เข็มถูกหมุนด้วย JS)"""
    ticks = ""
    for i in range(n_ticks + 1):
        frac = i / n_ticks
        theta = np.pi * (1 - frac)
        c, s = np.cos(theta), np.sin(theta)
        x1, y1 = G_CX + 0.86 * G_R * c, G_CY - 0.86 * G_R * s
        x2, y2 = G_CX + G_R * c, G_CY - G_R * s
        lx, ly = G_CX + 0.72 * G_R * c, G_CY - 0.72 * G_R * s
        ticks += (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{WIRE_COLOR}" stroke-width="1.5"/>'
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="10" text-anchor="middle" '
            f'dominant-baseline="central">{max_value * frac:.1f}</text>'
        )
    return f"""
<svg viewBox="0 0 300 192" class="gauge" xmlns="http://www.w3.org/2000/svg">
  <path d="M {G_CX - G_R},{G_CY} A {G_R},{G_R} 0 0 1 {G_CX + G_R},{G_CY} Z"
        fill="{FACE_COLOR}" stroke="{WIRE_COLOR}" stroke-width="1.5"/>
  {ticks}
  <g id="needle-{gid}" transform="rotate(-90 {G_CX} {G_CY})">
    <line x1="{G_CX}" y1="{G_CY}" x2="{G_CX}" y2="{G_CY - 0.82 * G_R:.1f}"
          stroke="{NEEDLE_COLOR}" stroke-width="3.5" stroke-linecap="round"/>
  </g>
  <circle cx="{G_CX}" cy="{G_CY}" r="6" fill="{NEEDLE_COLOR}"/>
  <text id="value-{gid}" x="{G_CX}" y="{G_CY + 0.22 * G_R:.1f}" font-size="18" font-weight="bold"
        text-anchor="middle" dominant-baseline="central">0.00</text>
  <text x="{G_CX}" y="{G_CY - 1.12 * G_R:.1f}" font-size="14" text-anchor="middle"
        dominant-baseline="central">{label}</text>
</svg>"""


SIM_TEMPLATE = """
<style>
  body { margin:0; font-family: Tahoma, "Noto Sans Thai", "Segoe UI", sans-serif; color:#1C2333; }
  .circuit { width:100%; max-width:520px; display:block; margin:0 auto; }
  .gauges { display:flex; gap:8px; margin-top:6px; }
  .gauge { width:50%; height:auto; }
</style>
__CIRCUIT__
<div class="gauges">__GAUGE_I__ __GAUGE_V__</div>
<script>
const CX = __CX__, CY = __CY__;
const gauges = __CFG__;

function setGauge(g, val){
  const frac = g.max <= 0 ? 0 : Math.min(Math.max(val / g.max, 0), 1);
  document.getElementById("needle-" + g.id)
          .setAttribute("transform", "rotate(" + ((frac - 0.5) * 180) + " " + CX + " " + CY + ")");
  document.getElementById("value-" + g.id).textContent = val.toFixed(2) + " " + g.unit;
}

function run(g){
  setGauge(g, g.from);
  if (g.from === g.to) return;
  const t0 = performance.now(), dur = 600;
  function step(t){
    const p = Math.min((t - t0) / dur, 1);
    const eased = 1 - (1 - p) * (1 - p);  // ease-out
    setGauge(g, g.from + (g.to - g.from) * eased);
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
gauges.forEach(run);
</script>
"""


def simulation_html():
    ss = st.session_state
    cfg = [
        {"id": "I", "unit": "mA", "max": MAX_I_GAUGE, "from": ss.from_I, "to": ss.last_I},
        {"id": "V", "unit": "V", "max": MAX_V_GAUGE, "from": ss.from_V, "to": ss.last_V},
    ]
    return (
        SIM_TEMPLATE
        .replace("__CIRCUIT__", circuit_svg(ss.bands, ss.band_names))
        .replace("__GAUGE_I__", gauge_svg("I", "แอมมิเตอร์ (I)", MAX_I_GAUGE))
        .replace("__GAUGE_V__", gauge_svg("V", "โวลต์มิเตอร์ (V)", MAX_V_GAUGE))
        .replace("__CX__", str(G_CX))
        .replace("__CY__", str(G_CY))
        .replace("__CFG__", json.dumps(cfg))
    )


# ----------------------------------------------------------------------
# fit ฟังก์ชันต่างๆ (ใช้ np.polyfit — สำหรับ Power/Exponential ทำบนข้อมูลที่ log แล้ว)
# ----------------------------------------------------------------------
def r_squared(y, y_pred):
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return 1 - ss_res / ss_tot if ss_tot != 0 else 0.0


def fit_curve(x, y, kind):
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    if kind == "Linear":
        m, c = np.polyfit(x, y, 1)
        y_pred = m * x + c
        xs = np.linspace(x.min(), x.max(), 100)
        ys = m * xs + c
        eq = f"y = {m:.4f}x + {c:.4f}"
        return xs, ys, eq, r_squared(y, y_pred)
    if kind == "Quadratic":
        a, b, c = np.polyfit(x, y, 2)
        y_pred = a * x**2 + b * x + c
        xs = np.linspace(x.min(), x.max(), 100)
        ys = a * xs**2 + b * xs + c
        eq = f"y = {a:.4f}x² + {b:.4f}x + {c:.4f}"
        return xs, ys, eq, r_squared(y, y_pred)
    if kind == "Power":
        mask = (x > 0) & (y > 0)
        b, loga = np.polyfit(np.log(x[mask]), np.log(y[mask]), 1)
        a = np.exp(loga)
        y_pred = a * x**b
        xs = np.linspace(max(x.min(), 1e-6), x.max(), 100)
        ys = a * xs**b
        eq = f"y = {a:.4f}·x^{b:.4f}"
        return xs, ys, eq, r_squared(y, y_pred)
    if kind == "Exponential":
        mask = y > 0
        b, loga = np.polyfit(x[mask], np.log(y[mask]), 1)
        a = np.exp(loga)
        y_pred = a * np.exp(b * x)
        xs = np.linspace(x.min(), x.max(), 100)
        ys = a * np.exp(b * xs)
        eq = f"y = {a:.4f}·e^({b:.4f}x)"
        return xs, ys, eq, r_squared(y, y_pred)
    return x, y, "", None


# ========================================================================
# UI
# ========================================================================
st.title("แลปกฎของโอห์ม — วงจรทดลองแบบ interactive")
st.caption("เปลี่ยนแบตเตอรี่ → วัดค่า I และ V → บันทึกลงตาราง → พล็อตกราฟหาความต้านทานปริศนา")

col_canvas, col_controls = st.columns([1.3, 1])

with col_canvas:
    st.subheader("พื้นที่จำลอง")
    sim_html = simulation_html().strip()
    if hasattr(st, "iframe"):  # Streamlit รุ่นใหม่ (components.html ถูกประกาศเลิกใช้)
        st.iframe(sim_html, height=600)
    else:
        components.html(sim_html, height=600)

with col_controls:
    st.subheader("แผงควบคุม")
    st.select_slider(
        "เลือกแบตเตอรี่ (โวลต์)", options=BATTERY_OPTIONS, value=BATTERY_OPTIONS[2], key="battery_v"
    )
    teacher_mode = st.checkbox("แสดงค่าจริง (สำหรับครู)")
    if teacher_mode:
        names = " - ".join(st.session_state.band_names)
        st.info(
            f"แถบสี: {names}\n\n"
            f"ค่าที่พิมพ์ตามแถบสี: {st.session_state.nominal_R:.0f} Ω "
            f"±{st.session_state.tolerance_pct*100:.0f}%\n\n"
            f"(ค่าความต้านทานจริงจะแสดงในส่วนตรวจคำตอบท้ายหน้า)"
        )

    st.button("🔄 สุ่มตัวต้านทานใหม่", use_container_width=True, on_click=on_randomize)
    st.button("▶ วัดค่า", use_container_width=True, on_click=on_measure)

    if st.session_state.measured:
        st.metric("ความต่างศักย์ (V)", f"{st.session_state.last_V:.2f} V")
        st.metric("กระแสไฟฟ้า (I)", f"{st.session_state.last_I:.2f} mA")

    st.button(
        "＋ บันทึกค่า",
        use_container_width=True,
        disabled=not st.session_state.measured,
        on_click=on_record,
    )

st.divider()

# ----------------------------------------------------------------------
# ตารางข้อมูล
# ----------------------------------------------------------------------
st.subheader("ตารางข้อมูลที่บันทึก")
edited = st.data_editor(
    st.session_state.data,
    num_rows="dynamic",
    use_container_width=True,
    key=f"data_editor_{st.session_state.editor_ver}",
)

st.divider()

# ----------------------------------------------------------------------
# พล็อตกราฟ + fit
# ----------------------------------------------------------------------
st.subheader("พล็อตกราฟ + Fit เส้นโค้ง")

df = edited.dropna()
if len(df) < 2:
    st.info("บันทึกข้อมูลอย่างน้อย 2 จุดเพื่อพล็อตกราฟ")
else:
    c1, c2, c3 = st.columns(3)
    with c1:
        x_col = st.selectbox("แกน X", df.columns, index=0)
    with c2:
        y_col = st.selectbox("แกน Y", df.columns, index=1)
    with c3:
        fit_kind = st.selectbox("รูปแบบ Fit", ["ไม่ fit", "Linear", "Quadratic", "Power", "Exponential"])

    x_vals = df[x_col].astype(float).values
    y_vals = df[y_col].astype(float).values

    eq_text, r2_text = "", ""
    fit_df = None
    if fit_kind != "ไม่ fit":
        try:
            xs, ys, eq, r2 = fit_curve(x_vals, y_vals, fit_kind)
            fit_df = pd.DataFrame({"x": xs, "y": ys, "series": LBL_FIT})
            eq_text, r2_text = eq, f"R² = {r2:.4f}"
        except Exception as e:
            st.warning(f"ไม่สามารถ fit ได้กับข้อมูลนี้: {e}")

    pts_df = pd.DataFrame({"x": x_vals, "y": y_vals, "series": LBL_DATA})
    enc_x = alt.X("x:Q", title=x_col, scale=alt.Scale(zero=False))
    enc_y = alt.Y("y:Q", title=y_col, scale=alt.Scale(zero=False))
    domain = [LBL_DATA] + ([LBL_FIT] if fit_df is not None else [])
    colors = ["#3B4FD6"] + (["#D85A30"] if fit_df is not None else [])
    enc_color = alt.Color(
        "series:N",
        scale=alt.Scale(domain=domain, range=colors),
        legend=alt.Legend(title=None, orient="top-left"),
    )

    layers = []
    if fit_df is not None:
        layers.append(
            alt.Chart(fit_df).mark_line(strokeWidth=2).encode(x=enc_x, y=enc_y, color=enc_color)
        )
    layers.append(
        alt.Chart(pts_df)
        .mark_circle(size=90, opacity=1)
        .encode(
            x=enc_x,
            y=enc_y,
            color=enc_color,
            tooltip=[alt.Tooltip("x:Q", title=x_col), alt.Tooltip("y:Q", title=y_col)],
        )
    )
    chart = alt.layer(*layers).properties(height=380).configure_axis(gridOpacity=0.25)
    st.altair_chart(chart, use_container_width=True)

    if eq_text:
        st.markdown(f"**สมการ fit:** `{eq_text}`  |  **{r2_text}**")
        if fit_kind == "Linear" and x_col == COL_I and y_col == COL_V:
            slope = float(np.polyfit(x_vals, y_vals, 1)[0])
            st.caption(f"หมายเหตุ: ความชัน ≈ ความต้านทาน R ≈ {slope*1000:.1f} Ω (จาก V = IR, I หน่วย mA)")

st.divider()

# ----------------------------------------------------------------------
# ตรวจคำตอบ + วิเคราะห์ % ความคลาดเคลื่อน (เปิดหลังคำนวณ R จากกราฟด้วยตนเอง)
# ----------------------------------------------------------------------
st.subheader("ตรวจคำตอบ: วิเคราะห์ % ความคลาดเคลื่อน")
with st.expander("เปิดเมื่อคำนวณค่า R จากกราฟด้วยตนเองแล้ว"):
    student_R = st.number_input("ค่า R ที่คำนวณได้จากกราฟ (Ω)", min_value=0.0, step=1.0, value=0.0)
    if student_R > 0:
        st.write(f"ค่าความต้านทานจริงของตัวต้านทานปริศนา: **{st.session_state.R_true:.1f} Ω**")
        pct_error = abs(student_R - st.session_state.R_true) / st.session_state.R_true * 100
        st.metric("% ความคลาดเคลื่อน", f"{pct_error:.2f}%")
        tol_pct = st.session_state.tolerance_pct * 100
        if pct_error <= tol_pct:
            st.success(f"อยู่ในช่วงความคลาดเคลื่อนที่ยอมรับได้ของตัวต้านทาน (±{tol_pct:.0f}%) ✅")
        else:
            st.warning(f"เกินช่วงความคลาดเคลื่อนที่ยอมรับได้ (±{tol_pct:.0f}%) ลองตรวจสอบข้อมูลหรือวิธี fit อีกครั้ง")
