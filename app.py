import streamlit as st
import pandas as pd
import pdfplumber
import re
import difflib
import io
import pypdf

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

# Default Published Google Sheet CSV URL (Update if needed)
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSmXqY9tG7gW8qE8v6/pub?output=csv"

sheet_url = st.sidebar.text_input(
    "Google Sheet Price Master CSV URL", 
    value="https://docs.google.com/spreadsheets/d/12a9031ezxQ2GTVyULyw-ddpEfVUYm0rkC4dthS-i68Q/export?format=csv",
    help="Published CSV URL of your Google Sheet Price List"
)

inv_number = st.sidebar.text_input("Invoice Number", "INV/2026-27/0842")
inv_date = st.sidebar.date_input("Invoice Date")

st.sidebar.subheader("Supplier (Company A)")
supplier_name = st.sidebar.text_input("Supplier Name", "COMPANY A PRIVATE LIMITED")
supplier_gstin = st.sidebar.text_input("Supplier GSTIN", "27AAAAA1111A1Z1")

st.sidebar.subheader("Billed To (Company B)")
buyer_name = st.sidebar.text_input("Buyer Name", "COMPANY B LOGISTICS & RETAIL LTD")
buyer_gstin = st.sidebar.text_input("Buyer GSTIN", "27BBBBB2222B1Z2")

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
# 4. MULTI-COLUMN PDF PARSING ENGINE
# -----------------------------------------------------------------------------

def parse_pdf_items(uploaded_file):
    """
    Extracts ALL Item Names and Quantities across multi-column rows.
    Handles lines containing multiple items like: "Item A 10  Item B 20  Item C 5"
    """
    uploaded_file.seek(0)
    text = ""
    
    # 1. Extract text using pypdf (or pdfplumber fallback)
    try:
        reader = pypdf.PdfReader(uploaded_file)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception:
        uploaded_file.seek(0)
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

    # 2. Pre-clean layout artifacts
    text = text.replace("order = 40", "order 40")
    text = text.replace("retail = 2", "retail 2")
    text = text.replace("(0.5 Kg Each)", "")
    text = re.sub(r"Combo Chilly\s*\(.*?\)\s*(\d+)", r"Combo Chilly \1", text)
    
    extracted = []
    lines = text.split("\n")
    
    for line in lines:
        line_str = line.strip().strip("|")
        if not line_str:
            continue
            
        # Regex matches ALL [Item Name] followed by [Quantity Digits] on the line
        raw_matches = re.findall(r"([^\d]+?)\s*[:=]?\s*(\d+)", line_str)
        
        for name, qty in raw_matches:
            name_clean = name.strip().strip("|")
            
            # Clean leading/trailing punctuation & special chars
            name_clean = re.sub(r"^[^\w\u0900-\u097F]+", "", name_clean)
            name_clean = re.sub(r"[^\w\u0900-\u097F)]+$", "", name_clean).strip()
            
            # Skip noise tokens
            if name_clean.lower() in ['order', 'retail', 'gm+less', 'gm', 'piece punnet', 'kg each', 'rs', 'total']:
                continue
                
            qty_int = int(qty)
            if len(name_clean) > 1 and qty_int > 0:
                extracted.append({"raw_name": name_clean, "qty": qty_int})
                
    return extracted
