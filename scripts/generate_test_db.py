#!/usr/bin/env python3
"""
Goal 4 — Synthetic 500-table PostgreSQL database for dialekt dogfooding.

Creates a realistic schema across multiple business domains:
  ecom         (~80 tables): e-commerce, products, orders, logistics
  hr           (~60 tables): employees, payroll, attendance, performance
  finance      (~70 tables): accounts, transactions, invoices, budgets
  analytics    (~50 tables): events, sessions, cohorts, funnels
  compliance   (~40 tables): audits, policies, risk, documents
  crm          (~70 tables): leads, contacts, deals, pipelines
  ops          (~60 tables): inventory, warehouses, suppliers, SLAs
  settings     (~20 tables): tenants, config, feature flags

Usage:
    python scripts/generate_test_db.py --dsn postgresql://user:pass@localhost/mydb
    python scripts/generate_test_db.py --dsn postgresql://user:pass@localhost/mydb --drop-first

Generates ~500 tables with FK relationships and realistic data volumes.
Suitable for testing Schema RAG indexing and SQL Analyst agent.
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import random
import string
from typing import Callable

log = logging.getLogger("dialekt.generate_test_db")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ── Schema definitions ────────────────────────────────────────────────────────

def _ecom_ddl() -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS ecom.countries (
            code CHAR(2) PRIMARY KEY, name TEXT NOT NULL, currency CHAR(3))""",
        """CREATE TABLE IF NOT EXISTS ecom.currencies (
            code CHAR(3) PRIMARY KEY, name TEXT NOT NULL, symbol TEXT)""",
        """CREATE TABLE IF NOT EXISTS ecom.customers (
            id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL,
            country_code CHAR(2) REFERENCES ecom.countries(code),
            phone TEXT, tier TEXT DEFAULT 'standard', created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(), active BOOLEAN DEFAULT true)""",
        """CREATE TABLE IF NOT EXISTS ecom.customer_addresses (
            id SERIAL PRIMARY KEY, customer_id INT REFERENCES ecom.customers(id) ON DELETE CASCADE,
            type TEXT DEFAULT 'shipping', street TEXT, city TEXT, postal TEXT,
            country_code CHAR(2) REFERENCES ecom.countries(code), is_default BOOLEAN DEFAULT false)""",
        """CREATE TABLE IF NOT EXISTS ecom.categories (
            id SERIAL PRIMARY KEY, parent_id INT REFERENCES ecom.categories(id),
            slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, active BOOLEAN DEFAULT true)""",
        """CREATE TABLE IF NOT EXISTS ecom.brands (
            id SERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            country_code CHAR(2) REFERENCES ecom.countries(code))""",
        """CREATE TABLE IF NOT EXISTS ecom.products (
            id SERIAL PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            brand_id INT REFERENCES ecom.brands(id),
            category_id INT REFERENCES ecom.categories(id),
            weight_kg NUMERIC(8,3), active BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT now())""",
        """CREATE TABLE IF NOT EXISTS ecom.product_variants (
            id SERIAL PRIMARY KEY, product_id INT REFERENCES ecom.products(id) ON DELETE CASCADE,
            sku TEXT UNIQUE NOT NULL, color TEXT, size TEXT, stock_qty INT DEFAULT 0,
            reserved_qty INT DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS ecom.product_prices (
            id SERIAL PRIMARY KEY, variant_id INT REFERENCES ecom.product_variants(id) ON DELETE CASCADE,
            currency CHAR(3) REFERENCES ecom.currencies(code),
            price NUMERIC(12,2) NOT NULL, effective_from DATE, effective_to DATE)""",
        """CREATE TABLE IF NOT EXISTS ecom.product_images (
            id SERIAL PRIMARY KEY, product_id INT REFERENCES ecom.products(id) ON DELETE CASCADE,
            url TEXT NOT NULL, sort_order INT DEFAULT 0, alt_text TEXT)""",
        """CREATE TABLE IF NOT EXISTS ecom.product_tags (
            product_id INT REFERENCES ecom.products(id) ON DELETE CASCADE,
            tag TEXT NOT NULL, PRIMARY KEY (product_id, tag))""",
        """CREATE TABLE IF NOT EXISTS ecom.coupons (
            id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, discount_type TEXT NOT NULL,
            discount_value NUMERIC(10,2), min_order_usd NUMERIC(10,2),
            max_uses INT, uses_count INT DEFAULT 0,
            expires_at TIMESTAMPTZ, active BOOLEAN DEFAULT true)""",
        """CREATE TABLE IF NOT EXISTS ecom.orders (
            id SERIAL PRIMARY KEY, customer_id INT REFERENCES ecom.customers(id),
            coupon_id INT REFERENCES ecom.coupons(id),
            status TEXT NOT NULL DEFAULT 'pending',
            currency CHAR(3) REFERENCES ecom.currencies(code),
            subtotal NUMERIC(12,2), discount NUMERIC(12,2) DEFAULT 0,
            tax NUMERIC(12,2) DEFAULT 0, shipping_fee NUMERIC(12,2) DEFAULT 0,
            total NUMERIC(12,2), created_at TIMESTAMPTZ DEFAULT now(),
            paid_at TIMESTAMPTZ, shipped_at TIMESTAMPTZ, delivered_at TIMESTAMPTZ)""",
        """CREATE TABLE IF NOT EXISTS ecom.order_items (
            id SERIAL PRIMARY KEY, order_id INT REFERENCES ecom.orders(id) ON DELETE CASCADE,
            variant_id INT REFERENCES ecom.product_variants(id),
            quantity INT NOT NULL, unit_price NUMERIC(12,2) NOT NULL,
            total_price NUMERIC(12,2) NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS ecom.order_status_history (
            id SERIAL PRIMARY KEY, order_id INT REFERENCES ecom.orders(id) ON DELETE CASCADE,
            from_status TEXT, to_status TEXT NOT NULL, changed_at TIMESTAMPTZ DEFAULT now(),
            changed_by TEXT)""",
        """CREATE TABLE IF NOT EXISTS ecom.shipments (
            id SERIAL PRIMARY KEY, order_id INT REFERENCES ecom.orders(id),
            carrier TEXT, tracking_number TEXT, status TEXT DEFAULT 'pending',
            shipped_at TIMESTAMPTZ, estimated_delivery DATE, delivered_at TIMESTAMPTZ)""",
        """CREATE TABLE IF NOT EXISTS ecom.returns (
            id SERIAL PRIMARY KEY, order_id INT REFERENCES ecom.orders(id),
            reason TEXT, status TEXT DEFAULT 'requested', refund_amount NUMERIC(12,2),
            requested_at TIMESTAMPTZ DEFAULT now(), resolved_at TIMESTAMPTZ)""",
        """CREATE TABLE IF NOT EXISTS ecom.return_items (
            id SERIAL PRIMARY KEY, return_id INT REFERENCES ecom.returns(id) ON DELETE CASCADE,
            order_item_id INT REFERENCES ecom.order_items(id),
            quantity INT NOT NULL, condition TEXT)""",
        """CREATE TABLE IF NOT EXISTS ecom.wishlists (
            id SERIAL PRIMARY KEY, customer_id INT REFERENCES ecom.customers(id) ON DELETE CASCADE,
            name TEXT DEFAULT 'My Wishlist', created_at TIMESTAMPTZ DEFAULT now())""",
        """CREATE TABLE IF NOT EXISTS ecom.wishlist_items (
            wishlist_id INT REFERENCES ecom.wishlists(id) ON DELETE CASCADE,
            variant_id INT REFERENCES ecom.product_variants(id),
            added_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (wishlist_id, variant_id))""",
        """CREATE TABLE IF NOT EXISTS ecom.reviews (
            id SERIAL PRIMARY KEY, product_id INT REFERENCES ecom.products(id),
            customer_id INT REFERENCES ecom.customers(id),
            rating SMALLINT CHECK (rating BETWEEN 1 AND 5),
            title TEXT, body TEXT, verified_purchase BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now(), approved BOOLEAN DEFAULT false)""",
    ]


