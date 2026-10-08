"""Product search across Shopify-powered stores (Shopify's Global Catalog, UCP over MCP).

One API call returns products with prices, the seller and a direct checkout link for each variant, so Clara compares
stores without clicking through websites. Buying goes through the store's own checkout page in Clara's browser,
paid with a one-time Link card (bridge/link.py).

Docs: https://shopify.dev/docs/agents/catalog/global-catalog · protocol: https://ucp.dev
"""
import os
import re
from urllib.parse import urlparse

import httpx

ENDPOINT = os.environ.get("CLARA_SHOPIFY_CATALOG", "https://catalog.shopify.com/api/ucp/mcp")
# Shopify asks every agent to point at a UCP profile declaring what it does. This is Shopify's reference profile, which
# its docs allow during development; Clara's own lives at clara.thewiderlens.info/.well-known/ucp once published.
PROFILE = os.environ.get("CLARA_UCP_PROFILE", "https://shopify.dev/ucp/agent-profiles/2026-04-08/valid-with-capabilities.json")


class CatalogError(Exception):
    pass


def _money(m) -> str:
    try:
        return f"${int(m['amount']) / 100:,.2f}"
    except (KeyError, TypeError, ValueError):
        return ""


def summarize(product: dict) -> dict:
    variants = product.get("variants") or []
    v = variants[0] if variants else {}
    seller = v.get("seller") or {}
    return {
        "title": product.get("title", "")[:140],
        "price": _money(v.get("price") or (product.get("price_range") or {}).get("min")),
        "price_cents": (v.get("price") or {}).get("amount"),
        "seller": seller.get("name", ""),
        # the store's own web address when it has one (marketcol.com), not its internal myshopify.com name
        "store": urlparse(seller.get("url") or "").hostname or urlparse(v.get("checkout_url") or "").hostname or seller.get("domain") or "",
        "product_id": product.get("id"), "variant_id": v.get("id"),
        "checkout_url": v.get("checkout_url") or "",
        "options": len(variants),
        "rating": (product.get("rating") or {}).get("value"),
    }


async def search(query: str, ships_to_zip: str = "", max_price_cents=None, min_price_cents=None, limit=8, client=None) -> list:
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:200]
    if not query:
        raise CatalogError("say what to search for")
    filters = {"available": True}
    if ships_to_zip:
        filters["ships_to"] = {"country": "US", "postal_code": str(ships_to_zip)[:10]}
    if max_price_cents or min_price_cents:
        filters["price"] = {k: int(v) for k, v in (("min", min_price_cents), ("max", max_price_cents)) if v}
    body = {"jsonrpc": "2.0", "method": "tools/call", "id": 1, "params": {"name": "search_catalog", "arguments": {
        "meta": {"ucp-agent": {"profile": PROFILE}},
        "catalog": {"query": query, "context": {"address_country": "US", "currency": "USD", "language": "en"},
                    "filters": filters, "pagination": {"limit": max(1, min(int(limit), 20))}}}}}
    own = client is None
    client = client or httpx.AsyncClient(timeout=40)
    try:
        r = await client.post(ENDPOINT, json=body, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise CatalogError(f"couldn't reach Shopify's catalog ({type(e).__name__})")
    finally:
        if own:
            await client.aclose()
    try:
        d = r.json()
    except ValueError:
        raise CatalogError(f"Shopify's catalog answered {r.status_code}")
    if d.get("error"):
        raise CatalogError(str((d["error"] or {}).get("message") or d["error"])[:200])
    sc = (d.get("result") or {}).get("structuredContent") or {}
    found = [summarize(p) for p in sc.get("products") or []]
    # the catalog's price filter is a hint, not a guarantee: enforce the user's range here
    return [p for p in found if p["price_cents"] is None or ((not max_price_cents or p["price_cents"] <= max_price_cents)
                                                             and (not min_price_cents or p["price_cents"] >= min_price_cents))]