# -----------------------------------------------------------------------------
# 5. BILINGUAL SMART ITEM MATCHER
# -----------------------------------------------------------------------------
def find_best_match(query, master_list):
    """Bilingual (Marathi/English) matching logic for truncated PDF text."""
    if not query:
        return None
        
    q_clean = query.strip().lower().replace(" ", "").replace("/", "").replace("-", "")
    
    # 1. Exact or containment match
    for item in master_list:
        i_clean = str(item).strip().lower().replace(" ", "").replace("/", "").replace("-", "")
        if q_clean in i_clean or i_clean in q_clean:
            return item
            
    # 2. Sub-part match (e.g. Marathi part before '/' or English part after '/')
    parts = [p.strip() for p in query.split("/") if p.strip()]
    for p in parts:
        p_sub = p.lower()
        if len(p_sub) > 2:
            for item in master_list:
                if p_sub in str(item).lower():
                    return item
                    
    # 3. Fuzzy match fallback
    matches = difflib.get_close_matches(query, [str(m) for m in master_list], n=1, cutoff=0.3)
    if matches:
        return matches[0]
        
    return None

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
def generate_pdf_bytes(df_rows, total_taxable, total_cgst, total_sgst, rounded_total, round_off, gst_summary):
    
    rows_html = ""
    for idx, row in enumerate(df_rows, start=1):
        rows_html += f"""
        <tr>
            <td style="text-align: center;">{idx}</td>
            <td>{row['Description']}</td>
            <td style="text-align: center;">{row['HSN']}</td>
            <td style="text-align: center;">{row['UOM']}</td>
            <td style="text-align: right;">{row['Qty']}</td>
            <td style="text-align: right;">{row['Rate']:,.2f}</td>
            <td style="text-align: right;">{row['Taxable Value']:,.2f}</td>
            <td style="text-align: center;">{row['CGST Rate']}</td>
            <td style="text-align: right;">{row['CGST Amt']:,.2f}</td>
            <td style="text-align: center;">{row['SGST Rate']}</td>
            <td style="text-align: right;">{row['SGST Amt']:,.2f}</td>
            <td style="text-align: right;">{row['Total']:,.2f}</td>
        </tr>
        """

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
                    <div>District Pune, Maharashtra - 412303</div>
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
                    <div>Mumbai, Maharashtra - 400093</div>
                    <div><strong>GSTIN:</strong> {buyer_gstin} | <strong>State:</strong> Maharashtra (27)</div>
                </td>
                <td style="vertical-align: top;">
                    <div class="bold" style="font-size: 9pt; color: #1a365d;">SHIPPED TO</div>
                    <div class="bold">{buyer_name} Fulfillment Center</div>
                    <div>Wagholi Logistics Park, Pune, Maharashtra - 412207</div>
                </td>
            </tr>
        </table>

        <table>
            <colgroup>
                <col style="width: 4%;">
                <col style="width: 28%;">
                <col style="width: 7%;">
                <col style="width: 6%;">
                <col style="width: 5%;">
                <col style="width: 8%;">
                <col style="width: 9%;">
                <col style="width: 5%;">
                <col style="width: 7%;">
                <col style="width: 5%;">
                <col style="width: 7%;">
                <col style="width: 9%;">
            </colgroup>
            <thead>
                <tr>
                    <th style="width: 4%;">S.No</th>
                    <th style="width: 28%;">Description of Farm Produce</th>
                    <th style="width: 7%;">HSN</th>
                    <th style="width: 6%;">UOM</th>
                    <th style="width: 5%;">Qty</th>
                    <th style="width: 8%;">Rate (₹)</th>
                    <th style="width: 9%;">Taxable Value</th>
                    <th style="width: 5%;">CGST %</th>
                    <th style="width: 7%;">CGST Amt</th>
                    <th style="width: 5%;">SGST %</th>
                    <th style="width: 7%;">SGST Amt</th>
                    <th style="width: 9%;">Total (₹)</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
                <tr style="font-weight: bold; background-color: #edf2f7;">
                    <td colspan="4" style="text-align: right;">Total Gross Values</td>
                    <td style="text-align: right;">{sum(r['Qty'] for r in df_rows)}</td>
                    <td></td>
                    <td style="text-align: right;">{total_taxable:,.2f}</td>
                    <td></td>
                    <td style="text-align: right;">{total_cgst:,.2f}</td>
                    <td></td>
                    <td style="text-align: right;">{total_sgst:,.2f}</td>
                    <td style="text-align: right;">{(total_taxable + total_cgst + total_sgst):,.2f}</td>
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
st.markdown('<div class="sub-header">Upload an incoming PDF item list to parse products and generate a Maharashtra GST Tax Invoice instantly.</div>', unsafe_allow_html=True)

price_master_df = load_price_master(sheet_url)

if price_master_df is not None:
    uploaded_pdf = st.file_uploader("Drop PDF Item List Report here", type=["pdf"])

    if uploaded_pdf is not None:
        st.info("Parsing multi-column PDF and matching items against Price Master...")
        
        extracted_items = parse_pdf_items(uploaded_pdf)
        
        if not extracted_items:
            st.error("No items could be extracted from the PDF. Please check the PDF format.")
        else:
            # Column mapping check for Price Master
            pname_col = "PRODUCT NAME" if "PRODUCT NAME" in price_master_df.columns else price_master_df.columns[1]
            hsn_col = "HSN CODE" if "HSN CODE" in price_master_df.columns else "HSN"
            uom_col = "UOM" if "UOM" in price_master_df.columns else price_master_df.columns[4]
            price_col = "UNIT PRICE (INR)" if "UNIT PRICE (INR)" in price_master_df.columns else "UNIT PRICE"
            gst_col = "GST RATE (%)" if "GST RATE (%)" in price_master_df.columns else "GST RATE"

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
                
                best_match = find_best_match(raw_name, master_product_list)
                
                if best_match:
                    row_data = price_master_df[price_master_df[pname_col] == best_match].iloc[0]
                    
                    # Clean price and tax rates
                    rate = float(str(row_data[price_col]).replace("₹", "").replace(",", "").strip())
                    gst_p = float(str(row_data[gst_col]).replace("%", "").strip())
                    hsn_val = str(row_data[hsn_col]).split(".")[0]
                    uom_val = str(row_data[uom_col])
                    desc_val = str(row_data[pname_col])
                else:
                    unmatched_items.append(raw_name)
                    rate = 40.0
                    gst_p = 0.0
                    hsn_val = "0709"
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
                    "HSN": hsn_val,
                    "UOM": uom_val,
                    "Qty": qty,
                    "Rate": rate,
                    "Taxable Value": taxable,
                    "CGST Rate": f"{cgst_p:.1f}%",
                    "CGST Amt": cgst_amt,
                    "SGST Rate": f"{sgst_p:.1f}%",
                    "SGST Amt": sgst_amt,
                    "Total": item_total
                })

            df_display = pd.DataFrame(processed_rows)

            st.subheader(f"Extracted Line Items ({len(df_display)} items extracted)")
            st.dataframe(df_display, use_container_width=True)

            if unmatched_items:
                st.warning(f"⚠️ {len(unmatched_items)} items were matched using default fallback rates: {', '.join(unmatched_items[:10])}...")

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
                processed_rows, total_taxable, total_cgst, total_sgst, rounded_total, round_off, gst_summary
            )

            if pdf_data:
                st.download_button(
                    label="📥 Download Finalized Maharashtra Tax Invoice PDF",
                    data=pdf_data,
                    file_name=f"Tax_Invoice_{inv_number.replace('/', '_')}.pdf",
                    mime="application/pdf"
                )