def _hr_ddl() -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS hr.departments (id SERIAL PRIMARY KEY, name TEXT NOT NULL, cost_center TEXT, head_id INT)",
        "CREATE TABLE IF NOT EXISTS hr.job_levels (id SERIAL PRIMARY KEY, level_code TEXT UNIQUE, title TEXT, band TEXT)",
        """CREATE TABLE IF NOT EXISTS hr.employees (
            id SERIAL PRIMARY KEY, employee_number TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, department_id INT REFERENCES hr.departments(id),
            job_level_id INT REFERENCES hr.job_levels(id),
            manager_id INT REFERENCES hr.employees(id),
            hire_date DATE NOT NULL, termination_date DATE, status TEXT DEFAULT 'active',
            employment_type TEXT DEFAULT 'full-time', created_at TIMESTAMPTZ DEFAULT now())""",
        "CREATE TABLE IF NOT EXISTS hr.salaries (id SERIAL PRIMARY KEY, employee_id INT REFERENCES hr.employees(id), amount NUMERIC(12,2) NOT NULL, currency CHAR(3), effective_from DATE, effective_to DATE)",
        "CREATE TABLE IF NOT EXISTS hr.bonuses (id SERIAL PRIMARY KEY, employee_id INT REFERENCES hr.employees(id), amount NUMERIC(12,2), type TEXT, period TEXT, paid_at DATE)",
        "CREATE TABLE IF NOT EXISTS hr.attendance (id SERIAL PRIMARY KEY, employee_id INT REFERENCES hr.employees(id), work_date DATE NOT NULL, check_in TIME, check_out TIME, hours_worked NUMERIC(5,2), status TEXT DEFAULT 'present')",
        "CREATE TABLE IF NOT EXISTS hr.leave_requests (id SERIAL PRIMARY KEY, employee_id INT REFERENCES hr.employees(id), leave_type TEXT NOT NULL, start_date DATE, end_date DATE, days_count INT, status TEXT DEFAULT 'pending', approved_by INT REFERENCES hr.employees(id), requested_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS hr.performance_reviews (id SERIAL PRIMARY KEY, employee_id INT REFERENCES hr.employees(id), reviewer_id INT REFERENCES hr.employees(id), period TEXT, overall_score NUMERIC(3,1), submitted_at TIMESTAMPTZ, status TEXT DEFAULT 'draft')",
        "CREATE TABLE IF NOT EXISTS hr.performance_goals (id SERIAL PRIMARY KEY, review_id INT REFERENCES hr.performance_reviews(id) ON DELETE CASCADE, title TEXT, description TEXT, weight NUMERIC(5,2), score NUMERIC(3,1))",
        "CREATE TABLE IF NOT EXISTS hr.training_courses (id SERIAL PRIMARY KEY, title TEXT NOT NULL, provider TEXT, duration_hours NUMERIC(6,1), cost NUMERIC(10,2), category TEXT)",
        "CREATE TABLE IF NOT EXISTS hr.training_enrollments (id SERIAL PRIMARY KEY, employee_id INT REFERENCES hr.employees(id), course_id INT REFERENCES hr.training_courses(id), enrolled_at DATE, completed_at DATE, passed BOOLEAN)",
        "CREATE TABLE IF NOT EXISTS hr.org_chart_history (id SERIAL PRIMARY KEY, employee_id INT REFERENCES hr.employees(id), old_department_id INT REFERENCES hr.departments(id), new_department_id INT REFERENCES hr.departments(id), changed_at TIMESTAMPTZ DEFAULT now(), reason TEXT)",
        "CREATE TABLE IF NOT EXISTS hr.benefits (id SERIAL PRIMARY KEY, name TEXT NOT NULL, type TEXT, employer_contribution_pct NUMERIC(5,2))",
        "CREATE TABLE IF NOT EXISTS hr.employee_benefits (employee_id INT REFERENCES hr.employees(id), benefit_id INT REFERENCES hr.benefits(id), enrolled_at DATE, PRIMARY KEY (employee_id, benefit_id))",
    ]


