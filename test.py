import os
import asyncio
from typing import List, Dict, Tuple
from datetime import datetime, timezone
import re
import requests
from playwright.async_api import async_playwright

# =========================
# CONFIG
# =========================

# Supplier portal
PORTAL_URL = "https://distributors.vertilux.com.au/"
PORTAL_USERNAME = "david@reillyandassociates.com.au"
PORTAL_PASSWORD = "Vc1074"

# HubSpot
HUBSPOT_TOKEN = "your_hubspot_token_here"
HS_OBJECT = "p442646332_purchase_order"
HS_BASE_URL = f"https://api.hubapi.com/crm/v3/objects/{HS_OBJECT}"
HS_HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json",
}

# HubSpot property mappings
HS_PROP_PO_NUMBER = "po_number"
HS_PROP_DESCRIPTION = "description"   # maps to Job Name
HS_PROP_ORDER_VALUE = "order_value"
HS_PROP_STATUS = "status"
HS_PROP_ORDER_DATE = "order_date"
HS_PROP_VALUE_MATCH = "order_value_match"

# Status logic
STATUS_ORDER_ISSUED = "Order Issued"
STATUS_SUPPLIER_CONFIRMED = "Supplier Confirmed"
STATUS_ACTION_NEEDED = "Action Needed"

# Orders older than this get action-needed if mismatch
ACTION_NEEDED_AGE_DAYS = 3


# =========================
# HELPERS
# =========================

def clean_currency(value: str) -> str:
    if not value:
        return "0.00"
    cleaned = re.sub(r"[^\d.]", "", str(value))
    try:
        return f"{float(cleaned):.2f}"
    except Exception:
        return "0.00"


def parse_hubspot_date(value: str):
    if not value:
        return None
    try:
        # HubSpot date field stored as YYYY-MM-DD
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


# =========================
# SUPPLIER SCRAPER
# =========================

