"""Configuration and seed data. The live data now lives in SQLite (see store.py);
these dicts are only used to SEED a new database."""

# sku -> (starting stock, unit price in USD)
SEED_ITEMS = {
    "wireless_mouse":      (42, 25.00),
    "mechanical_keyboard": (3, 120.00),
    "usb_c_hub":           (0, 40.00),
    "laptop":              (5, 1200.00),
    "monitor":             (10, 300.00),
}

# Kept for backward compatibility with jury-1 code/tests: sku -> stock
INVENTORY_DB = {sku: stock for sku, (stock, _) in SEED_ITEMS.items()}

# Orders whose GOODS value (qty * unit price, shipping excluded) is >= this need a human.
APPROVAL_THRESHOLD = 500.00