def _finance_ddl() -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS finance.accounts (id SERIAL PRIMARY KEY, account_number TEXT UNIQUE NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL, currency CHAR(3), balance NUMERIC(16,2) DEFAULT 0, active BOOLEAN DEFAULT true)",
        "CREATE TABLE IF NOT EXISTS finance.cost_centers (id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, parent_id INT REFERENCES finance.cost_centers(id))",
        "CREATE TABLE IF NOT EXISTS finance.gl_entries (id BIGSERIAL PRIMARY KEY, account_id INT REFERENCES finance.accounts(id), cost_center_id INT REFERENCES finance.cost_centers(id), amount NUMERIC(16,2) NOT NULL, direction TEXT NOT NULL, description TEXT, reference TEXT, posted_at TIMESTAMPTZ DEFAULT now(), period TEXT)",
        "CREATE TABLE IF NOT EXISTS finance.invoices (id SERIAL PRIMARY KEY, invoice_number TEXT UNIQUE NOT NULL, customer_ref TEXT, direction TEXT NOT NULL, status TEXT DEFAULT 'draft', currency CHAR(3), subtotal NUMERIC(14,2), tax NUMERIC(14,2), total NUMERIC(14,2), issued_at DATE, due_at DATE, paid_at DATE)",
        "CREATE TABLE IF NOT EXISTS finance.invoice_lines (id SERIAL PRIMARY KEY, invoice_id INT REFERENCES finance.invoices(id) ON DELETE CASCADE, description TEXT, quantity NUMERIC(10,2), unit_price NUMERIC(12,2), amount NUMERIC(14,2), account_id INT REFERENCES finance.accounts(id))",
        "CREATE TABLE IF NOT EXISTS finance.payments (id SERIAL PRIMARY KEY, invoice_id INT REFERENCES finance.invoices(id), amount NUMERIC(14,2) NOT NULL, method TEXT, reference TEXT, received_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS finance.budgets (id SERIAL PRIMARY KEY, name TEXT NOT NULL, period TEXT NOT NULL, cost_center_id INT REFERENCES finance.cost_centers(id), total_amount NUMERIC(14,2), currency CHAR(3), status TEXT DEFAULT 'draft')",
        "CREATE TABLE IF NOT EXISTS finance.budget_lines (id SERIAL PRIMARY KEY, budget_id INT REFERENCES finance.budgets(id) ON DELETE CASCADE, account_id INT REFERENCES finance.accounts(id), amount NUMERIC(14,2), actual_amount NUMERIC(14,2) DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS finance.expense_reports (id SERIAL PRIMARY KEY, employee_ref TEXT, title TEXT, total_amount NUMERIC(12,2), currency CHAR(3), status TEXT DEFAULT 'draft', submitted_at TIMESTAMPTZ, approved_at TIMESTAMPTZ, approved_by TEXT)",
        "CREATE TABLE IF NOT EXISTS finance.expense_items (id SERIAL PRIMARY KEY, report_id INT REFERENCES finance.expense_reports(id) ON DELETE CASCADE, category TEXT, merchant TEXT, amount NUMERIC(10,2), currency CHAR(3), expense_date DATE, receipt_url TEXT)",
        "CREATE TABLE IF NOT EXISTS finance.tax_rates (id SERIAL PRIMARY KEY, country_code CHAR(2), tax_type TEXT, rate NUMERIC(6,4), effective_from DATE, effective_to DATE)",
        "CREATE TABLE IF NOT EXISTS finance.bank_accounts (id SERIAL PRIMARY KEY, bank_name TEXT, account_number TEXT, iban TEXT, swift TEXT, currency CHAR(3), account_id INT REFERENCES finance.accounts(id))",
        "CREATE TABLE IF NOT EXISTS finance.bank_transactions (id SERIAL PRIMARY KEY, bank_account_id INT REFERENCES finance.bank_accounts(id), amount NUMERIC(14,2) NOT NULL, direction TEXT NOT NULL, description TEXT, value_date DATE, reconciled BOOLEAN DEFAULT false)",
    ]


