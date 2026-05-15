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
# Agrega o quita tiendas aquí sin tocar el resto del código
# -------------------------------------------------------
STORES = [
    {
        "name": "mumpreggo",
        "base_url": "https://mumpreggo.com",
        "platform": "shopify",   # shopify | woocommerce | unknown
    },
    {
        "name": "hellomom",
        "base_url": "https://hellomom.com.mx",
        "platform": "shopify",
    },
    {
        "name": "hellomom_lomas",
        "base_url": "https://hellomom-gdllomasaltas.com.mx",
        "platform": "shopify",
    },
    {
        "name": "moman",
        "base_url": "https://moman.mx",
        "platform": "shopify",
    },
    {
        "name": "labarriguita",
        "base_url": "https://labarriguitademama.com",
        "platform": "shopify",
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
def save_to_db(df: pd.DataFrame):
    """Guarda el DataFrame en SQLite, acumulando registros históricos."""
    conn = sqlite3.connect(DB_FILE)
    df.to_sql("inventario", conn, if_exists="append", index=False)
    conn.close()
    print(f"  💾 {len(df)} filas guardadas en {DB_FILE}")


def init_db():
    """Crea la tabla si no existe (útil en primera ejecución)."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventario (
            tienda          TEXT,
            product_url     TEXT,
            product_name    TEXT,
            variant_id      TEXT,
            variant_title   TEXT,
            sku             TEXT,
            price           TEXT,
            inventory_quantity INTEGER,
            available       INTEGER,
            timestamp       TEXT
        )
    """)
    conn.commit()
    conn.close()


# -------------------------------------------------------
# SHOPIFY — obtener todos los productos via /products.json
# -------------------------------------------------------
def shopify_get_all_products(base_url: str) -> list:
    """Descarga todos los productos usando el endpoint público de Shopify."""
    all_products = []
    page = 1
    limit = 250

    while True:
        url = f"{base_url}/products.json?page={page}&limit={limit}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException as e:
            print(f"    ⚠️  Error de red en página {page}: {e}")
            break

        if resp.status_code != 200:
            print(f"    ⚠️  HTTP {resp.status_code} en {url}")
            break

        data = resp.json()
        products = data.get("products", [])
        if not products:
            break

        all_products.extend(products)
        print(f"    Página {page}: {len(products)} productos")
        page += 1
        time.sleep(0.6)

    return all_products


def shopify_extract_inventory(base_url: str, product: dict) -> list:
    """
    Extrae inventario de una página de producto Shopify.
    Intenta dos métodos:
      1. Script tag 'data-product-inventory-json'  (igual que tu scraper de lebump)
      2. Variantes directas desde /products/<handle>.json
    """
    handle = product.get("handle", "")
    product_url = f"{base_url}/products/{handle}"
    rows = []

    # --- Método 1: JSON de inventario en el HTML ---
    try:
        resp = requests.get(product_url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            script_tag = soup.find(
                "script",
                {"type": "application/json", "data-product-inventory-json": True},
            )
            if script_tag:
                inv_data = json.loads(script_tag.string)
                for variant_id, val in inv_data.get("inventory", {}).items():
                    rows.append({
                        "product_url": product_url,
                        "product_name": handle,
                        "variant_id": variant_id,
                        "variant_title": "",
                        "sku": "",
                        "price": "",
                        "inventory_quantity": val.get("inventory_quantity", 0),
                        "available": int(val.get("inventory_quantity", 0) > 0),
                    })
                if rows:
                    return rows
    except Exception as e:
        print(f"      ⚠️  Método 1 falló para {handle}: {e}")

    # --- Método 2: variantes del producto desde /products/<handle>.json ---
    try:
        json_url = f"{base_url}/products/{handle}.json"
        resp2 = requests.get(json_url, headers=HEADERS, timeout=15)
        if resp2.status_code == 200:
            p = resp2.json().get("product", {})
            for v in p.get("variants", []):
                rows.append({
                    "product_url": product_url,
                    "product_name": handle,
                    "variant_id": str(v.get("id", "")),
                    "variant_title": v.get("title", ""),
                    "sku": v.get("sku", ""),
                    "price": v.get("price", ""),
                    "inventory_quantity": v.get("inventory_quantity", 0),
                    "available": int(v.get("available", False)),
                })
    except Exception as e:
        print(f"      ⚠️  Método 2 falló para {handle}: {e}")

    return rows


def scrape_shopify(store: dict) -> pd.DataFrame:
    """Scraper completo para una tienda Shopify."""
    name = store["name"]
    base_url = store["base_url"]
    print(f"\n🛍️  [{name}] Obteniendo productos Shopify de {base_url}")

    products = shopify_get_all_products(base_url)
    print(f"  Total productos: {len(products)}")

    if not products:
        print(f"  ⛔ Sin productos — verifica que {base_url} sea Shopify")
        return pd.DataFrame()

    all_rows = []
    for i, product in enumerate(products):
        print(f"  [{i+1}/{len(products)}] {product.get('handle', '')}")
        rows = shopify_extract_inventory(base_url, product)
        for r in rows:
            r["tienda"] = name
        all_rows.extend(rows)
        time.sleep(0.5)

    df = pd.DataFrame(all_rows)
    df["timestamp"] = datetime.now().isoformat()
    return df


# -------------------------------------------------------
# DETECCIÓN AUTOMÁTICA DE PLATAFORMA
# (útil si no estás seguro de que el sitio es Shopify)
# -------------------------------------------------------
def detect_platform(base_url: str) -> str:
    """Detecta si el sitio es Shopify, WooCommerce u otro."""
    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=15)
        html = resp.text.lower()

        if "shopify" in html or "cdn.shopify" in html:
            return "shopify"
        if "woocommerce" in html or "wp-content" in html:
            return "woocommerce"

        # Probar endpoint Shopify directamente
        r2 = requests.get(
            f"{base_url}/products.json?limit=1", headers=HEADERS, timeout=10
        )
        if r2.status_code == 200:
            d = r2.json()
            if "products" in d:
                return "shopify"
    except Exception:
        pass

    return "unknown"


# -------------------------------------------------------
# FUNCIÓN PRINCIPAL
# -------------------------------------------------------
def main():
    init_db()
    all_dfs = []

    for store in STORES:
        platform = store.get("platform", "unknown")

        # Si no se especificó plataforma, detectar automáticamente
        if platform == "unknown":
            print(f"\n🔍 Detectando plataforma de {store['base_url']}...")
            platform = detect_platform(store["base_url"])
            print(f"  → {platform}")

        if platform == "shopify":
            df = scrape_shopify(store)
            if not df.empty:
                all_dfs.append(df)
        else:
            print(
                f"\n⚠️  [{store['name']}] Plataforma '{platform}' no soportada aún. "
                "Cambia 'platform' en STORES o implementa el scraper correspondiente."
            )

    if all_dfs:
        df_final = pd.concat(all_dfs, ignore_index=True)
        save_to_db(df_final)
        print(f"\n✅ Scraping completado. Total filas: {len(df_final)}")
    else:
        print("\n⚠️  No se obtuvo ningún dato.")


if __name__ == "__main__":
    main()
