# main.py (Cloud Run, fully automated, no manual OAuth)

import os
import io
import base64
import re
import requests
import pdfplumber
from datetime import datetime, timezone
from flask import Flask, jsonify

app = Flask(__name__)

# -----------------------------------------
# ENV VARS (Cloud Run) – set these in GCP
# -----------------------------------------
TENANT_ID        = os.getenv("TENANT_ID")
CLIENT_ID        = os.getenv("CLIENT_ID")
CLIENT_SECRET    = os.getenv("CLIENT_SECRET")
SUPPLIER_MAILBOX = os.getenv("SUPPLIER_MAILBOX")
HUBSPOT_TOKEN    = os.getenv("HUBSPOT_TOKEN")
HUBSPOT_OBJECT   = os.getenv("HUBSPOT_OBJECT", "p442646332_purchase_order")

if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, SUPPLIER_MAILBOX, HUBSPOT_TOKEN]):
    raise RuntimeError("❌ Missing required environment variables (TENANT_ID, CLIENT_ID, CLIENT_SECRET, SUPPLIER_MAILBOX, HUBSPOT_TOKEN).")


# Only these are considered “unconfirmed”
UNCONFIRMED_STATUSES = {"Order Issued", "Action Needed"}

GRAPH_TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
GRAPH_BASE      = "https://graph.microsoft.com/v1.0"
HUBSPOT_BASE    = "https://api.hubapi.com"


# -----------------------------------------
# GRAPH AUTH (Client Credentials Flow)
# -----------------------------------------
def get_graph_access_token():
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }
    r = requests.post(GRAPH_TOKEN_URL, data=data)
    r.raise_for_status()
    return r.json()["access_token"]


def graph_get(url, params=None):
    token = get_graph_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()


# -----------------------------------------
# GRAPH EMAIL HELPERS
# -----------------------------------------
def find_supplier_emails_with_attachments(supplier_email, max_messages=50):
    """
    Search dedicated mailbox for messages FROM supplier_email with attachments.
    Using /users/{mailbox}/messages for application permissions.
    """
    url = f"{GRAPH_BASE}/users/{SUPPLIER_MAILBOX}/messages"

    params = {
        "$top": max_messages,
        "$filter": f"from/emailAddress/address eq '{supplier_email}' and hasAttachments eq true",
        "$orderby": "receivedDateTime desc",
    }

    data = graph_get(url, params)
    return data.get("value", [])


def get_message_attachments(message_id):
    url = f"{GRAPH_BASE}/users/{SUPPLIER_MAILBOX}/messages/{message_id}/attachments"
    data = graph_get(url)
    return data.get("value", [])


# -----------------------------------------
# HUBSPOT HELPERS
# -----------------------------------------
def get_unconfirmed_purchase_orders(limit=100):
    """
    Pull all POs with status in UNCONFIRMED_STATUSES.
    """
    url = f"{HUBSPOT_BASE}/crm/v3/objects/{HUBSPOT_OBJECT}"
    headers = {"Authorization": f"Bearer {HUBSPOT_TOKEN}"}
    params = {
        "limit": limit,
        "properties": (
            "po_number,product_type,order_type,shipping_method,description,"
            "supplier_email,order_date,required_date,status"
        ),
    }

    results = []
    while True:
        r = requests.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()

        for rec in data.get("results", []):
            props = rec.get("properties", {}) or {}
            status = (props.get("status") or "").strip()
            if status in UNCONFIRMED_STATUSES:
                results.append(rec)

        next_link = data.get("paging", {}).get("next", {}).get("link")
        if not next_link:
            break
        url = next_link
        params = None  # next link already includes query params

    return results