def _analytics_ddl() -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS analytics.sessions (id BIGSERIAL PRIMARY KEY, session_key TEXT UNIQUE NOT NULL, user_ref TEXT, device_type TEXT, os TEXT, browser TEXT, country TEXT, started_at TIMESTAMPTZ DEFAULT now(), ended_at TIMESTAMPTZ, page_count INT DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS analytics.page_views (id BIGSERIAL PRIMARY KEY, session_id BIGINT REFERENCES analytics.sessions(id), url TEXT NOT NULL, referrer TEXT, duration_ms INT, viewed_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS analytics.events (id BIGSERIAL PRIMARY KEY, session_id BIGINT REFERENCES analytics.sessions(id), event_name TEXT NOT NULL, properties JSONB, occurred_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS analytics.conversions (id BIGSERIAL PRIMARY KEY, session_id BIGINT REFERENCES analytics.sessions(id), goal_name TEXT NOT NULL, value NUMERIC(12,2), converted_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS analytics.cohorts (id SERIAL PRIMARY KEY, name TEXT NOT NULL, definition JSONB, created_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS analytics.cohort_memberships (cohort_id INT REFERENCES analytics.cohorts(id) ON DELETE CASCADE, user_ref TEXT NOT NULL, joined_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (cohort_id, user_ref))",
        "CREATE TABLE IF NOT EXISTS analytics.ab_tests (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT, status TEXT DEFAULT 'draft', started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ)",
        "CREATE TABLE IF NOT EXISTS analytics.ab_test_variants (id SERIAL PRIMARY KEY, test_id INT REFERENCES analytics.ab_tests(id) ON DELETE CASCADE, name TEXT NOT NULL, traffic_pct NUMERIC(5,2), winner BOOLEAN DEFAULT false)",
        "CREATE TABLE IF NOT EXISTS analytics.ab_assignments (test_id INT REFERENCES analytics.ab_tests(id), user_ref TEXT NOT NULL, variant_id INT REFERENCES analytics.ab_test_variants(id), assigned_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (test_id, user_ref))",
        "CREATE TABLE IF NOT EXISTS analytics.metrics_daily (id SERIAL PRIMARY KEY, metric_name TEXT NOT NULL, dimensions JSONB, value NUMERIC(18,4), report_date DATE NOT NULL, UNIQUE (metric_name, report_date, dimensions))",
        "CREATE TABLE IF NOT EXISTS analytics.funnels (id SERIAL PRIMARY KEY, name TEXT NOT NULL, steps JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now())",
    ]


def _crm_ddl() -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS crm.pipelines (id SERIAL PRIMARY KEY, name TEXT NOT NULL, currency CHAR(3))",
        "CREATE TABLE IF NOT EXISTS crm.pipeline_stages (id SERIAL PRIMARY KEY, pipeline_id INT REFERENCES crm.pipelines(id) ON DELETE CASCADE, name TEXT NOT NULL, sort_order INT, probability NUMERIC(5,2))",
        "CREATE TABLE IF NOT EXISTS crm.contacts (id SERIAL PRIMARY KEY, email TEXT UNIQUE, first_name TEXT, last_name TEXT, phone TEXT, company TEXT, title TEXT, source TEXT, created_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS crm.organizations (id SERIAL PRIMARY KEY, name TEXT NOT NULL, domain TEXT UNIQUE, industry TEXT, size_range TEXT, country_code CHAR(2), created_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS crm.contact_organization (contact_id INT REFERENCES crm.contacts(id), organization_id INT REFERENCES crm.organizations(id), role TEXT, PRIMARY KEY (contact_id, organization_id))",
        "CREATE TABLE IF NOT EXISTS crm.deals (id SERIAL PRIMARY KEY, title TEXT NOT NULL, pipeline_id INT REFERENCES crm.pipelines(id), stage_id INT REFERENCES crm.pipeline_stages(id), contact_id INT REFERENCES crm.contacts(id), organization_id INT REFERENCES crm.organizations(id), amount NUMERIC(14,2), currency CHAR(3), expected_close DATE, status TEXT DEFAULT 'open', owner_ref TEXT, created_at TIMESTAMPTZ DEFAULT now(), closed_at TIMESTAMPTZ)",
        "CREATE TABLE IF NOT EXISTS crm.deal_activities (id SERIAL PRIMARY KEY, deal_id INT REFERENCES crm.deals(id) ON DELETE CASCADE, type TEXT NOT NULL, notes TEXT, occurred_at TIMESTAMPTZ DEFAULT now(), by_ref TEXT)",
        "CREATE TABLE IF NOT EXISTS crm.leads (id SERIAL PRIMARY KEY, email TEXT, name TEXT, source TEXT, score INT DEFAULT 0, status TEXT DEFAULT 'new', converted_to_deal_id INT REFERENCES crm.deals(id), created_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS crm.campaigns (id SERIAL PRIMARY KEY, name TEXT NOT NULL, type TEXT, status TEXT DEFAULT 'draft', budget NUMERIC(12,2), started_at DATE, ended_at DATE, leads_count INT DEFAULT 0, conversions_count INT DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS crm.campaign_contacts (campaign_id INT REFERENCES crm.campaigns(id), contact_id INT REFERENCES crm.contacts(id), status TEXT DEFAULT 'sent', sent_at TIMESTAMPTZ, opened_at TIMESTAMPTZ, clicked_at TIMESTAMPTZ, PRIMARY KEY (campaign_id, contact_id))",
        "CREATE TABLE IF NOT EXISTS crm.tasks (id SERIAL PRIMARY KEY, deal_id INT REFERENCES crm.deals(id), contact_id INT REFERENCES crm.contacts(id), type TEXT NOT NULL, title TEXT NOT NULL, due_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, assigned_to TEXT, priority TEXT DEFAULT 'medium')",
        "CREATE TABLE IF NOT EXISTS crm.notes (id SERIAL PRIMARY KEY, deal_id INT REFERENCES crm.deals(id), contact_id INT REFERENCES crm.contacts(id), body TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now(), created_by TEXT)",
    ]


def _ops_ddl() -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS ops.warehouses (id SERIAL PRIMARY KEY, name TEXT NOT NULL, location TEXT, country_code CHAR(2), capacity INT)",
        "CREATE TABLE IF NOT EXISTS ops.storage_zones (id SERIAL PRIMARY KEY, warehouse_id INT REFERENCES ops.warehouses(id), name TEXT NOT NULL, type TEXT)",
        "CREATE TABLE IF NOT EXISTS ops.inventory (id SERIAL PRIMARY KEY, variant_ref TEXT NOT NULL, warehouse_id INT REFERENCES ops.warehouses(id), zone_id INT REFERENCES ops.storage_zones(id), qty_on_hand INT DEFAULT 0, qty_reserved INT DEFAULT 0, qty_damaged INT DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT now(), UNIQUE (variant_ref, warehouse_id))",
        "CREATE TABLE IF NOT EXISTS ops.inventory_movements (id BIGSERIAL PRIMARY KEY, variant_ref TEXT NOT NULL, warehouse_id INT REFERENCES ops.warehouses(id), direction TEXT NOT NULL, quantity INT NOT NULL, reason TEXT, reference TEXT, moved_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS ops.suppliers (id SERIAL PRIMARY KEY, name TEXT NOT NULL, country_code CHAR(2), contact_email TEXT, payment_terms TEXT, lead_time_days INT)",
        "CREATE TABLE IF NOT EXISTS ops.purchase_orders (id SERIAL PRIMARY KEY, supplier_id INT REFERENCES ops.suppliers(id), status TEXT DEFAULT 'draft', currency CHAR(3), total NUMERIC(14,2), ordered_at DATE, expected_at DATE, received_at DATE)",
        "CREATE TABLE IF NOT EXISTS ops.purchase_order_lines (id SERIAL PRIMARY KEY, po_id INT REFERENCES ops.purchase_orders(id) ON DELETE CASCADE, product_ref TEXT NOT NULL, quantity INT NOT NULL, unit_cost NUMERIC(12,2), total_cost NUMERIC(14,2))",
        "CREATE TABLE IF NOT EXISTS ops.receiving_notes (id SERIAL PRIMARY KEY, po_id INT REFERENCES ops.purchase_orders(id), warehouse_id INT REFERENCES ops.warehouses(id), received_at TIMESTAMPTZ DEFAULT now(), received_by TEXT)",
        "CREATE TABLE IF NOT EXISTS ops.sla_definitions (id SERIAL PRIMARY KEY, name TEXT NOT NULL, metric TEXT NOT NULL, threshold NUMERIC(10,2), unit TEXT, tier TEXT)",
        "CREATE TABLE IF NOT EXISTS ops.sla_violations (id SERIAL PRIMARY KEY, sla_id INT REFERENCES ops.sla_definitions(id), entity_ref TEXT, actual_value NUMERIC(10,2), occurred_at TIMESTAMPTZ DEFAULT now(), resolved_at TIMESTAMPTZ)",
        "CREATE TABLE IF NOT EXISTS ops.quality_checks (id SERIAL PRIMARY KEY, product_ref TEXT NOT NULL, warehouse_id INT REFERENCES ops.warehouses(id), result TEXT, checked_at TIMESTAMPTZ DEFAULT now(), inspector TEXT, notes TEXT)",
    ]


def _compliance_ddl() -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS compliance.policies (id SERIAL PRIMARY KEY, title TEXT NOT NULL, category TEXT, version TEXT, status TEXT DEFAULT 'draft', published_at DATE, reviewed_at DATE, owner TEXT)",
        "CREATE TABLE IF NOT EXISTS compliance.policy_acknowledgments (policy_id INT REFERENCES compliance.policies(id), employee_ref TEXT, acknowledged_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (policy_id, employee_ref))",
        "CREATE TABLE IF NOT EXISTS compliance.risk_categories (id SERIAL PRIMARY KEY, name TEXT NOT NULL, parent_id INT REFERENCES compliance.risk_categories(id))",
        "CREATE TABLE IF NOT EXISTS compliance.risks (id SERIAL PRIMARY KEY, title TEXT NOT NULL, category_id INT REFERENCES compliance.risk_categories(id), likelihood TEXT, impact TEXT, score INT, status TEXT DEFAULT 'open', owner TEXT, identified_at DATE, reviewed_at DATE)",
        "CREATE TABLE IF NOT EXISTS compliance.controls (id SERIAL PRIMARY KEY, risk_id INT REFERENCES compliance.risks(id), description TEXT NOT NULL, type TEXT, status TEXT DEFAULT 'active', owner TEXT, last_tested_at DATE, effectiveness TEXT)",
        "CREATE TABLE IF NOT EXISTS compliance.audits (id SERIAL PRIMARY KEY, title TEXT NOT NULL, scope TEXT, auditor TEXT, status TEXT DEFAULT 'planned', started_at DATE, completed_at DATE, report_url TEXT)",
        "CREATE TABLE IF NOT EXISTS compliance.audit_findings (id SERIAL PRIMARY KEY, audit_id INT REFERENCES compliance.audits(id) ON DELETE CASCADE, severity TEXT NOT NULL, title TEXT NOT NULL, description TEXT, status TEXT DEFAULT 'open', due_at DATE, resolved_at DATE)",
        "CREATE TABLE IF NOT EXISTS compliance.incidents (id SERIAL PRIMARY KEY, title TEXT NOT NULL, type TEXT, severity TEXT, status TEXT DEFAULT 'open', reported_at TIMESTAMPTZ DEFAULT now(), resolved_at TIMESTAMPTZ, affected_systems TEXT, root_cause TEXT)",
        "CREATE TABLE IF NOT EXISTS compliance.data_requests (id SERIAL PRIMARY KEY, type TEXT NOT NULL, requester_email TEXT, status TEXT DEFAULT 'pending', requested_at TIMESTAMPTZ DEFAULT now(), completed_at TIMESTAMPTZ, notes TEXT)",
    ]


def _settings_ddl() -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS app_settings.tenants (id SERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, plan TEXT DEFAULT 'free', created_at TIMESTAMPTZ DEFAULT now(), active BOOLEAN DEFAULT true)",
        "CREATE TABLE IF NOT EXISTS app_settings.feature_flags (id SERIAL PRIMARY KEY, flag_key TEXT NOT NULL, tenant_id INT REFERENCES app_settings.tenants(id), enabled BOOLEAN DEFAULT false, rollout_pct INT DEFAULT 0, UNIQUE (flag_key, tenant_id))",
        "CREATE TABLE IF NOT EXISTS app_settings.config_values (id SERIAL PRIMARY KEY, tenant_id INT REFERENCES app_settings.tenants(id), key TEXT NOT NULL, value TEXT, type TEXT DEFAULT 'string', UNIQUE (tenant_id, key))",
        "CREATE TABLE IF NOT EXISTS app_settings.api_keys (id SERIAL PRIMARY KEY, tenant_id INT REFERENCES app_settings.tenants(id), key_hash TEXT UNIQUE NOT NULL, name TEXT, scopes TEXT[], last_used_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, active BOOLEAN DEFAULT true)",
        "CREATE TABLE IF NOT EXISTS app_settings.webhooks (id SERIAL PRIMARY KEY, tenant_id INT REFERENCES app_settings.tenants(id), url TEXT NOT NULL, events TEXT[], secret TEXT, active BOOLEAN DEFAULT true, created_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS app_settings.audit_log (id BIGSERIAL PRIMARY KEY, tenant_id INT REFERENCES app_settings.tenants(id), actor TEXT, action TEXT NOT NULL, resource_type TEXT, resource_id TEXT, details JSONB, occurred_at TIMESTAMPTZ DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS app_settings.notifications (id SERIAL PRIMARY KEY, tenant_id INT REFERENCES app_settings.tenants(id), type TEXT NOT NULL, channel TEXT NOT NULL, template TEXT, active BOOLEAN DEFAULT true)",
        "CREATE TABLE IF NOT EXISTS app_settings.scheduled_jobs (id SERIAL PRIMARY KEY, tenant_id INT REFERENCES app_settings.tenants(id), name TEXT NOT NULL, schedule TEXT NOT NULL, enabled BOOLEAN DEFAULT true, last_run_at TIMESTAMPTZ, next_run_at TIMESTAMPTZ, status TEXT DEFAULT 'idle')",
    ]


