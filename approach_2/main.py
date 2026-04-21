import os
import asyncio
from typing import List, Dict, Tuple
from datetime import datetime, timezone
import re
import requests
from playwright.async_api import async_playwright, Page

# =========================
# CONFIG (ENV VARIABLES)
# =========================
PORTAL_URL = "https://distributors.vertilux.com.au/"
PORTAL_USERNAME = os.getenv("PORTAL_USERNAME")
PORTAL_PASSWORD = os.getenv("PORTAL_PASSWORD")
HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")

if not PORTAL_USERNAME or not PORTAL_PASSWORD or not HUBSPOT_TOKEN:
    raise RuntimeError("❌ Missing required environment variables.")

HS_OBJECT = "p442646332_purchase_order"
HS_BASE_URL = f"https://api.hubapi.com/crm/v3/objects/{HS_OBJECT}"
HS_HEADERS = {"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"}

HS_PROP_PO_NUMBER, HS_PROP_DESCRIPTION = "po_number", "description"
HS_PROP_ORDER_VALUE, HS_PROP_STATUS = "order_value", "status"
HS_PROP_ORDER_DATE, HS_PROP_VALUE_MATCH = "order_date", "order_value_match"

STATUS_ORDER_ISSUED, STATUS_SUPPLIER_CONFIRMED = "Order Issued", "Supplier Confirmed"
STATUS_ACTION_NEEDED, ACTION_NEEDED_AGE_DAYS = "Action Needed", 3

# =========================
# HELPER FUNCTIONS
# =========================

def clean_currency(value) -> str:
    if value is None: return "0.00"
    s = str(value).strip()
    if s == "" or s.lower() == "nan": return "0.00"
    cleaned = re.sub(r"[^\d.]", "", s)
    try: return f"{float(cleaned):.2f}"
    except: return "0.00"

async def close_portal_dialog(page: Page):
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
        await page.evaluate('''() => {
            document.querySelectorAll(".ui-dialog").forEach(el => el.remove());
            document.querySelectorAll(".ui-widget-overlay").forEach(el => el.remove());
            document.body.classList.remove("ui-helper-hidden-accessible");
        }''')
        await page.wait_for_timeout(200)
    except: pass

async def login_and_wait_for_orders(page: Page):
    for attempt in range(1, 4):
        try:
            print(f"🌐 [Attempt {attempt}] Navigating to portal...", flush=True)
            await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)
            await page.fill("#user_login", PORTAL_USERNAME)
            await page.fill("#user_pass", PORTAL_PASSWORD)
            await page.click("#wp-submit")
            await page.wait_for_timeout(4000)
            await page.wait_for_selector("#vertilux_current_orders", timeout=30000)
            print("✅ Login successful.", flush=True)
            return
        except Exception as e:
            if attempt == 3: raise e
            await page.wait_for_timeout(2000)

# =========================
# SCRAPER & SYNC
# =========================

async def fetch_supplier_orders() -> List[Dict]:
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1600, "height": 1400})
        try:
            await login_and_wait_for_orders(page)
            header_els = await page.query_selector_all("#vertilux_current_orders thead th")
            headers = [ (await h.inner_text()).strip() for h in header_els ]
            rows = await page.query_selector_all("#vertilux_current_orders tbody tr")
            
            for idx, row in enumerate(rows, start=1):
                row_text = await row.inner_text()
                if "No data available" in row_text: break
                
                await close_portal_dialog(page)
                cells = await row.query_selector_all("td")
                values = [ (await c.inner_text()).strip() for c in cells ]
                row_data = dict(zip(headers, values))
                
                order_no = row_data.get("Order No", "").strip()
                link = await row.query_selector("td.sorting_1 a[rel='vertilux-order']")

                if link:
                    print(f"📄 Row {idx}: Scraping PO {order_no}...", flush=True)
                    await link.click(force=True)
                    await page.locator("div.ui-dialog:visible").first.wait_for(timeout=10000)
                    
                    frame = None
                    for f in page.frames:
                        if "vertilux_order_details" in (f.url or ""): 
                            frame = f
                            break
                    
                    try:
                        target = frame.locator("table.totals-table") if frame else page.locator("table.totals-table")
                        await target.wait_for(timeout=5000)
                        raw_amt = await target.locator("tbody tr:last-child td:last-child").inner_text()
                        row_data["Order_Amount"] = clean_currency(raw_amt)
                        print(f"   💰 Value: {row_data['Order_Amount']}", flush=True)
                    except:
                        row_data["Order_Amount"] = "0.00"
                    
                    await close_portal_dialog(page)
                results.append(row_data)
        finally:
            await browser.close()
    return results

def sync_hubspot(portal_rows):
    # Key = (Order No, Job Name)
    portal_index = { (str(r.get("Order No")).strip(), str(r.get("Job Name")).strip()): clean_currency(r.get("Order_Amount")) for r in portal_rows }
    
    params = {"limit": 100, "properties": f"{HS_PROP_PO_NUMBER},{HS_PROP_DESCRIPTION},{HS_PROP_ORDER_VALUE},{HS_PROP_STATUS},{HS_PROP_ORDER_DATE},{HS_PROP_VALUE_MATCH}"}
    resp = requests.get(HS_BASE_URL, headers=HS_HEADERS, params=params)
    hs_records = resp.json().get("results", [])
    now = datetime.now(tz=timezone.utc)

    for rec in hs_records:
        p = rec.get("properties") or {}
        # We only process if current status is "Order Issued" OR "Action Needed" (to re-verify)
        current_status = p.get(HS_PROP_STATUS)
        if current_status not in [STATUS_ORDER_ISSUED, STATUS_ACTION_NEEDED]:
            continue

        po, desc = str(p.get(HS_PROP_PO_NUMBER) or "").strip(), str(p.get(HS_PROP_DESCRIPTION) or "").strip()
        hs_val = clean_currency(p.get(HS_PROP_ORDER_VALUE))
        portal_val = portal_index.get((po, desc))

        new_status = current_status
        match_flag = "no"

        # LOGIC CHANGE:
        if portal_val is not None:
            # 1. Exact Match
            if hs_val == portal_val:
                new_status = STATUS_SUPPLIER_CONFIRMED
                match_flag = "yes"
                print(f"✅ PO {po}: Match found. Confirming.", flush=True)
            # 2. Key exists, but price mismatch
            else:
                new_status = STATUS_ACTION_NEEDED
                match_flag = "no"
                print(f"⚠️ PO {po}: Price mismatch (HS: {hs_val} vs Portal: {portal_val}). Flagging Action Needed.", flush=True)
        else:
            # 3. Not found in portal yet
            match_flag = "no"
            dt_str = p.get(HS_PROP_ORDER_DATE)
            if dt_str:
                dt = datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if (now - dt).days > ACTION_NEEDED_AGE_DAYS:
                    new_status = STATUS_ACTION_NEEDED
                    print(f"⏳ PO {po}: Not in portal and > {ACTION_NEEDED_AGE_DAYS} days old. Flagging Action Needed.", flush=True)

        if new_status != current_status or match_flag != p.get(HS_PROP_VALUE_MATCH):
            requests.patch(f"{HS_BASE_URL}/{rec.get('id')}", headers=HS_HEADERS, json={"properties": {HS_PROP_STATUS: new_status, HS_PROP_VALUE_MATCH: match_flag}})

async def main():
    print("🚀 SYNC START", flush=True)
    rows = await fetch_supplier_orders()
    sync_hubspot(rows)
    print("✅ SYNC COMPLETE", flush=True)

if __name__ == "__main__":
    asyncio.run(main())