async def fetch_supplier_orders() -> List[Dict]:
    """Returns list of portal rows with Job Name and Order_Amount."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1400})

        # LOGIN
        await page.goto(PORTAL_URL)
        await page.fill("#user_login", PORTAL_USERNAME)
        await page.fill("#user_pass", PORTAL_PASSWORD)
        await page.click("#wp-submit")
        await page.wait_for_load_state("networkidle")

        # WAIT FOR TABLE
        await page.wait_for_selector("#vertilux_current_orders tbody tr")

        # Extract headers
        header_elements = await page.query_selector_all("#vertilux_current_orders thead th")
        headers = [(await h.inner_text()).strip() for h in header_elements]

        # Extract rows
        row_elements = await page.query_selector_all("#vertilux_current_orders tbody tr")
        results: List[Dict] = []

        for idx, row in enumerate(row_elements):
            cells = await row.query_selector_all("td")
            values = [(await c.inner_text()).strip() for c in cells]
            row_data = dict(zip(headers, values))

            order_no = row_data.get("Order No", "").strip()
            job_name = row_data.get("Job Name", "").strip()

            print(f"[Portal] Row {idx+1}: {order_no} | {job_name}")

            # Click details
            link = await row.query_selector("td.sorting_1 a[rel='vertilux-order']")
            if not link:
                row_data["Order_Amount"] = None
                results.append(row_data)
                continue

            await link.click()
            await page.wait_for_timeout(600)

            # Detect visible dialog
            dialogs = page.locator("div.ui-dialog")
            visible_dialog = None
            dlg_count = await dialogs.count()

            for i in range(dlg_count):
                dlg = dialogs.nth(i)
                box = await dlg.bounding_box()
                if box:
                    visible_dialog = dlg
                    break

            if not visible_dialog:
                print(" ❌ No dialog found")
                row_data["Order_Amount"] = None
                results.append(row_data)
                continue

            # Detect iframe
            frame = None
            for f in page.frames:
                if "vertilux_order_details" in f.url or "admin-ajax" in f.url:
                    frame = f
                    break

            # Locate totals table
            if frame:
                totals = frame.locator("table.totals-table")
            else:
                totals = visible_dialog.locator("table.totals-table")

            try:
                await totals.wait_for(timeout=10000)
                total_cell = totals.locator("tbody tr:last-child td:last-child")
                amount_raw = (await total_cell.inner_text()).strip()
                print(f"   ✔ Amount: {amount_raw}")
                row_data["Order_Amount"] = amount_raw
            except:
                print("   ❌ No Order Amount found")
                row_data["Order_Amount"] = None

            # Close popup
            close_btn = visible_dialog.locator(".ui-dialog-titlebar-close")
            if await close_btn.count() > 0:
                try:
                    await close_btn.click(force=True)
                except:
                    await page.keyboard.press("Escape")
            else:
                await page.keyboard.press("Escape")

            await page.wait_for_timeout(300)
            results.append(row_data)

        await browser.close()
        print(f"\n=== PORTAL SCRAPE COMPLETE: {len(results)} ROWS ===")
        return results


def build_portal_index(rows: List[Dict]) -> Dict[Tuple[str, str], str]:
    """Build lookup by (Order No, Job Name) -> cleaned amount."""
    index = {}
    for r in rows:
        order_no = (r.get("Order No") or "").strip()
        job_name = (r.get("Job Name") or "").strip()
        amount_clean = clean_currency(r.get("Order_Amount") or "")
        if order_no and job_name:
            index[(order_no, job_name)] = amount_clean
    return index


# =========================
# HUBSPOT SYNC
# =========================

def fetch_hubspot_orders() -> List[Dict]:
    props = ",".join([
        HS_PROP_PO_NUMBER,
        HS_PROP_DESCRIPTION,
        HS_PROP_ORDER_VALUE,
        HS_PROP_STATUS,
        HS_PROP_ORDER_DATE,
        HS_PROP_VALUE_MATCH,
    ])
    results = []
    after = None

    while True:
        params = {"limit": 100, "properties": props}
        if after:
            params["after"] = after

        resp = requests.get(HS_BASE_URL, headers=HS_HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))

        paging = data.get("paging", {})
        next_link = paging.get("next", {})
        after = next_link.get("after")
        if not after:
            break

    return results


def sync_hubspot_with_portal(portal_index):
    hs_records = fetch_hubspot_orders()
    now = datetime.now(tz=timezone.utc)
    updates = []

    for rec in hs_records:
        rec_id = rec.get("id")
        props = rec.get("properties", {})

        status = props.get(HS_PROP_STATUS, "")
        if status != STATUS_ORDER_ISSUED:
            continue

        po = (props.get(HS_PROP_PO_NUMBER) or "").strip()
        desc = (props.get(HS_PROP_DESCRIPTION) or "").strip()
        hs_val = clean_currency(str(props.get(HS_PROP_ORDER_VALUE) or "0"))

        order_date = parse_hubspot_date(props.get(HS_PROP_ORDER_DATE))
        age_days = (now - order_date).days if order_date else None

        portal_val = portal_index.get((po, desc))

        print(f"\n[HS] PO={po} | Desc={desc} | HS={hs_val} | Portal={portal_val} | Age={age_days}")

        new_status = status
        match_flag = props.get(HS_PROP_VALUE_MATCH, None)

        if portal_val:
            if hs_val == portal_val:
                new_status = STATUS_SUPPLIER_CONFIRMED
                match_flag = "yes"
                print("  ✔ MATCH → Supplier Confirmed")
            else:
                match_flag = "no"
                print("  ❌ VALUE MISMATCH")
                if age_days and age_days > ACTION_NEEDED_AGE_DAYS:
                    new_status = STATUS_ACTION_NEEDED
                    print(f"  ⚠ >{ACTION_NEEDED_AGE_DAYS} days → Action Needed")
                else:
                    print("  ⏳ Not old enough for Action Needed")
        else:
            print("  ⚠ No portal record found")
            match_flag = "no"
            if age_days and age_days > ACTION_NEEDED_AGE_DAYS:
                new_status = STATUS_ACTION_NEEDED
                print(f"  ⚠ >{ACTION_NEEDED_AGE_DAYS} days → Action Needed")

        # Patch only if changed
        if new_status != status or match_flag != props.get(HS_PROP_VALUE_MATCH):
            patch = {
                "properties": {
                    HS_PROP_STATUS: new_status,
                    HS_PROP_VALUE_MATCH: match_flag
                }
            }
            print(f"  🔄 PATCH: {rec_id} status={new_status}, match={match_flag}")
            requests.patch(f"{HS_BASE_URL}/{rec_id}", headers=HS_HEADERS, json=patch)
            updates.append(rec_id)

    print(f"\n=== HUBSPOT SYNC DONE: {len(updates)} UPDATED ===")
    return updates


# =========================
# MAIN
# =========================

async def main():
    print("=== SUPPLIER → HUBSPOT SYNC START ===")
    portal_rows = await fetch_supplier_orders()
    portal_index = build_portal_index(portal_rows)
    updated = sync_hubspot_with_portal(portal_index)
    print("\nUpdated Records:", updated)


if __name__ == "__main__":
    asyncio.run(main())
