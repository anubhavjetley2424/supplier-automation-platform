# Supplier PO & Invoice Automation Platform

This repository contains the prototype and production codebase for an end-to-end AI-driven document and portal automation system built for **Reillys**.

---

## 🚀 Application for SEEK (Cover Letter)

### 🤖 AI Tool Overview

**What it does:**
This AI tool is a dual-pipeline automated reconciliation system that entirely replaces manual invoice matching. It autonomously monitors, extracts, and validates supplier purchase orders (POs) and invoices to ensure they perfectly match the CRM records.

**Who uses it and Why:**
It is specifically built for the **Reillys Admin team**. Previously, the administration team had to manually open every email or regularly check supplier portals to confirm if supplier orders and pricing exactly matched the PO records existing in the HubSpot Database.

**The Value it delivers:**
By running this automation, the system eliminates 15-20 hours a week of grueling data entry for the Reillys Admin team. It automatically cross-references order values and catches critical price deviations (supplier quoted prices vs. internal PO budgets) instantaneously, turning a process that took days into seconds and practically eradicating human-entry errors prior to financial payments clearing.

---

## 🏗️ Architecture Breakdown

Because suppliers provide invoices differently, the system utilizes two distinct parallel approaches.

### Workflow Diagram

```mermaid
graph TD
    %% Base CRM
    HS[(HubSpot Database<br/>Unconfirmed Orders)]

    %% Approach 1 Setup
    subgraph Approach 1: M365 Email Parsing
        Mailbox[Reillys Admin<br/>M365 Mailbox]
        AI_Extractor[Python FLASK + Graph API<br/>PDF Plumber / Regex Extract]
        Mailbox -- Receives PDF Email --> AI_Extractor
    end

    %% Approach 2 Setup
    subgraph Approach 2: Supplier Portal Web Scraping
        Portal[Vertilux Supplier<br/>Web Portal Dashboard]
        Scraper[Python Playwright<br/>Headless Chromium Browser]
        Portal -- Live Table Rows --> Scraper
    end

    %% Reconcile
    AI_Extractor -- Total & PO# --> Matcher1{Match with<br/>HubSpot Entry?}
    Scraper -- Order Amount & PO# --> Matcher2{Match with<br/>HubSpot Entry?}
    
    HS -. Compare Unconfirmed .-> Matcher1
    HS -. Compare Unconfirmed .-> Matcher2

    %% Updates
    Matcher1 -- Match: Yes --> Confirmed[Update CRM Status:<br/>Supplier Confirmed]
    Matcher1 -- Match: No --> Action[Update CRM Status:<br/>Action Needed]

    Matcher2 -- Match: Yes --> Confirmed
    Matcher2 -- Match: No --> Action
    
    Confirmed --> HS_Final[(HubSpot Successfully<br/>Updated)]
    Action --> HS_Final
```

### 1. Approach 1: M365 Email AI Parser
Suppliers who issue invoices via email PDFs are processed completely headlessly utilizing Microsoft Graph.
*   **Technologies Used:** Python, Flask, Microsoft Graph API, OAuth2, `pdfplumber` (OCR/Text Extraction), Docker.
*   **How it Works:** The system listens to the Reillys M365 mailbox. When a supplier sends an email, it intercepts the attachment, algorithmically isolates the PO numbers and financial totals, and checks them against the Hubspot database to reconcile differences automatically.

### 2. Approach 2: Asynchronous Supplier Portal Scraper
Suppliers (like Vertilux) who utilize web dashboards rather than PDF emails are natively processed via dynamic headless browser scraping.
*   **Technologies Used:** Python, Async Playwright (Chromium Headless), Requests, Docker.
*   **How it Works:** The application bypasses UI overlays and dialog modals to seamlessly log into the portal. It scrapes active financial cells from the dashboard tables, cross-checking the live data with the active HubSpot CRM tables systematically.

---

## ☁️ Cloud Infrastructure (Azure to GCP)

**Prototype Phase (Microsoft Azure):** 
The system was originally prototyped and conceptualized using **Microsoft Azure**, heavily leveraging serverless Azure Functions and Microsoft 365 app registrations. *Because the Azure prototype handled live, sensitive financial data, the deployed endpoints cannot be externally shared for confidentiality reasons.*

**Production Phase (GCP Cloud Run):**
Following the prototype iteration, the architecture was seamlessly transitioned. The codebase was completely containerized via Docker and deployed onto **Google Cloud Platform (GCP) Cloud Run**. This pivot drastically optimized scaling and effectively reduced operational serverless hosting costs while maintaining peak computing performance.

---

### 🎥 Live Demo / Video Walkthrough
Please find the included video demonstration showcasing the automation natively running:

**[View Video Walkthrough Demo](./Reillys%20-%20Approach%202.mp4)**

*(Note: The `Reillys - Approach 2.mp4` video file is included in the root directory alongside this repository).*
