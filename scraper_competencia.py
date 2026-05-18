import requests
from bs4 import BeautifulSoup
import json
import sqlite3
import pandas as pd
from datetime import datetime
import time

print("🚀 Scraper de competencia iniciado")

# =========================================================

# CONFIGURACIÓN TIENDAS

# =========================================================

STORES = [

```
{
    "name": "lebump",
    "base_url": "https://lebump.mx",
    "inventory": "inventory_json",
},

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
```

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

# =========================================================

# BASE DE DATOS

# =========================================================

def init_db():

```
conn = sqlite3.connect(DB_FILE)

conn.execute("""
    CREATE TABLE IF NOT EXISTS inventario (

        tienda                 TEXT,
        product_url            TEXT,
        product_name           TEXT,
        handle                 TEXT,

        variant_id             TEXT,
        variant_title          TEXT,

        sku                    TEXT,

        vendor                 TEXT,
        product_type           TEXT,
        tags                   TEXT,

        price                  TEXT,
        compare_at_price       TEXT,

        inventory_quantity     INTEGER,
        inventory_message      TEXT,

        available              INTEGER,

        image                  TEXT,

        timestamp              TEXT
    )
""")

conn.commit()
conn.close()
```

def save_to_db(df: pd.DataFrame):

```
conn = sqlite3.connect(DB_FILE)

df.to_sql(
    "inventario",
    conn,
    if_exists="append",
    index=False
)

conn.close()

print(f"\n💾 {len(df)} filas guardadas")
```

# =========================================================

# PRODUCTS.JSON

# =========================================================

def get_all_products(base_url: str):

```
all_products = []

page = 1

while True:

    url = f"{base_url}/products.json?page={page}&limit=250"

    try:

        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

    except requests.RequestException as e:

        print(f"⚠️ Error de red: {e}")
        break

    if resp.status_code != 200:

        print(f"⚠️ HTTP {resp.status_code}")
        break

    data = resp.json()

    products = data.get("products", [])

    if not products:
        break

    all_products.extend(products)

    print(f"    Página {page}: {len(products)} productos")

    page += 1

    time.sleep(0.5)

return all_products
```

# =========================================================

# MÉTODO A

# inventory_json (LEBUMP STYLE)

# =========================================================

def extract_inventory_json(base_url: str, product: dict):

```
handle = product["handle"]

product_url = f"{base_url}/products/{handle}"

rows = []

try:

    resp = requests.get(
        product_url,
        headers=HEADERS,
        timeout=20
    )

    if resp.status_code != 200:
        return rows

    soup = BeautifulSoup(resp.text, "html.parser")

    # SELECTOR ROBUSTO
    script_tag = soup.select_one(
        'script[data-product-inventory-json]'
    )

    if not script_tag:

        print(f"      ⚠️ inventory_json no encontrado")
        return rows

    script_content = script_tag.get_text(strip=True)

    inv_data = json.loads(script_content)

    inventory = inv_data.get("inventory", {})

    for variant_id, val in inventory.items():

        qty = val.get("inventory_quantity", 0)

        rows.append({

            "variant_id": str(variant_id),

            "variant_title": "",
            "sku": "",

            "price": "",
            "compare_at_price": "",

            "inventory_quantity": qty,

            "inventory_message":
                val.get("inventory_message", ""),

            "available": int(qty > 0),
        })

except Exception as e:

    print(f"      ⚠️ extract_inventory_json falló ({handle}): {e}")

return rows
```

# =========================================================

# MÉTODO B

# data attribute inventory

# =========================================================

def extract_data_attribute(base_url: str, product: dict):

```
handle = product["handle"]

product_url = f"{base_url}/products/{handle}"

rows = []

try:

    resp = requests.get(
        product_url,
        headers=HEADERS,
        timeout=20
    )

    if resp.status_code != 200:
        return rows

    soup = BeautifulSoup(resp.text, "html.parser")

    elements = soup.find_all(
        attrs={"data-inventoryquantity": True}
    )

    for el in elements:

        qty = int(
            el.get("data-inventoryquantity", 0) or 0
        )

        rows.append({

            "variant_id":
                str(el.get("data-variant-id", "")),

            "variant_title":
                el.get("data-variant-title", ""),

            "sku":
                el.get("data-sku", ""),

            "price":
                el.get("data-price", ""),

            "compare_at_price": "",

            "inventory_quantity": qty,

            "inventory_message": "",

            "available": int(qty > 0),
        })

except Exception as e:

    print(f"      ⚠️ extract_data_attribute falló ({handle}): {e}")

return rows
```

# =========================================================

# MÉTODO C

# SOLO AVAILABLE TRUE/FALSE

# =========================================================

def extract_variant_available(product: dict):

```
rows = []

for v in product.get("variants", []):

    rows.append({

        "variant_id":
            str(v.get("id", "")),

        "variant_title":
            v.get("title", ""),

        "sku":
            v.get("sku", ""),

        "price":
            str(v.get("price", "")),

        "compare_at_price":
            str(v.get("compare_at_price", "")),

        "inventory_quantity": None,

        "inventory_message": "",

        "available":
            int(v.get("available", False)),
    })

return rows
```

# =========================================================

# SCRAPER PRINCIPAL

# =========================================================

def scrape_store(store: dict):

```
name = store["name"]

base_url = store["base_url"]

method = store["inventory"]

print(f"\n🛍️ {name}")
print(f"🌐 {base_url}")
print(f"📦 método: {method}")

products = get_all_products(base_url)

print(f"✅ Total productos: {len(products)}")

all_rows = []

for i, product in enumerate(products):

    handle = product.get("handle", "")

    print(f"  [{i+1}/{len(products)}] {handle}")

    # =================================================
    # INVENTORY
    # =================================================
    if method == "inventory_json":

        rows = extract_inventory_json(
            base_url,
            product
        )

    elif method == "data_attribute":

        rows = extract_data_attribute(
            base_url,
            product
        )

    else:

        rows = extract_variant_available(product)

    # =================================================
    # METADATA PRODUCTO
    # =================================================
    for r in rows:

        r["tienda"] = name

        r["product_url"] = (
            f"{base_url}/products/{handle}"
        )

        r["product_name"] = product.get(
            "title",
            handle
        )

        r["handle"] = handle

        r["vendor"] = product.get("vendor", "")

        r["product_type"] = product.get(
            "product_type",
            ""
        )

        r["tags"] = ",".join(
            product.get("tags", [])
        ) if isinstance(
            product.get("tags"),
            list
        ) else str(product.get("tags", ""))

        r["image"] = ""

        if product.get("images"):

            first_image = product["images"][0]

            if isinstance(first_image, dict):

                r["image"] = first_image.get("src", "")

            else:

                r["image"] = str(first_image)

    all_rows.extend(rows)

    if method in (
        "inventory_json",
        "data_attribute",
    ):
        time.sleep(0.4)

df = pd.DataFrame(all_rows)

df["timestamp"] = datetime.now().isoformat()

return df
```

# =========================================================

# MAIN

# =========================================================

def main():

```
init_db()

all_dfs = []

for store in STORES:

    try:

        df = scrape_store(store)

        if not df.empty:
            all_dfs.append(df)

    except Exception as e:

        print(f"\n❌ ERROR tienda {store['name']}: {e}")

if all_dfs:

    df_final = pd.concat(
        all_dfs,
        ignore_index=True
    )

    save_to_db(df_final)

    print("\n✅ SCRAPING COMPLETADO")

    print(df_final.head())

else:

    print("\n⚠️ No se obtuvo información")
```

if **name** == "**main**":
main()
