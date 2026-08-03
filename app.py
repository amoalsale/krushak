import streamlit as st
import pandas as pd
import difflib
import io
import json
import os
import base64
import requests

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Auto-Invoice Generator | Farm Produce",
    page_icon="🚜",
    layout="wide"
)

st.markdown("""
    <style>
    .main-header { font-size: 24pt; font-weight: bold; color: #1a365d; margin-bottom: 5px; }
    .sub-header { font-size: 11pt; color: #4a5568; margin-bottom: 20px; }
    .stMetric { background-color: #f7fafc; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0; }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. SIDEBAR CONFIGURATION
# -----------------------------------------------------------------------------
st.sidebar.title("📄 Invoice & Company Details")

# Company/sheet details are persisted to invoice_config.json inside this same
# GitHub repo (via the GitHub Contents API), so the sidebar stays pre-filled
# across app restarts AND full redeploys - not just within one running
# container. If no GitHub token is configured (e.g. running locally), we
# fall back to a local JSON file that only survives within that session.
GITHUB_OWNER = "amoalsale"
GITHUB_REPO = "krushak"
GITHUB_BRANCH = "master"
CONFIG_PATH_IN_REPO = "invoice_config.json"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{CONFIG_PATH_IN_REPO}"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{CONFIG_PATH_IN_REPO}"

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "invoice_config.json")

FALLBACK_CONFIG = {
    "sheet_url": "https://docs.google.com/spreadsheets/d/12a9031ezxQ2GTVyULyw-ddpEfVUYm0rkC4dthS-i68Q/export?format=csv",
    "supplier_name": "Ekrushak Farm Fresh Pvt Ltd",
    "supplier_address": "Milkat No.635, Wadgaon Anand, Tal- Junnar, Dist-Pune 412411",
    "supplier_gstin": "27AAJCE4239R1ZX",
    "buyer_name": "Farm Fresh",
    "buyer_address": "Milkat no- 635, Wadgaon Anand, Tal- Junnar, Dist-Pune 412411",
    "buyer_gstin": "27AKYPD1464B1Z7",
    "gst_rate": 0.0,
}

# -----------------------------------------------------------------------------
# INVOICE LINE-ITEM COLUMN DEFINITIONS
# -----------------------------------------------------------------------------
# S.No and Description are always shown; the rest are optional via the
# sidebar "Invoice Columns" control, which applies to both the on-screen
# preview table and the downloaded PDF.
OPTIONAL_INVOICE_COLUMNS = [
    {"key": "Qty", "label": "Qty", "width": 5, "align": "right"},
    {"key": "UOM", "label": "UOM", "width": 6, "align": "center"},
    {"key": "Rate", "label": "Rate (₹)", "width": 8, "align": "right", "money": True},
    {"key": "Taxable Value", "label": "Taxable Value", "width": 9, "align": "right", "money": True},
    {"key": "CGST Rate", "label": "CGST %", "width": 5, "align": "center"},
    {"key": "CGST Amt", "label": "CGST Amt", "width": 7, "align": "right", "money": True},
    {"key": "SGST Rate", "label": "SGST %", "width": 5, "align": "center"},
    {"key": "SGST Amt", "label": "SGST Amt", "width": 7, "align": "right", "money": True},
    {"key": "Total", "label": "Total (₹)", "width": 9, "align": "right", "money": True},
]
SUMMABLE_COLUMN_KEYS = {"Qty", "Taxable Value", "CGST Amt", "SGST Amt", "Total"}

def _get_github_token():
    try:
        return st.secrets.get("GITHUB_TOKEN")
    except Exception:
        return None

def _save_local(values):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def load_saved_config():
    """Load previously saved company details. Tries the copy committed in the
    GitHub repo first (public read, no token needed, survives redeploys),
    then the local file, then falls back to defaults for anything missing."""
    config = FALLBACK_CONFIG.copy()
    try:
        resp = requests.get(GITHUB_RAW_URL, timeout=5)
        if resp.status_code == 200:
            config.update(resp.json())
            return config
    except Exception:
        pass
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception:
            pass
    return config

def save_config(values):
    """Persist config. Writes to the GitHub repo (survives redeploys) when a
    GITHUB_TOKEN secret is configured; always also writes the local file as a
    same-session cache/fallback."""
    _save_local(values)

    token = _get_github_token()
    if not token:
        return True, "local"

    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        get_resp = requests.get(
            GITHUB_API_URL, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=10
        )
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

        content_b64 = base64.b64encode(
            json.dumps(values, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {
            "message": "Update saved invoice config",
            "content": content_b64,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(GITHUB_API_URL, headers=headers, json=payload, timeout=10)
        if put_resp.status_code in (200, 201):
            return True, "github"
        return True, "local"
    except Exception:
        return True, "local"

saved_config = load_saved_config()

sheet_url = st.sidebar.text_input(
    "Google Sheet Price Master CSV URL",
    value=saved_config["sheet_url"],
    help="Published CSV URL of your Google Sheet Price List"
)

inv_number = st.sidebar.text_input("Invoice Number", "INV/2026-27/0842")
inv_date = st.sidebar.date_input("Invoice Date")

st.sidebar.subheader("Supplier (Company A)")
supplier_name = st.sidebar.text_input("Supplier Name", saved_config["supplier_name"])
supplier_address = st.sidebar.text_input("Supplier Address", saved_config["supplier_address"])
supplier_gstin = st.sidebar.text_input("Supplier GSTIN", saved_config["supplier_gstin"])

st.sidebar.subheader("Billed To (Company B)")
buyer_name = st.sidebar.text_input("Buyer Name", saved_config["buyer_name"])
buyer_address = st.sidebar.text_input("Buyer Address", saved_config["buyer_address"])
buyer_gstin = st.sidebar.text_input("Buyer GSTIN", saved_config["buyer_gstin"])

st.sidebar.subheader("Tax Settings")
gst_rate = st.sidebar.number_input(
    "GST Rate (%)",
    min_value=0.0,
    max_value=100.0,
    value=float(saved_config["gst_rate"]),
    step=0.5,
    format="%.2f",
    help="Applied to every line item on the invoice, overriding the price master sheet's own GST RATE column."
)

st.sidebar.subheader("Invoice Columns")
_optional_column_keys = [c["key"] for c in OPTIONAL_INVOICE_COLUMNS]
selected_column_keys = st.sidebar.multiselect(
    "Columns to show on the invoice",
    options=_optional_column_keys,
    default=_optional_column_keys,
    help="S.No and Description are always shown. Applies to both the on-screen preview and the downloaded PDF."
)
visible_columns = [c for c in OPTIONAL_INVOICE_COLUMNS if c["key"] in selected_column_keys]

if st.sidebar.button("💾 Save as Default for Next Time"):
    saved_ok, saved_where = save_config({
        "sheet_url": sheet_url,
        "supplier_name": supplier_name,
        "supplier_address": supplier_address,
        "supplier_gstin": supplier_gstin,
        "buyer_name": buyer_name,
        "buyer_address": buyer_address,
        "buyer_gstin": buyer_gstin,
        "gst_rate": gst_rate,
    })
    if saved_ok and saved_where == "github":
        st.sidebar.success("Saved to GitHub — these details will persist across redeploys.")
    elif saved_ok:
        st.sidebar.warning(
            "Saved for this session only. Add a GITHUB_TOKEN secret in "
            "Streamlit Cloud's app settings to make this permanent across redeploys."
        )
    else:
        st.sidebar.error("Could not save details on this server.")

# -----------------------------------------------------------------------------
# 3. PRICE MASTER DATA LOADER
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_price_master(url):
    try:
        df = pd.read_csv(url)
        # Standardize column headers
        df.columns = [c.strip().upper() for c in df.columns]
        return df
    except Exception as e:
        st.error(f"Error loading Price Master from Google Sheet: {e}")
        return None

# -----------------------------------------------------------------------------
# 4. PACKAGING REPORT XLSX PARSER
# -----------------------------------------------------------------------------

def parse_xlsx_items(uploaded_file):
    """Extracts Item Names and Quantities from a packaging-report XLSX/XLS
    export with 'Product' and 'Quantity' columns."""
    uploaded_file.seek(0)
    df = pd.read_excel(uploaded_file)

    product_col = next(
        (c for c in df.columns if str(c).strip().lower() == "product"), df.columns[0]
    )
    qty_col = next(
        (c for c in df.columns if str(c).strip().lower() == "quantity"), df.columns[1]
    )

    extracted = []
    for _, row in df.iterrows():
        name, qty = row[product_col], row[qty_col]
        if pd.isna(name) or pd.isna(qty):
            continue
        name_clean = str(name).strip()
        try:
            qty_int = int(qty)
        except (TypeError, ValueError):
            continue
        if len(name_clean) > 1 and qty_int > 0:
            extracted.append({"raw_name": name_clean, "qty": qty_int})

    return extracted
# -----------------------------------------------------------------------------
# 5. BILINGUAL SMART ITEM MATCHER
# -----------------------------------------------------------------------------
def _norm(s):
    return str(s).strip().lower().replace(" ", "").replace("/", "").replace("-", "")

def _score_candidates(query, master_list):
    """Finds the single best-scoring master-list candidate for `query`,
    regardless of any acceptance threshold. Returns (best_item, best_ratio) -
    best_item is None with best_ratio 0.0 only if master_list is empty or no
    candidate could be found at all (not even a loose fuzzy one).

    Candidates are pooled from exact match, substring containment, sub-part
    containment, and fuzzy search, then ranked by overall similarity - rather
    than returning the first containment hit - so a short common word (e.g.
    "कांदा"/onion) embedded inside an unrelated longer product name can't
    shadow a much better match elsewhere in the list.
    """
    if not query or not master_list:
        return None, 0.0

    q_clean = _norm(query)

    # 1. Exact match short-circuits immediately.
    for item in master_list:
        if _norm(item) == q_clean:
            return item, 1.0

    candidates = []

    # 2. Containment either direction.
    for item in master_list:
        i_clean = _norm(item)
        if q_clean in i_clean or i_clean in q_clean:
            candidates.append(item)

    # 3. Sub-part containment (e.g. Marathi part before '/' or English part after '/')
    parts = [p.strip() for p in query.split("/") if p.strip()]
    for p in parts:
        p_sub = p.lower()
        if len(p_sub) > 2:
            for item in master_list:
                if p_sub in str(item).lower() and item not in candidates:
                    candidates.append(item)

    # 4. Fuzzy candidates (skip very short/ambiguous fragments, which are
    # prone to matching unrelated products on noise like stray unit tokens)
    if len(query.strip()) >= 3:
        for fm in difflib.get_close_matches(query, [str(m) for m in master_list], n=5, cutoff=0.3):
            if fm not in candidates:
                candidates.append(fm)

    # 5. If still nothing, fall back to whatever difflib considers globally
    # closest (even a poor match) purely so callers can explain *why* a
    # match failed - this is never used to accept a match.
    if not candidates:
        closest = difflib.get_close_matches(query, [str(m) for m in master_list], n=1, cutoff=0.0)
        if not closest:
            return None, 0.0
        candidates = closest

    best_item, best_ratio = None, -1.0
    for item in candidates:
        ratio = difflib.SequenceMatcher(None, q_clean, _norm(item)).ratio()
        if ratio > best_ratio:
            best_item, best_ratio = item, ratio

    return best_item, best_ratio

MATCH_CUTOFF = 0.75

def find_best_match(query, master_list, cutoff=MATCH_CUTOFF):
    """Bilingual (Marathi/English) matching logic against the price master.
    Returns the best-scoring candidate only if it clears `cutoff`; anything
    weaker is treated as unmatched rather than guessed."""
    best_item, best_ratio = _score_candidates(query, master_list)
    return best_item if best_ratio >= cutoff else None

# -----------------------------------------------------------------------------
# 6. NUMBER TO WORDS CONVERTER
# -----------------------------------------------------------------------------
def number_to_words(n):
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", 
             "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    
    if n == 0:
        return "Zero"
        
    def convert_hundreds(num):
        res = ""
        if num >= 100:
            res += units[num // 100] + " Hundred "
            num %= 100
        if num >= 20:
            res += tens[num // 10] + " "
            num %= 10
        if num > 0:
            res += units[num] + " "
        return res.strip()

    res = ""
    if n >= 10000000:
        res += convert_hundreds(n // 10000000) + " Crore "
        n %= 10000000
    if n >= 100000:
        res += convert_hundreds(n // 100000) + " Lakh "
        n %= 100000
    if n >= 1000:
        res += convert_hundreds(n // 1000) + " Thousand "
        n %= 1000
    if n > 0:
        res += convert_hundreds(n)
        
    return res.strip() + " Only"

# -----------------------------------------------------------------------------
# 7. INVOICE PDF GENERATOR (Cross-Platform)
# -----------------------------------------------------------------------------
def generate_pdf_bytes(df_rows, total_taxable, total_cgst, total_sgst, rounded_total, round_off, gst_summary, visible_columns):

    def cell_value(row, col):
        val = row[col["key"]]
        return f"{val:,.2f}" if col.get("money") else val

    rows_html = ""
    for idx, row in enumerate(df_rows, start=1):
        cells = f'<td style="text-align: center;">{idx}</td><td>{row["Description"]}</td>'
        for col in visible_columns:
            cells += f'<td style="text-align: {col["align"]};">{cell_value(row, col)}</td>'
        rows_html += f"<tr>{cells}</tr>\n"

    # S.No + Description always get a fixed 4% / the remainder of the width;
    # optional columns keep their own base width so the table stays
    # proportioned however many of them are visible.
    desc_width = 100 - 4 - sum(col["width"] for col in visible_columns)
    colgroup_html = f'<col style="width: 4%;">\n<col style="width: {desc_width}%;">\n'
    colgroup_html += "\n".join(f'<col style="width: {col["width"]}%;">' for col in visible_columns)

    thead_html = f'<th style="width: 4%;">S.No</th><th style="width: {desc_width}%;">Description of Farm Produce</th>'
    thead_html += "".join(f'<th style="width: {col["width"]}%;">{col["label"]}</th>' for col in visible_columns)

    total_qty = sum(r["Qty"] for r in df_rows)
    column_totals = {
        "Qty": total_qty,
        "Taxable Value": total_taxable,
        "CGST Amt": total_cgst,
        "SGST Amt": total_sgst,
        "Total": total_taxable + total_cgst + total_sgst,
    }
    label_span = 0
    for col in visible_columns:
        if col["key"] in SUMMABLE_COLUMN_KEYS:
            break
        label_span += 1
    totals_row_html = f'<td colspan="{2 + label_span}" style="text-align: right;">Total Gross Values</td>'
    for col in visible_columns[label_span:]:
        if col["key"] in SUMMABLE_COLUMN_KEYS:
            value = column_totals[col["key"]]
            formatted = f"{value:,.2f}" if col.get("money") else value
            totals_row_html += f'<td style="text-align: right;">{formatted}</td>'
        else:
            totals_row_html += "<td></td>"

    summary_rows_html = ""
    for rate, data in gst_summary.items():
        summary_rows_html += f"""
        <tr>
            <td style="text-align: center;">{rate:.1f}%</td>
            <td style="text-align: right;">{data['taxable']:,.2f}</td>
            <td style="text-align: center;">{rate/2:.1f}%</td>
            <td style="text-align: right;">{data['cgst']:,.2f}</td>
            <td style="text-align: center;">{rate/2:.1f}%</td>
            <td style="text-align: right;">{data['sgst']:,.2f}</td>
            <td style="text-align: right;">{(data['cgst'] + data['sgst']):,.2f}</td>
        </tr>
        """

    total_words = number_to_words(rounded_total)

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4 landscape; margin: 8mm; }}
            body {{ font-family: "Noto Sans", Helvetica, Arial, "Lohit Devanagari", "Lohit Marathi", sans-serif; font-size: 7.5pt; color: #333; line-height: 1.2; }}
            .title {{ text-align: center; font-size: 15pt; font-weight: bold; color: #1a365d; margin-bottom: 2px; }}
            .subtitle {{ text-align: center; font-size: 8pt; font-style: italic; color: #555; margin-bottom: 10px; }}
            table {{ width: 100%; table-layout: fixed; border-collapse: collapse; margin-top: 6px; }}
            th {{ background-color: #1a365d; color: white; font-weight: bold; font-size: 7pt; padding: 3px; border: 1px solid #1a365d; word-wrap: break-word; overflow-wrap: break-word; }}
            td {{ border: 1px solid #cbd5e0; padding: 2.5px; font-size: 7pt; word-wrap: break-word; overflow-wrap: break-word; }}
            .summary-th {{ background-color: #2d3748; color: white; }}
            .bold {{ font-weight: bold; }}
            .box {{ border: 1px solid #cbd5e0; padding: 6px; margin-bottom: 8px; }}
        </style>
    </head>
    <body>
        <div class="title">TAX INVOICE</div>
        <div class="subtitle">(ORIGINAL FOR RECIPIENT)</div>

        <table>
            <tr>
                <td style="width: 50%; vertical-align: top;">
                    <div class="bold" style="font-size: 9pt; color: #1a365d;">SUPPLIER DETAILS</div>
                    <div class="bold">{supplier_name}</div>
                    <div>{supplier_address}</div>
                    <div><strong>GSTIN:</strong> {supplier_gstin} | <strong>State:</strong> Maharashtra (27)</div>
                </td>
                <td style="width: 50%; vertical-align: top;">
                    <div class="bold" style="font-size: 9pt; color: #1a365d;">INVOICE DETAILS</div>
                    <div><strong>Invoice No:</strong> {inv_number}</div>
                    <div><strong>Invoice Date:</strong> {inv_date.strftime('%d-%b-%Y')}</div>
                    <div><strong>Place of Supply:</strong> Maharashtra (Code 27 - Intra-State)</div>
                </td>
            </tr>
            <tr>
                <td style="vertical-align: top;">
                    <div class="bold" style="font-size: 9pt; color: #1a365d;">BILLED TO</div>
                    <div class="bold">{buyer_name}</div>
                    <div>{buyer_address}</div>
                    <div><strong>GSTIN:</strong> {buyer_gstin} | <strong>State:</strong> Maharashtra (27)</div>
                </td>
                <td style="vertical-align: top;">
                    <div class="bold" style="font-size: 9pt; color: #1a365d;">SHIPPED TO</div>
                    <div class="bold">{buyer_name}</div>
                    <div>{buyer_address}</div>
                </td>
            </tr>
        </table>

        <table>
            <colgroup>
                {colgroup_html}
            </colgroup>
            <thead>
                <tr>
                    {thead_html}
                </tr>
            </thead>
            <tbody>
                {rows_html}
                <tr style="font-weight: bold; background-color: #edf2f7;">
                    {totals_row_html}
                </tr>
            </tbody>
        </table>

        <br>
        <table>
            <tr>
                <td style="width: 60%; vertical-align: top;">
                    <div class="bold" style="color: #1a365d; margin-bottom: 4px;">GST TAX BREAKDOWN SUMMARY</div>
                    <table>
                        <thead>
                            <tr>
                                <th class="summary-th">GST Rate</th>
                                <th class="summary-th">Taxable Value</th>
                                <th class="summary-th">CGST %</th>
                                <th class="summary-th">CGST Amt</th>
                                <th class="summary-th">SGST %</th>
                                <th class="summary-th">SGST Amt</th>
                                <th class="summary-th">Total Tax</th>
                            </tr>
                        </thead>
                        <tbody>
                            {summary_rows_html}
                        </tbody>
                    </table>
                    <br>
                    <div><strong>Amount Chargeable in Words:</strong><br><span style="font-style: italic; color: #1a365d; font-weight: bold;">INR {total_words}</span></div>
                </td>
                <td style="width: 40%; vertical-align: top; background-color: #f7fafc;">
                    <table>
                        <tr><td>Total Taxable Value:</td><td style="text-align: right;">₹ {total_taxable:,.2f}</td></tr>
                        <tr><td>Total CGST Amount:</td><td style="text-align: right;">₹ {total_cgst:,.2f}</td></tr>
                        <tr><td>Total SGST Amount:</td><td style="text-align: right;">₹ {total_sgst:,.2f}</td></tr>
                        <tr><td>Round-off Adjustment:</td><td style="text-align: right;">₹ {round_off:+.2f}</td></tr>
                        <tr style="font-size: 10pt; font-weight: bold; color: #1a365d;">
                            <td>Grand Total:</td>
                            <td style="text-align: right;">₹ {rounded_total:,.2f}</td>
                        </tr>
                    </table>
                    <div style="margin-top: 30px; text-align: center; border-top: 1px solid #ccc; padding-top: 10px;">
                        For <strong>{supplier_name}</strong><br><br><br>
                        <strong>Authorised Signatory</strong>
                    </div>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    # Try WeasyPrint first, fallback to xhtml2pdf if native libraries are missing
    try:
        from weasyprint import HTML
        return HTML(string=html_content).write_pdf()
    except Exception:
        try:
            from xhtml2pdf import pisa
            pdf_buffer = io.BytesIO()
            pisa.CreatePDF(html_content, dest=pdf_buffer)
            return pdf_buffer.getvalue()
        except Exception as e:
            st.error(f"PDF Generation failed. Please install xhtml2pdf or weasyprint: {e}")
            return None

# -----------------------------------------------------------------------------
# 8. STREAMLIT MAIN APPLICATION INTERFACE
# -----------------------------------------------------------------------------
st.markdown('<div class="main-header">🚜 Auto-Invoice Generator for Farm Produce</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Upload a Packaging Report XLSX to parse products and generate a Maharashtra GST Tax Invoice instantly.</div>', unsafe_allow_html=True)

price_master_df = load_price_master(sheet_url)

if price_master_df is not None:
    uploaded_file = st.file_uploader("Drop Packaging Report XLSX here", type=["xlsx", "xls"])

    if uploaded_file is not None:
        st.info("Parsing XLSX Packaging Report and matching items against Price Master...")
        extracted_items = parse_xlsx_items(uploaded_file)

        if not extracted_items:
            st.error("No items could be extracted from the file. Please check its format.")
        else:
            # Column mapping check for Price Master
            pname_col = "PRODUCT NAME" if "PRODUCT NAME" in price_master_df.columns else price_master_df.columns[1]
            uom_col = "UOM" if "UOM" in price_master_df.columns else price_master_df.columns[4]
            price_col = "UNIT PRICE (INR)" if "UNIT PRICE (INR)" in price_master_df.columns else "UNIT PRICE"

            master_product_list = price_master_df[pname_col].dropna().tolist()

            processed_rows = []
            unmatched_items = []
            gst_summary = {}

            total_taxable = 0.0
            total_cgst = 0.0
            total_sgst = 0.0

            for item in extracted_items:
                raw_name = item["raw_name"]
                qty = item["qty"]
                
                closest_item, closest_ratio = _score_candidates(raw_name, master_product_list)
                best_match = closest_item if closest_ratio >= MATCH_CUTOFF else None

                # GST rate is a global override from the sidebar (applies to
                # every line item), not read per-item from the price master.
                gst_p = gst_rate

                if best_match:
                    row_data = price_master_df[price_master_df[pname_col] == best_match].iloc[0]

                    # Clean price
                    rate = float(str(row_data[price_col]).replace("₹", "").replace(",", "").strip())
                    uom_val = str(row_data[uom_col])
                    desc_val = str(row_data[pname_col])
                else:
                    if closest_item:
                        reason = f"Not found in price sheet. Closest match: {closest_item}"
                    else:
                        reason = "Not found in price sheet. No similar item found."
                    unmatched_items.append({"name": raw_name, "qty": qty, "reason": reason})
                    rate = 40.0
                    uom_val = "Kg"
                    desc_val = raw_name

                taxable = qty * rate
                cgst_p = gst_p / 2.0
                sgst_p = gst_p / 2.0
                cgst_amt = taxable * (cgst_p / 100.0)
                sgst_amt = taxable * (sgst_p / 100.0)
                item_total = taxable + cgst_amt + sgst_amt

                total_taxable += taxable
                total_cgst += cgst_amt
                total_sgst += sgst_amt

                # Update tax summary buckets
                if gst_p not in gst_summary:
                    gst_summary[gst_p] = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0}
                gst_summary[gst_p]["taxable"] += taxable
                gst_summary[gst_p]["cgst"] += cgst_amt
                gst_summary[gst_p]["sgst"] += sgst_amt

                processed_rows.append({
                    "Description": desc_val,
                    "Qty": qty,
                    "UOM": uom_val,
                    "Rate": rate,
                    "Taxable Value": taxable,
                    "CGST Rate": f"{cgst_p:.1f}%",
                    "CGST Amt": cgst_amt,
                    "SGST Rate": f"{sgst_p:.1f}%",
                    "SGST Amt": sgst_amt,
                    "Total": item_total
                })

            # Consolidate duplicate line items: the same product can appear on
            # multiple rows of the source report, which previously produced
            # repeated S.No rows for one product instead of a single row with
            # the combined quantity.
            consolidated_rows = {}
            consolidation_order = []
            for row in processed_rows:
                dedupe_key = (row["Description"], row["UOM"], row["Rate"])
                if dedupe_key not in consolidated_rows:
                    consolidated_rows[dedupe_key] = dict(row)
                    consolidation_order.append(dedupe_key)
                else:
                    existing = consolidated_rows[dedupe_key]
                    existing["Qty"] += row["Qty"]
                    existing["Taxable Value"] += row["Taxable Value"]
                    existing["CGST Amt"] += row["CGST Amt"]
                    existing["SGST Amt"] += row["SGST Amt"]
                    existing["Total"] += row["Total"]
            processed_rows = [consolidated_rows[k] for k in consolidation_order]

            display_column_keys = ["Description"] + [c["key"] for c in visible_columns]
            df_display = pd.DataFrame(processed_rows)[display_column_keys]

            st.subheader(f"Extracted Line Items ({len(df_display)} items extracted)")
            st.dataframe(df_display, use_container_width=True)

            if unmatched_items:
                st.warning(
                    f"⚠️ {len(unmatched_items)} items were priced using default fallback "
                    "rates because they didn't confidently match the price master. "
                    "See the full list at the bottom of this page."
                )

            grand_total_pre = total_taxable + total_cgst + total_sgst
            rounded_total = round(grand_total_pre)
            round_off = rounded_total - grand_total_pre

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Taxable Value", f"₹ {total_taxable:,.2f}")
            col2.metric("Total CGST", f"₹ {total_cgst:,.2f}")
            col3.metric("Total SGST", f"₹ {total_sgst:,.2f}")
            col4.metric("Grand Total", f"₹ {rounded_total:,.2f}")

            st.markdown("---")

            # Generate downloadable PDF
            pdf_data = generate_pdf_bytes(
                processed_rows, total_taxable, total_cgst, total_sgst, rounded_total, round_off, gst_summary,
                visible_columns
            )

            if pdf_data:
                st.download_button(
                    label="📥 Download Finalized Maharashtra Tax Invoice PDF",
                    data=pdf_data,
                    file_name=f"Tax_Invoice_{inv_number.replace('/', '_')}.pdf",
                    mime="application/pdf"
                )

            if unmatched_items:
                st.markdown("---")
                st.subheader(f"⚠️ Items Needing Price Master Attention ({len(unmatched_items)})")
                st.caption(
                    "These items didn't confidently match a product in the Google Sheet "
                    "price master, so the invoice above priced them using a default "
                    "fallback rate. Add or rename these in the price master sheet, then "
                    "re-upload the report to get correct pricing."
                )
                unmatched_df = pd.DataFrame(unmatched_items).rename(
                    columns={"name": "Item", "qty": "Qty", "reason": "Why no match"}
                )
                st.dataframe(unmatched_df, use_container_width=True, hide_index=True)