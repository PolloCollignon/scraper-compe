import requests
from bs4 import BeautifulSoup
import json
import sqlite3
import pandas as pd
from datetime import datetime
import time

print("Scraper de competencia iniciado.")

# -------------------------------------------------------
# CONFIGURACIÓN DE TIENDAS
# platform:  shopify
# inventory: "inventory_json"      → data-product-inventory-json (lebump style)
#            "data_attribute"      → data-inventoryQuantity en el HTML (labarriguita)
#            "variant_available"   → solo available:true/false en el JSON (las demás)
# -------------------------------------------------------
STORES = [
    {
        "name": "mumpreggo",
        "base_url": "https://mumpreggo.com",
        "inventory": "variant_available",
    },
    {
        "name": "hellomom",
        "base_url": "https://hellomom.com.mx",
        "inventory": "variant_available",
    },
    {
        "name": "hellomom_lomas",
        "base_url": "https://hellomom-gdllomasaltas.com.mx",
        "inventory": "variant_available",
    },
    {
        "name": "moman",
        "base_url": "https://moman.mx",
        "inventory": "variant_available",
    },
    {
        "name": "labarriguita",
        "base_url": "https://labarriguitademama.com",
        "inventory": "data_attribute",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}

DB_FILE = "inventario_competencia.db"


# -------------------------------------------------------
# BASE DE DATOS
# -------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventario (
            tienda              TEXT,
            product_url         TEXT,
            product_name        TEXT,
            variant_id          TEXT,
            variant_title       TEXT,
            sku                 TEXT,
            price               TEXT,
            inventory_quantity  INTEGER,
            available           INTEGER,
            timestamp           TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_to_db(df: pd.DataFrame):
    conn = sqlite3.connect(DB_FILE)
    df.to_sql("inventario", conn, if_exists="append", index=False)
    conn.close()
    print(f"  💾 {len(df)} filas guardadas en {DB_FILE}")


# -------------------------------------------------------
# OBTENER TODOS LOS PRODUCTOS (igual en todas las tiendas)
# -------------------------------------------------------
def get_all_products(base_url: str) -> list:
    all_products = []
    page = 1
    while True:
        url = f"{base_url}/products.json?page={page}&limit=250"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException as e:
            print(f"    ⚠️  Error de red en página {page}: {e}")
            break

        if resp.status_code != 200:
            print(f"    ⚠️  HTTP {resp.status_code} en {url}")
            break

        products = resp.json().get("products", [])
        if not products:
            break

        all_products.extend(products)
        print(f"    Página {page}: {len(products)} productos")
        page += 1
        time.sleep(0.6)

    return all_products


# -------------------------------------------------------
# MÉTODO A: data-product-inventory-json  (lebump style)
# Devuelve inventory_quantity real
# -------------------------------------------------------
def extract_inventory_json(base_url: str, product: dict) -> list:
    handle = product["handle"]
    product_url = f"{base_url}/products/{handle}"
    rows = []

    try:
        resp = requests.get(product_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return rows

        soup = BeautifulSoup(resp.text, "html.parser")
        script_tag = soup.find(
            "script",
            {"type": "application/json", "data-product-inventory-json": True},
        )
        if not script_tag:
            return rows

        inv_data = json.loads(script_tag.string)
        for variant_id, val in inv_data.get("inventory", {}).items():
            qty = val.get("inventory_quantity", 0)
            rows.append({
                "variant_id": variant_id,
                "variant_title": "",
                "sku": "",
                "price": "",
                "inventory_quantity": qty,
                "available": int(qty > 0),
            })
    except Exception as e:
        print(f"      ⚠️  extract_inventory_json falló ({handle}): {e}")

    return rows


# -------------------------------------------------------
# MÉTODO B: data-inventoryQuantity en el HTML (labarriguita)
# Devuelve inventory_quantity real
# -------------------------------------------------------
def extract_data_attribute(base_url: str, product: dict) -> list:
    handle = product["handle"]
    product_url = f"{base_url}/products/{handle}"
    rows = []

    try:
        resp = requests.get(product_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return rows

        soup = BeautifulSoup(resp.text, "html.parser")

        # Buscar elementos con data-inventoryquantity
        elements = soup.find_all(attrs={"data-inventoryquantity": True})

        if elements:
            for el in elements:
                qty = int(el.get("data-inventoryquantity", 0) or 0)
                variant_id = el.get("data-variant-id", el.get("data-id", ""))
                variant_title = el.get("data-variant-title", el.get("data-title", ""))
                rows.append({
                    "variant_id": str(variant_id),
                    "variant_title": variant_title,
                    "sku": el.get("data-sku", ""),
                    "price": el.get("data-price", ""),
                    "inventory_quantity": qty,
                    "available": int(qty > 0),
                })
        else:
            # Fallback: buscar en scripts JSON que contengan inventoryQuantity
            for script in soup.find_all("script"):
                if script.string and "inventoryQuantity" in script.string:
                    try:
                        text = script.string.strip()
                        start = text.find("{")
                        end = text.rfind("}") + 1
                        if start != -1:
                            data = json.loads(text[start:end])
                            variants = data.get("variants", [])
                            for v in variants:
                                qty = v.get("inventoryQuantity", v.get("inventory_quantity", 0))
                                rows.append({
                                    "variant_id": str(v.get("id", "")),
                                    "variant_title": v.get("title", ""),
                                    "sku": v.get("sku", ""),
                                    "price": str(v.get("price", "")),
                                    "inventory_quantity": qty,
                                    "available": int(qty > 0),
                                })
                            if rows:
                                break
                    except Exception:
                        continue

    except Exception as e:
        print(f"      ⚠️  extract_data_attribute falló ({handle}): {e}")

    return rows


# -------------------------------------------------------
# MÉTODO C: available true/false desde /products.json
# No da cantidad exacta, solo disponible (1) o no (0)
# -------------------------------------------------------
def extract_variant_available(product: dict, base_url: str) -> list:
    handle = product["handle"]
    rows = []

    try:
        for v in product.get("variants", []):
            available = v.get("available", False)
            rows.append({
                "variant_id": str(v.get("id", "")),
                "variant_title": v.get("title", ""),
                "sku": v.get("sku", ""),
                "price": str(v.get("price", "")),
                "inventory_quantity": None,  # No expuesto por Shopify en este método
                "available": int(available),
            })
    except Exception as e:
        print(f"      ⚠️  extract_variant_available falló ({handle}): {e}")

    return rows


# -------------------------------------------------------
# SCRAPER PRINCIPAL POR TIENDA
# -------------------------------------------------------
def scrape_store(store: dict) -> pd.DataFrame:
    name = store["name"]
    base_url = store["base_url"]
    method = store["inventory"]

    print(f"\n🛍️  [{name}] {base_url}  |  método: {method}")

    products = get_all_products(base_url)
    print(f"  Total productos: {len(products)}")

    if not products:
        print(f"  ⛔ Sin productos")
        return pd.DataFrame()

    all_rows = []
    for i, product in enumerate(products):
        handle = product.get("handle", "")
        print(f"  [{i+1}/{len(products)}] {handle}")

        if method == "inventory_json":
            rows = extract_inventory_json(base_url, product)
        elif method == "data_attribute":
            rows = extract_data_attribute(base_url, product)
        elif method == "variant_available":
            # Ya tenemos los datos del products.json, sin petición extra
            rows = extract_variant_available(product, base_url)
        else:
            rows = []

        for r in rows:
            r["tienda"] = name
            r["product_url"] = f"{base_url}/products/{handle}"
            r["product_name"] = handle

        all_rows.extend(rows)

        # Solo pausar si hicimos una petición HTTP extra al producto
        if method in ("inventory_json", "data_attribute"):
            time.sleep(0.5)

    df = pd.DataFrame(all_rows)
    df["timestamp"] = datetime.now().isoformat()
    return df


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    init_db()
    all_dfs = []

    for store in STORES:
        df = scrape_store(store)
        if not df.empty:
            all_dfs.append(df)

    if all_dfs:
        df_final = pd.concat(all_dfs, ignore_index=True)
        save_to_db(df_final)
        print(f"\n✅ Scraping completado. Total filas: {len(df_final)}")
    else:
        print("\n⚠️  No se obtuvo ningún dato.")


if __name__ == "__main__":
    main()