def update_purchase_order(po_id, status_value):
    url = f"{HUBSPOT_BASE}/crm/v3/objects/{HUBSPOT_OBJECT}/{po_id}"
    headers = {
        "Authorization": f"Bearer {HUBSPOT_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"properties": {"status": status_value}}
    r = requests.patch(url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json()


# -----------------------------------------
# PDF PARSER + MATCHING
# -----------------------------------------
def parse_materialised_pdf(pdf_bytes):
    text = ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text += t + "\n"

    # Adjust patterns to match your real supplier PDFs
    m_conf  = re.search(r"Order Confirmation\s+([A-Z0-9]+)", text)
    m_ref   = re.search(r"Order Reference\s+(\S+)", text)
    m_ship  = re.search(r"Shipment Date\s+([0-9/]+)", text)
    m_total = re.search(r"Total AUD Incl\. GST\s+\$?([\d.,]+)", text)

    return {
        "confirmation_number": m_conf.group(1).strip() if m_conf else None,
        "order_reference": m_ref.group(1).strip() if m_ref else None,
        "shipment_date": m_ship.group(1).strip() if m_ship else None,
        "total_incl_gst": m_total.group(1).strip() if m_total else None,
        "raw_text": text,
    }


def pdf_matches_purchase_order(parsed, po_props):
    """
    Simple matching logic:
    - PO number should match confirmation number (if present)
    - product_type should appear somewhere in the PDF text
    """
    po_number    = (po_props.get("po_number") or "").strip()
    product_type = (po_props.get("product_type") or "").strip()

    if not po_number:
        return False

    conf = parsed.get("confirmation_number")
    txt  = (parsed.get("raw_text") or "").lower()

    if conf and conf != po_number:
        return False

    if product_type and product_type.lower() not in txt:
        return False

    return True


# -----------------------------------------
# MAIN PROCESS
# -----------------------------------------
def process_unconfirmed_orders():
    summary = {"checked": 0, "confirmed": 0, "action": 0, "no_email": 0, "errors": []}

    orders = get_unconfirmed_purchase_orders()
    summary["checked"] = len(orders)

    today_utc = datetime.now(timezone.utc).date()

    for rec in orders:
        po_id = rec["id"]
        props = rec.get("properties", {}) or {}

        po_number = (props.get("po_number") or "").strip()
        supplier  = (props.get("supplier_email") or "").strip()
        status    = (props.get("status") or "").strip()

        # Parse order_date (assuming ISO format "YYYY-MM-DD" – adjust if different)
        order_date_str = props.get("order_date")
        order_date = None
        if order_date_str:
            try:
                order_date = datetime.fromisoformat(order_date_str).date()
            except Exception:
                order_date = None  # If format is not ISO, handle/transform as needed

        if not po_number or not supplier:
            continue

        try:
            # 1) Fetch recent messages from supplier
            msgs = find_supplier_emails_with_attachments(supplier)

            # 2) Filter to messages that mention PO number in subject
            filtered_msgs = []
            for msg in msgs:
                subj = (msg.get("subject") or "")
                if po_number in subj:
                    filtered_msgs.append(msg)

            outcome = None  # "Order Confirmed" or "Action Needed"

            # 3) Inspect filtered messages + attachments
            for msg in filtered_msgs:
                msg_id = msg["id"]
                atts = get_message_attachments(msg_id)

                for att in atts:
                    if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
                        continue

                    name = (att.get("name") or "").lower()
                    if not name.endswith(".pdf"):
                        continue

                    pdf_bytes = base64.b64decode(att["contentBytes"])
                    parsed = parse_materialised_pdf(pdf_bytes)

                    if pdf_matches_purchase_order(parsed, props):
                        # Perfect: email + PDF match the HubSpot row
                        outcome = "Order Confirmed"
                    else:
                        # Email exists but PDF doesn't match our PO – raise a flag
                        outcome = "Action Needed"
                    break  # Stop after first PDF

                if outcome:
                    break  # Stop after first matching message

            # 4) If we still have no outcome, apply the 2-day grace rule:
            #    - If there is no suitable email and it's been >= 2 days since order date:
            #        -> mark as "Action Needed"
            #    - Otherwise, leave as is and check again next scheduler run
            if not outcome:
                if order_date is not None:
                    days_since_order = (today_utc - order_date).days
                    if days_since_order >=3:
                        outcome = "Action Needed"

            # 5) Apply status update in HubSpot
            if outcome:
                update_purchase_order(po_id, outcome)
                if outcome == "Order Confirmed":
                    summary["confirmed"] += 1
                else:
                    summary["action"] += 1
            else:
                # No confirmation yet, still within grace window
                summary["no_email"] += 1

        except Exception as e:
            summary["errors"].append({"po_id": po_id, "error": str(e)})

    return summary


# -----------------------------------------
# FLASK ROUTE
# -----------------------------------------
@app.route("/run", methods=["GET"])
def run_automation():
    try:
        result = process_unconfirmed_orders()
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