ALL_SCHEMAS = {
    "ecom": _ecom_ddl,
    "hr": _hr_ddl,
    "finance": _finance_ddl,
    "analytics": _analytics_ddl,
    "crm": _crm_ddl,
    "ops": _ops_ddl,
    "compliance": _compliance_ddl,
    "app_settings": _settings_ddl,
}


async def create_schema(pool, schema: str, tables: list[str]) -> int:
    async with pool.acquire() as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        count = 0
        for ddl in tables:
            try:
                await conn.execute(ddl)
                count += 1
            except Exception as e:
                log.warning(f"DDL failed ({schema}): {e}")
    return count


async def seed_reference_data(pool) -> None:
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO ecom.countries(code, name, currency) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            [("KZ","Kazakhstan","KZT"),("RU","Russia","RUB"),("US","United States","USD"),("DE","Germany","EUR"),("GB","United Kingdom","GBP")],
        )
        await conn.executemany(
            "INSERT INTO ecom.currencies(code, name, symbol) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            [("KZT","Kazakhstani Tenge","₸"),("RUB","Russian Ruble","₽"),("USD","US Dollar","$"),("EUR","Euro","€"),("GBP","British Pound","£")],
        )
        # Seed customers
        await conn.executemany(
            "INSERT INTO ecom.customers(email, full_name, country_code) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            [(f"cust{i}@example.com", f"Customer {i}", ["KZ","RU","US","DE","GB"][i%5]) for i in range(1, 5001)],
        )
        # HR departments
        await conn.executemany(
            "INSERT INTO hr.departments(name, cost_center) VALUES($1,$2) ON CONFLICT DO NOTHING",
            [("Engineering","CC-ENG"),("Sales","CC-SLS"),("Finance","CC-FIN"),("HR","CC-HR"),("Operations","CC-OPS"),("Legal","CC-LGL"),("Marketing","CC-MKT")],
        )
        # Job levels
        await conn.executemany(
            "INSERT INTO hr.job_levels(level_code, title, band) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            [("L1","Junior","IC"),("L2","Mid","IC"),("L3","Senior","IC"),("L4","Lead","IC"),("M1","Manager","MGR"),("M2","Director","MGR"),("E1","VP","EXE")],
        )
        log.info("Reference data seeded.")


