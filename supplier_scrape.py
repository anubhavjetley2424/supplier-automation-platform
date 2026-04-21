import os
import asyncio
from typing import List, Dict
from playwright.async_api import async_playwright

PORTAL_URL = "https://distributors.vertilux.com.au/"
USERNAME = "david@reillyandassociates.com.au"
PASSWORD = "Vc1074"


async def fetch_supplier_orders() -> List[Dict]:
    if not USERNAME or not PASSWORD:
        raise RuntimeError("Missing PORTAL_USERNAME or PORTAL_PASSWORD env vars")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        # Larger viewport to avoid navbar overlap
        page = await browser.new_page(viewport={"width": 1600, "height": 1400})

        # LOGIN
        await page.goto(PORTAL_URL)
        await page.fill("#user_login", USERNAME)
        await page.fill("#user_pass", PASSWORD)
        await page.click("#wp-submit")
        await page.wait_for_load_state("networkidle")

        # WAIT FOR MAIN TABLE
        await page.wait_for_selector("#vertilux_current_orders tbody tr")

        # Extract header names
        header_elements = await page.query_selector_all("#vertilux_current_orders thead th")
        headers = [(await h.inner_text()).strip() for h in header_elements]

        # Extract rows
        row_elements = await page.query_selector_all("#vertilux_current_orders tbody tr")
        results: List[Dict] = []

        for idx, row in enumerate(row_elements):
            cells = await row.query_selector_all("td")
            values = [(await c.inner_text()).strip() for c in cells]
            row_data = dict(zip(headers, values))

            print(f"Processing Row {idx+1}: {row_data}")

            # CLICK JOB LINK
            link = await row.query_selector("td.sorting_1 a[rel='vertilux-order']")
            if not link:
                print("→ No job link, skipping.")
                row_data["Order_Amount"] = None
                results.append(row_data)
                continue

            await link.click()
            await page.wait_for_timeout(600)  # popup animation time

            # STEP A: Find visible dialog
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
                print("❌ No visible dialog found after click.")
                row_data["Order_Amount"] = None
                results.append(row_data)
                continue

            # STEP B: Detect iframe for details
            frame = None
            for f in page.frames:
                if "vertilux_order_details" in f.url or "admin-ajax" in f.url:
                    frame = f
                    break

            # STEP C: Find totals-table
            if frame:
                totals_table = frame.locator("table.totals-table")
            else:
                totals_table = visible_dialog.locator("table.totals-table")

            try:
                await totals_table.wait_for(timeout=10000)
            except:
                print("❌ totals-table not found in popup.")
                row_data["Order_Amount"] = None
                results.append(row_data)
                continue

            # Extract TOTAL cell (last row, last column)
            total_cell = totals_table.locator("tbody tr:last-child td:last-child")

            if await total_cell.count() > 0:
                total_value = (await total_cell.inner_text()).strip()
                print(f"✔ Extracted Order Amount: {total_value}")
                row_data["Order_Amount"] = total_value
            else:
                print("⚠ totals-table found but TOTAL cell missing.")
                row_data["Order_Amount"] = None

            # STEP D: Scroll content before closing
            if frame:
                await frame.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            else:
                await visible_dialog.evaluate("node => node.scrollTo(0, node.scrollHeight)")

            await page.wait_for_timeout(300)

            # STEP E: Close popup (force click to bypass navbar overlap)
            close_btn = visible_dialog.locator(".ui-dialog-titlebar-close")
            if await close_btn.count() > 0:
                try:
                    await close_btn.click(force=True)
                except:
                    print("⚠ Force-click failed, trying keyboard ESC")
                    await page.keyboard.press("Escape")
            else:
                print("⚠ Close button not found, trying ESC")
                await page.keyboard.press("Escape")

            await page.wait_for_timeout(300)

            results.append(row_data)

        await browser.close()
        return results


async def main():
    data = await fetch_supplier_orders()
    print(f"\n=== DONE: {len(data)} ROWS SCRAPED ===")
    for r in data[:5]:
        print(r)


if __name__ == "__main__":
    asyncio.run(main())
