# Supplier PO & Invoice Automation Platform

This repository contains the prototype and production codebase for an end-to-end AI-driven document automation system. It is designed to completely eliminate manual data entry, visually reconcile supplier purchase orders, and automatically sync validated financial data to our HubSpot CRM.

---

## 🚀 Application for SEEK 

*This README has been crafted to support my application via SEEK, addressing the mandatory cover letter requirements regarding an end-to-end AI project build.*

### AI Tool Overview (Cover Letter Requirement)
**What it does:**
This AI tool is a robust, dual-approach automated reconciliation system that completely replaces manual invoice matching. Built end-to-end, it autonomously manages the tracking, semantic data extraction, and validation of supplier purchase orders (POs) and invoices. The system operates via two dedicated pipelines:
1. **Email & Graph API Pipeline:** The system continuously listens to a dedicated Microsoft 365 mailbox via the Microsoft Graph API. Upon receiving a supplier correspondence, it intercepts the email, extracts PDF attachments, and parses the unstructured text using targeted algorithmic data extraction. It accurately isolates PO numbers, product lines, and financial totals, evaluating them directly against pending "Unconfirmed" records housed in our HubSpot CRM.
2. **Web Automation Pipeline:** Because some vendors exclusively use dashboards rather than email, the tool utilizes asynchronous headless automation (Playwright) to log into the Vertilux supplier web portal. It scrapes active order ledger tables, verifies the real-time order total against the HubSpot database, and automatically patches the CRM field to "Supplier Confirmed" if exact, or triggers an "Action Needed" alert for price disparities.

**Who uses it:**
The primary users are procurement officers, logistics managers, and the accounts payable department. Historically, these staff members were forced to open every supplier email, manually cross-reference PDFs, search for the relevant CRM entry, and manually reconcile invoices. Now, the system acts as an autonomous digital worker executing this entire workflow in the background.

**The Value it delivers:**
By deploying this automation tool, a massive operational bottleneck was eliminated. It effectively saves the operations team roughly 15-20 hours every single week in manual data entry. Furthermore, it practically eradicates human data-entry errors, immediately flags critical price deviations so financial disputes can be resolved prior to payments clearing, and accelerates the entire order reconciliation lifecycle from days down to a matter of seconds. Procurement staff can now seamlessly focus on strategic high-value tasks rather than clerical sorting.

### ☁️ Architecture Evolution: Azure to GCP Cloud Run

**Prototype Phase (Azure):** 
The system was initially prototyped, tested, and successfully conceptualized entirely on **Microsoft Azure**. The Azure environment heavily leveraged active Microsoft 365 App Registrations and serverless Azure Functions. *Because the Azure prototype handled real, highly sensitive production financial data, I no longer have local access to the live deployed Azure environment to showcase. For absolute confidentiality and security reasons, the deployed Azure endpoints cannot be externally shared.*

**Production Phase (GCP Cloud Run):**
Following the validated Azure prototype iteration, the architecture was strategically refactored. The application logic was securely containerized (via Docker) and seamlessly deployed onto **GCP Cloud Run** for the final production build. This transition from Azure serverless to GCP Cloud Run was driven by a necessity to significantly optimize production scaling and dramatically reduce hosting costs without sacrificing compute performance.

### 🎥 Live Demo / Video Walkthrough
Please find the included video demonstration showcasing the automation natively running:

**[View Video Walkthrough Demo](./Reillys%20-%20Approach%202.mp4)**

*(Note: The `Reillys - Approach 2.mp4` video file is included in the root directory alongside this repository).*

---

## 💻 Technical Repositories Produced

### 1. `approach_1/` (Headless M365 Email AI Parser)
- Headless Python worker wrapped in Flask.
- Implements secure OAuth2 Client Credentials Flow for Microsoft Graph API.
- Intelligent `pdfplumber` based text extraction and regex validation matching.
- Bi-directional HubSpot CRM data patching depending on logic pathways.

### 2. `approach_2/` (Asynchronous Supplier Portal Scraper)
- Asynchronous Playwright (Chromium) containerized pipeline.
- Specifically designed to dynamically bypass UI overlays and dialog modals.
- Extracts live financial cell values instantly from specific DOM tables.
- Cross-checks with active HubSpot database records and systematically updates matched discrepancy fields.

## 🔐 Security Practices Strictly Followed
- **No Hardcoded Credentials**: I ensured all repository code is fully optimized for security. Sensitive keys (`TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`, `HUBSPOT_TOKEN`) have been entirely decoupled from the origin logic and are securely integrated strictly via isolated environment variables (`os.getenv`).
- **Containerization**: Explicit `Dockerfile` configurations have been prepared to guarantee the code runs securely within an isolated Linux image layer.