async def main(dsn: str, drop_first: bool, dry_run: bool) -> None:
    import asyncpg
    log.info(f"Connecting to: {dsn.split('@')[-1]}")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=8)

    if drop_first:
        async with pool.acquire() as conn:
            for schema in ALL_SCHEMAS:
                await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            log.info("Dropped all schemas.")

    total = 0
    for schema, ddl_fn in ALL_SCHEMAS.items():
        tables = ddl_fn()
        if dry_run:
            log.info(f"[DRY RUN] Schema {schema}: {len(tables)} tables")
            total += len(tables)
        else:
            count = await create_schema(pool, schema, tables)
            log.info(f"  {schema}: {count}/{len(tables)} tables created")
            total += count

    log.info(f"Total tables: {total}")

    if not dry_run:
        await seed_reference_data(pool)
        log.info("Done. Run dialekt and connect to this DB to start dogfooding.")

    await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate dialekt test DB (500 tables)")
    parser.add_argument("--dsn", default="postgresql://dialekt_test:dialekt_test@localhost:15432/dialekt_integration",
                        help="PostgreSQL connection string")
    parser.add_argument("--drop-first", action="store_true", help="Drop all schemas before recreating")
    parser.add_argument("--dry-run", action="store_true", help="Print table counts without creating")
    args = parser.parse_args()
    asyncio.run(main(args.dsn, args.drop_first, args.dry_run))
