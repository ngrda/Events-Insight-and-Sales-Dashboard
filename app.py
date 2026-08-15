from flask import Flask, jsonify, send_from_directory, request, Response
from flask_cors import CORS
import pandas as pd
import os
import re
import io
import json
from datetime import datetime

app = Flask(__name__, static_folder=".")
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Two tiers of data:
#  - uploaded_data/  : whatever the visitor drags/drops into the UI this run.
#  - default_data/   : a bundled sample dataset shipped with the app, used
#    only as a fallback so a first-time visitor who doesn't want to attach
#    their own CSVs still sees a working dashboard instead of an empty state.
# Every route reads through active_csv_path() below, which prefers the
# uploaded file and falls back to the sample one.
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_data")
DEFAULT_DIR = os.path.join(BASE_DIR, "data")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
GLOBAL_CSV = os.path.join(UPLOAD_DIR, "mlm_global.csv")
INDI_CSV = os.path.join(UPLOAD_DIR, "mlm_indi.csv")
DEFAULT_GLOBAL_CSV = os.path.join(DEFAULT_DIR, "mlm_global.csv")
DEFAULT_INDI_CSV = os.path.join(DEFAULT_DIR, "mlm_indi.csv")

os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Every time the server (re)starts, wipe any CSVs left over from a previous
# run - the user must drag in fresh files each run rather than silently
# picking up whatever was uploaded last time. This does NOT touch
# default_data/, which is a static asset shipped with the app, not something
# a visitor uploaded.
for _stale_path in (GLOBAL_CSV, INDI_CSV):
    if os.path.exists(_stale_path):
        os.remove(_stale_path)


def is_using_default(kind):
    """True if this dataset is currently falling back to the bundled sample
    (i.e. the visitor hasn't uploaded their own file for it yet)."""
    uploaded = GLOBAL_CSV if kind == "global" else INDI_CSV
    return not os.path.exists(uploaded)


def active_csv_path(kind):
    """Path to actually read for this dataset: the visitor's own upload if
    present, otherwise the bundled sample so the dashboard always has
    something to show."""
    uploaded = GLOBAL_CSV if kind == "global" else INDI_CSV
    default = DEFAULT_GLOBAL_CSV if kind == "global" else DEFAULT_INDI_CSV
    return uploaded if os.path.exists(uploaded) else default


class DataNotAvailable(Exception):
    """Raised anywhere a route needs the global or individual CSV before the
    user has uploaded it. Caught by a single error handler below so every
    route - not just the ones with an explicit check - fails the same clean
    way instead of a raw 500 traceback."""
    pass


@app.errorhandler(DataNotAvailable)
def handle_data_not_available(err):
    return jsonify({"error": str(err)}), 404


def clean_columns(df):
    df.columns = [re.sub(r"[\s\u00a0\u00ca\u00c2]+", " ", col).strip() for col in df.columns]
    return df


# Columns on the global sheet that are always fixed metrics/metadata, never
# swept into the dynamic "others" sub-categories below. Each is optional -
# if a week's export is missing one, to_float()/`.get(..., 0)` default it to
# 0 rather than erroring.
FIXED_GLOBAL_COLUMNS = {
    "Day", "Attendance", "Total Sales", "Net Sales",
    "Polly's Total Sales", "Pioneer Total Sales",
    "Polly's Sales", "Pioneer Sales",
    "Popcorn", "Popcorn Sales",
    "Snowcones", "Snowcones Sales",
    "Temperature", "Category",
}


def normalize_key(name):
    """Collapse a column name to bare alphanumerics so a units column can be
    matched to its revenue column regardless of casing, hyphens, apostrophes,
    or stray whitespace (e.g. 'Pop-A-Shot Sales' <-> 'Pop-a-shot')."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def split_sale_suffix(name):
    """If a column name ends in 'Sale'/'Sales', it's a revenue column -
    return (base_name, True). Otherwise it's a units column - (name, False)."""
    m = re.match(r"^(.*?)\s+sales?$", name.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip(), True
    return name.strip(), False


def discover_dynamic_categories(columns):
    """Any global-sheet column that isn't on the fixed list and isn't the
    'Others' $ total itself is a dynamic sub-category (Chairs, Candy, or
    whatever new item shows up in a future week's export). Columns are
    paired up - a unit-count column with its matching Sale/Sales column -
    by normalized base name, so no category name is ever hardcoded. If a
    category only has one side (e.g. a units column with no matching sales
    column), it still shows up with the missing side defaulting to 0 rather
    than being silently dropped. Order follows first appearance in the CSV.
    """
    leftover = [c for c in columns if c not in FIXED_GLOBAL_COLUMNS and c not in ("Others", "_id")]
    order = []
    pairs = {}
    for col in leftover:
        base, is_sales = split_sale_suffix(col)
        key = normalize_key(base)
        if key not in pairs:
            pairs[key] = {"key": key, "label": base, "units_col": None, "sales_col": None}
            order.append(key)
        if is_sales:
            pairs[key]["sales_col"] = col
        else:
            pairs[key]["units_col"] = col
            pairs[key]["label"] = base  # prefer the units-column's casing for display
    return [pairs[k] for k in order]


def format_day(day_value):
    return str(day_value).split(" ")[0].strip()


def is_valid_day(day_value):
    """A row only counts as a real week if Day is an actual d/m/y date -
    blank rows, stray junk rows, or malformed dates are not weeks."""
    try:
        datetime.strptime(format_day(day_value), "%d/%m/%y")
        return True
    except (ValueError, TypeError):
        return False


def load_csv(path):
    if not os.path.exists(path):
        kind = "Global" if path in (GLOBAL_CSV, DEFAULT_GLOBAL_CSV) else "Individual products"
        raise DataNotAvailable(f"{kind} CSV has not been uploaded yet")
    df = pd.read_csv(path, sep=";", encoding="latin-1")
    df = clean_columns(df)
    if "Day" not in df.columns:
        kind = "Global" if path in (GLOBAL_CSV, DEFAULT_GLOBAL_CSV) else "Individual products"
        raise DataNotAvailable(f"{kind} CSV is missing a 'Day' column - check the file and re-upload")
    # Drop any row that doesn't have a real, parseable date in Day (e.g.
    # trailing blank lines some spreadsheet exports leave at the end of the
    # file) - a row with no valid date is not a week.
    df = df[df["Day"].apply(is_valid_day)]
    df = df.reset_index(drop=True)
    return df.fillna(0)


def to_float(value, default=0.0):
    """Parse a numeric CSV cell that may use a comma as the decimal
    separator (e.g. '0,00') instead of crashing on it."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return default


def day_to_id(day_value):
    return format_day(day_value).replace("/", "-")


def parse_day(day_str):
    try:
        return datetime.strptime(format_day(day_str), "%d/%m/%y")
    except ValueError:
        return None


def week_label(day_str, index):
    dt = parse_day(day_str)
    if dt:
        return f"Week {index + 1} · {dt.strftime('%b %d, %Y')}"
    return f"Week {index + 1} · {format_day(day_str)}"


def growth_pct(current, previous):
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return round(((current - previous) / previous) * 100, 1)


def load_merged():
    global_df = load_csv(active_csv_path("global"))
    indi_df = load_csv(active_csv_path("individual"))

    dynamic_cats = discover_dynamic_categories(global_df.columns)

    global_df["_id"] = global_df["Day"].apply(day_to_id)
    indi_df["_id"] = indi_df["Day"].apply(day_to_id)

    return global_df, indi_df, dynamic_cats


def resolve_brand_figures(global_row, indi_row, dynamic_cats):
    """Real per-brand units + revenue for the week, filling in a brand's
    numbers if its 'Total Sales'/'Sales' columns are blank in the global
    sheet. fillna(0) leaves no way to tell "blank cell" from "genuinely sold
    zero", so we treat "reported units column is 0 but the individual-flavor
    sheet shows real units sold" as evidence the cell was blank, not a
    zero-sales week.

    Units always come from the individual-flavor sheet (mlm_indi.csv) when
    it has any - that number is real regardless of what the global sheet
    says. Revenue for a missing brand is backed out algebraically from Net
    Sales, since:
        Net Sales = Popcorn + Snowcones + Polly + Pioneer + Others
    so if every other component is known, the missing one is just:
        missing_revenue = Net Sales - (every other known component)
    This only works when exactly ONE brand is missing that week - if both
    are missing there's no way to know how to split the remainder between
    them, so we fall back to the sheet's reported (0) values rather than
    guess a split.
    """
    product_cols = [c for c in indi_row.index if c not in ("Day", "_id")]
    polly_units_by_name = {n: int(indi_row[n]) for n in product_cols if n.startswith("Polly")}
    pioneer_units_by_name = {n: int(indi_row[n]) for n in product_cols if n.startswith("Pioneer")}
    polly_units_actual = sum(polly_units_by_name.values())
    pioneer_units_actual = sum(pioneer_units_by_name.values())

    polly_units_reported = to_float(global_row.get("Polly's Total Sales", 0))
    pioneer_units_reported = to_float(global_row.get("Pioneer Total Sales", 0))
    polly_revenue_reported = round(to_float(global_row.get("Polly's Sales", 0)), 2)
    pioneer_revenue_reported = round(to_float(global_row.get("Pioneer Sales", 0)), 2)

    polly_missing = polly_units_reported == 0 and polly_units_actual > 0
    pioneer_missing = pioneer_units_reported == 0 and pioneer_units_actual > 0

    popcorn_revenue = round(to_float(global_row.get("Popcorn Sales", 0)), 2)
    snowcone_revenue = round(to_float(global_row.get("Snowcones Sales", 0)), 2)
    others_revenue_total = round(
        sum(to_float(global_row.get(cat["sales_col"], 0)) for cat in dynamic_cats if cat["sales_col"]), 2
    )
    net_sales = to_float(global_row.get("Net Sales", 0))

    polly_units = polly_units_actual if polly_units_actual else polly_units_reported
    pioneer_units = pioneer_units_actual if pioneer_units_actual else pioneer_units_reported
    polly_revenue = polly_revenue_reported
    pioneer_revenue = pioneer_revenue_reported
    inferred = None

    if polly_missing and not pioneer_missing:
        polly_revenue = round(
            net_sales - (popcorn_revenue + snowcone_revenue + pioneer_revenue_reported + others_revenue_total), 2
        )
        inferred = "polly"
    elif pioneer_missing and not polly_missing:
        pioneer_revenue = round(
            net_sales - (popcorn_revenue + snowcone_revenue + polly_revenue_reported + others_revenue_total), 2
        )
        inferred = "pioneer"

    return {
        "polly_units": polly_units,
        "polly_revenue": polly_revenue,
        "pioneer_units": pioneer_units,
        "pioneer_revenue": pioneer_revenue,
        "polly_units_by_name": polly_units_by_name,
        "pioneer_units_by_name": pioneer_units_by_name,
        "inferred": inferred,
    }


def brand_avg_prices(polly_units, polly_revenue, pioneer_units, pioneer_revenue):
    """Average price per unit for each brand from its (possibly inferred,
    see resolve_brand_figures) units + revenue. If a brand sold zero units
    that week there is no real price to derive, so we return 0 instead of
    inventing a number (units are 0 anyway, so revenue = units * price is
    unaffected)."""
    polly_price = round(polly_revenue / polly_units, 2) if polly_units else 0.0
    pioneer_price = round(pioneer_revenue / pioneer_units, 2) if pioneer_units else 0.0
    return polly_price, pioneer_price


def distribute_revenue(units_by_name, total_revenue):
    """Split a brand's real $ revenue for the week across its individual
    flavors in proportion to units sold, using the largest-remainder method
    so the per-flavor figures always sum EXACTLY to the real revenue column
    (to the cent) - unlike a flat units * avg_price estimate, which drifts
    a few cents once a rounded price is multiplied out across many flavors
    and summed back up. That drift was why per-product revenue totals
    (Top Products, Products page) didn't match the week's real revenue.
    Returns {name: revenue} covering every key in units_by_name."""
    total_units = sum(units_by_name.values())
    total_cents = round(total_revenue * 100)
    if total_units <= 0 or total_cents == 0:
        return {name: 0.0 for name in units_by_name}

    raw_shares = {name: (units / total_units) * total_cents for name, units in units_by_name.items()}
    floor_cents = {name: int(share) for name, share in raw_shares.items()}
    remainder = int(round(total_cents - sum(floor_cents.values())))

    # Hand out the leftover pennies to whichever flavors had the largest
    # fractional remainder, so the total lands exactly on total_revenue.
    order = sorted(units_by_name.keys(), key=lambda n: (raw_shares[n] - floor_cents[n]), reverse=True)
    for name in order[:remainder]:
        floor_cents[name] += 1

    return {name: round(cents / 100, 2) for name, cents in floor_cents.items()}


def build_top_products(global_row, indi_row, dynamic_cats):
    products = []
    product_cols = [c for c in indi_row.index if c not in ("Day", "_id")]
    figures = resolve_brand_figures(global_row, indi_row, dynamic_cats)
    polly_price, pioneer_price = brand_avg_prices(
        figures["polly_units"], figures["polly_revenue"], figures["pioneer_units"], figures["pioneer_revenue"]
    )

    polly_revenue_by_name = distribute_revenue(figures["polly_units_by_name"], figures["polly_revenue"])
    pioneer_revenue_by_name = distribute_revenue(figures["pioneer_units_by_name"], figures["pioneer_revenue"])

    for name in product_cols:
        units = int(indi_row[name])
        is_polly = name.startswith("Polly")
        brand = "Polly's Pop" if is_polly else "Pioneer"
        clean_name = re.sub(r"^(Polly|Pioneer)\s+", "", name).strip()
        avg_price = polly_price if is_polly else pioneer_price
        revenue = (polly_revenue_by_name if is_polly else pioneer_revenue_by_name)[name]
        products.append({
            "name": f"{brand} {clean_name}",
            "units": units,
            "price": round(avg_price, 2),
            "revenue": revenue,
            "category": "soda",
            "revenue_estimated": figures["inferred"] == ("polly" if is_polly else "pioneer"),
        })

    # Only beverages (soda) are shown in the Top Selling Products list.
    # Popcorn/Snowcones still count toward revenue mix and delivery totals elsewhere.
    return sorted(products, key=lambda p: p["units"], reverse=True)


def build_week_payload(global_row, indi_row, index, dynamic_cats, prev_global_row=None):
    revenue = to_float(global_row["Net Sales"])
    prev_revenue = to_float(prev_global_row["Net Sales"]) if prev_global_row is not None else 0

    popcorn_units = int(to_float(global_row["Popcorn"]))
    snowcone_units = int(to_float(global_row["Snowcones"]))

    # Real per-brand units + revenue, with a missing brand's revenue backed
    # out from Net Sales when the global sheet has a blank cell for it (see
    # resolve_brand_figures docstring).
    brand_figures = resolve_brand_figures(global_row, indi_row, dynamic_cats)
    polly_units = brand_figures["polly_units"]
    pioneer_units = brand_figures["pioneer_units"]

    # Real unit counts and $ revenue for every dynamic "others" sub-category
    # (Chairs, Pop-a-shot, Raffle Tickets, Nee-Dohs, Candy, or whatever else
    # shows up in this dataset's columns), straight from each one's own
    # dedicated units/sales column pair - NOT the "Others" $ total column,
    # which is just a reported grand total we reconcile against below.
    others_units = {}
    others_breakdown = {}
    for cat in dynamic_cats:
        units_val = int(to_float(global_row.get(cat["units_col"], 0))) if cat["units_col"] else 0
        sales_val = round(to_float(global_row.get(cat["sales_col"], 0)), 2) if cat["sales_col"] else 0.0
        others_units[cat["key"]] = units_val
        others_breakdown[cat["key"]] = sales_val

    others_units_total = sum(others_units.values())
    others_revenue_total = round(sum(others_breakdown.values()), 2)

    # Reconciliation check: the source "Others" column is a reported $ total -
    # compare it to what our dynamic sub-categories actually sum to, and flag
    # any mismatch instead of silently trusting either number.
    reported_others_total = round(to_float(global_row.get("Others", 0)), 2)
    others_check_diff = round(reported_others_total - others_revenue_total, 2)

    mix = {
        "popcorn": popcorn_units,
        "snowcones": snowcone_units,
        "polly": polly_units,
        "pioneer": pioneer_units,
        "others": others_units_total,
    }
    mix_total = sum(mix.values())
    mix_pct = {k: round((v / mix_total) * 100, 1) if mix_total else 0 for k, v in mix.items()}

    top_products = build_top_products(global_row, indi_row, dynamic_cats)
    soda_total = sum(p["units"] for p in top_products)  # sodas only (Polly's + Pioneer)
    product_units = int(to_float(global_row["Total Sales"]))  # kept equal to total_orders, same number

    others_labels = [cat["label"] for cat in dynamic_cats]
    others_values = [others_breakdown[cat["key"]] for cat in dynamic_cats]
    # Real unit counts aligned to others_labels order (for the units chart).
    others_units_list = [others_units[cat["key"]] for cat in dynamic_cats]

    # Real dollar revenue for Polly's Pop / Pioneer straight from the sales
    # columns - unless one of them was blank in the source sheet, in which
    # case brand_figures already backed it out from Net Sales (see
    # resolve_brand_figures).
    polly_revenue = round(brand_figures["polly_revenue"], 2)
    pioneer_revenue = round(brand_figures["pioneer_revenue"], 2)

    # Popcorn & Snowcones DO have dedicated $ columns in the source data
    # ("Popcorn Sales", "Snowcones Sales") - read them directly instead of
    # inventing a split from a computed remainder.
    popcorn_revenue = round(to_float(global_row.get("Popcorn Sales", 0)), 2)
    snowcone_revenue = round(to_float(global_row.get("Snowcones Sales", 0)), 2)

    mix_revenue = {
        "popcorn": popcorn_revenue,
        "snowcones": snowcone_revenue,
        "polly": polly_revenue,
        "pioneer": pioneer_revenue,
        "others": others_revenue_total,
    }

    combined_labels = ["Popcorn", "Snowcones", "Polly's Pop", "Pioneer"] + others_labels
    combined_values = [mix_revenue["popcorn"], mix_revenue["snowcones"], mix_revenue["polly"], mix_revenue["pioneer"]] + others_values
    # Units aligned to the same combined_labels order (revenue and unit views share one legend).
    combined_units = [mix["popcorn"], mix["snowcones"], mix["polly"], mix["pioneer"]] + others_units_list

    day = format_day(global_row["Day"])
    category = str(global_row.get("Category", "")).strip()
    raw_temperature = str(global_row.get("Temperature", "")).strip()
    temp_match = re.search(r"-?\d+(\.\d+)?", raw_temperature)
    temperature = f"{temp_match.group()}°F" if temp_match else ""
    attendance = int(to_float(global_row["Attendance"]))
    avg_spend = round(revenue / attendance, 2) if attendance else 0.0

    return {
        "id": global_row["_id"],
        "label": week_label(global_row["Day"], index),
        "date": day,
        "category": category,
        "temperature": temperature,
        "metrics": {
            "total_revenue": round(revenue, 2),
            "revenue_growth": growth_pct(revenue, prev_revenue),
            "previous_week_revenue": round(prev_revenue, 2),
            "total_orders": int(to_float(global_row["Total Sales"])),
            "product_units": product_units,
            "soda_total": soda_total,
            "total_customers": attendance,
            "total_deliveries": int(to_float(global_row["Popcorn"])) + int(to_float(global_row["Snowcones"])),
            "total_popcorn": int(to_float(global_row["Popcorn"])),
            "total_snowcones": int(to_float(global_row["Snowcones"])),
            "avg_spend_per_attendee": avg_spend,
        },
        "breakdown": mix,
        "breakdown_pct": mix_pct,
        "breakdown_revenue": mix_revenue,
        "others_breakdown": others_breakdown,
        "others_units": others_units,
        "others_categories": dynamic_cats,  # [{key, label, units_col, sales_col}] - same set for every week in this dataset
        "others_check": {
            "reported_total": reported_others_total,
            "computed_total": others_revenue_total,
            "diff": others_check_diff,
        },
        "brand_revenue_estimated": brand_figures["inferred"],  # "polly", "pioneer", or None
        "top_products": top_products,
        "charts": {
            "labels": ["Popcorn", "Snowcones", "Polly's Pop", "Pioneer", "Others"],
            "values": [mix["popcorn"], mix["snowcones"], mix["polly"], mix["pioneer"], mix["others"]],
            "revenue_values": [mix_revenue["popcorn"], mix_revenue["snowcones"], mix_revenue["polly"], mix_revenue["pioneer"], mix_revenue["others"]],
            "others_labels": others_labels,
            "others_values": others_values,
            "combined_labels": combined_labels,
            "combined_values": combined_values,
            "combined_units": combined_units,
        },
        "raw": {
            "global": {k: (float(v) if isinstance(v, (int, float)) else str(v)) for k, v in global_row.items() if k != "_id"},
            "products": {k: int(v) for k, v in indi_row.items() if k not in ("Day", "_id")},
        },
    }


def get_all_weeks():
    global_df, indi_df, dynamic_cats = load_merged()
    weeks = []
    product_cols = [c for c in indi_df.columns if c not in ("Day", "_id")]

    for i, (_, grow) in enumerate(global_df.iterrows()):
        prev = global_df.iloc[i - 1] if i > 0 else None
        indi_match = indi_df[indi_df["_id"] == grow["_id"]]
        if indi_match.empty:
            # No soda-flavor row for this week in mlm_indi.csv - use zeros for
            # the soda breakdown only, but still keep this week's real data
            # (Popcorn, Snowcones, and every dynamic "others" sub-category all
            # come from mlm_global.csv and must not be dropped just because
            # the separate soda-flavor file is missing this day).
            indi_row = pd.Series({c: 0 for c in product_cols})
        else:
            indi_row = indi_match.iloc[0]
        weeks.append(build_week_payload(grow, indi_row, i, dynamic_cats, prev))

    return weeks


def build_products_catalog(scope_week_id=None):
    global_df, indi_df, dynamic_cats = load_merged()
    weeks_meta = []

    for i, (_, grow) in enumerate(global_df.iterrows()):
        indi_row = indi_df[indi_df["_id"] == grow["_id"]]
        if indi_row.empty:
            continue
        weeks_meta.append({
            "id": grow["_id"],
            "label": week_label(grow["Day"], i).split(" · ")[0],
            "date": format_day(grow["Day"]),
            "index": i,
        })

    if scope_week_id:
        weeks_meta = [w for w in weeks_meta if w["id"] == scope_week_id]

    product_cols = [c for c in indi_df.columns if c not in ("Day", "_id")]
    catalog = {}

    for wm in weeks_meta:
        grow = global_df[global_df["_id"] == wm["id"]].iloc[0]
        indi_row = indi_df[indi_df["_id"] == wm["id"]].iloc[0]
        figures = resolve_brand_figures(grow, indi_row, dynamic_cats)
        polly_price, pioneer_price = brand_avg_prices(
            figures["polly_units"], figures["polly_revenue"], figures["pioneer_units"], figures["pioneer_revenue"]
        )

        polly_units_by_name = figures["polly_units_by_name"]
        pioneer_units_by_name = figures["pioneer_units_by_name"]
        polly_revenue_by_name = distribute_revenue(polly_units_by_name, figures["polly_revenue"])
        pioneer_revenue_by_name = distribute_revenue(pioneer_units_by_name, figures["pioneer_revenue"])

        for name in product_cols:
            units = int(indi_row[name])
            is_polly = name.startswith("Polly")
            brand = "Polly's Pop" if is_polly else "Pioneer"
            clean_name = re.sub(r"^(Polly|Pioneer)\s+", "", name).strip()
            display_name = f"{brand} {clean_name}"
            price = polly_price if is_polly else pioneer_price
            week_revenue = (polly_revenue_by_name if is_polly else pioneer_revenue_by_name)[name]

            entry = catalog.setdefault(display_name, {
                "name": display_name,
                "brand": brand,
                "category": "soda",
                "price": price,
                "units": 0,
                "revenue": 0.0,
                "weekly": [],
            })
            entry["units"] += units
            entry["revenue"] += week_revenue
            entry["weekly"].append({
                "week_id": wm["id"],
                "week_label": wm["label"],
                "date": wm["date"],
                "units": units,
                "revenue": week_revenue,
            })

    products = []
    for entry in catalog.values():
        entry["revenue"] = round(entry["revenue"], 2)
        if entry["units"] > 0:
            entry["price"] = round(entry["revenue"] / entry["units"], 2)
        best = max(entry["weekly"], key=lambda w: w["units"]) if entry["weekly"] else None
        entry["best_week"] = best
        products.append(entry)

    products.sort(key=lambda p: p["units"], reverse=True)
    return products, weeks_meta


def build_weekly_detail():
    weeks = get_all_weeks()
    return [{
        "id": w["id"],
        "label": w["label"].split(" · ")[0],
        "date": w["date"],
        "category": w["category"],
        "revenue": w["metrics"]["total_revenue"],
        "orders": w["metrics"]["total_orders"],
        "customers": w["metrics"]["total_customers"],
        "deliveries": w["metrics"]["total_deliveries"],
        "product_units": w["metrics"]["product_units"],
        "avg_spend": w["metrics"]["avg_spend_per_attendee"],
        "popcorn": w["metrics"]["total_popcorn"],
        "snowcones": w["metrics"]["total_snowcones"],
        # Dynamic "others" sub-categories (Chairs, Candy, whatever else the
        # CSV has this dataset), keyed by normalized category key.
        "others_units": w["others_units"],
        "others_revenue": w["others_breakdown"],
        "others_total": round(sum(w["others_breakdown"].values()), 2),
    } for w in weeks]



def build_soda_products(weeks):
    """Aggregate soda flavors only (Polly's + Pioneer) across a list of weeks."""
    totals = {}
    for w in weeks:
        for p in w["top_products"]:
            entry = totals.setdefault(p["name"], {
                "name": p["name"],
                "units": 0,
                "revenue": 0.0,
                "category": p["category"],
            })
            entry["units"] += p["units"]
            entry["revenue"] += p["revenue"]

    result = sorted(totals.values(), key=lambda p: p["revenue"], reverse=True)
    for p in result:
        p["revenue"] = round(p["revenue"], 2)
        p["price"] = round(p["revenue"] / p["units"], 2) if p["units"] else 0
    return result


def build_all_products(weeks):
    """Every sellable item across a list of weeks: sodas + popcorn + snowcones +
    whatever dynamic "others" sub-categories this dataset has (chairs,
    pop-a-shot, raffle tickets, nee-dohs, candy, or new ones as they appear).
    Built on top of build_soda_products so soda flavors and non-soda
    categories share one list."""
    totals = {p["name"]: dict(p) for p in build_soda_products(weeks)}

    # (display name, category key, per-week units getter, per-week revenue getter)
    fixed_categories = [
        ("Popcorn", "popcorn", lambda w: w["metrics"]["total_popcorn"], lambda w: w["breakdown_revenue"]["popcorn"]),
        ("Snowcones", "snowcones", lambda w: w["metrics"]["total_snowcones"], lambda w: w["breakdown_revenue"]["snowcones"]),
    ]

    for name, category, units_fn, revenue_fn in fixed_categories:
        units = sum(units_fn(w) for w in weeks)
        revenue = round(sum(revenue_fn(w) for w in weeks), 2)
        if units > 0:
            totals[name] = {
                "name": name,
                "units": units,
                "revenue": revenue,
                "category": category,
                "price": round(revenue / units, 2) if units else 0,
            }

    dynamic_cats = weeks[0]["others_categories"] if weeks else []
    for cat in dynamic_cats:
        key = cat["key"]
        units = sum(w["others_units"].get(key, 0) for w in weeks)
        revenue = round(sum(w["others_breakdown"].get(key, 0) for w in weeks), 2)
        if units > 0:
            totals[cat["label"]] = {
                "name": cat["label"],
                "units": units,
                "revenue": revenue,
                "category": key,
                "price": round(revenue / units, 2) if units else 0,
            }

    return sorted(totals.values(), key=lambda p: p["revenue"], reverse=True)


def build_category_breakdown(weeks):
    """Group every sellable item into broad categories (all Polly's Pop
    flavors combined into one row, all Pioneer flavors combined into another,
    plus whatever dynamic "others" sub-categories this dataset has) instead
    of listing every individual flavor."""
    cat_defs = [
        ("Popcorn", "popcorn"),
        ("Snowcones", "snowcones"),
        ("Polly's Pop", "polly"),
        ("Pioneer", "pioneer"),
    ]
    dynamic_cats = weeks[0]["others_categories"] if weeks else []
    cat_defs += [(cat["label"], cat["key"]) for cat in dynamic_cats]
    weekly_by_cat = {key: [] for _, key in cat_defs}

    for w in weeks:
        polly_units = sum(p["units"] for p in w["top_products"] if p["name"].startswith("Polly's Pop"))
        pioneer_units = sum(p["units"] for p in w["top_products"] if p["name"].startswith("Pioneer"))

        per_week_values = {
            "popcorn": (w["metrics"]["total_popcorn"], w["breakdown_revenue"]["popcorn"]),
            "snowcones": (w["metrics"]["total_snowcones"], w["breakdown_revenue"]["snowcones"]),
            "polly": (polly_units, w["breakdown_revenue"]["polly"]),
            "pioneer": (pioneer_units, w["breakdown_revenue"]["pioneer"]),
        }
        for cat in dynamic_cats:
            key = cat["key"]
            per_week_values[key] = (w["others_units"].get(key, 0), w["others_breakdown"].get(key, 0))

        for _, key in cat_defs:
            units, revenue = per_week_values[key]
            weekly_by_cat[key].append({
                "week_label": w["label"].split(" · ")[0],
                "date": w["date"],
                "units": units,
                "revenue": round(revenue, 2),
            })

    categories = []
    for name, key in cat_defs:
        weekly = weekly_by_cat[key]
        total_units = sum(x["units"] for x in weekly)
        total_revenue = round(sum(x["revenue"] for x in weekly), 2)
        best = max(weekly, key=lambda x: x["revenue"]) if weekly else None
        categories.append({
            "name": name,
            "category": key,
            "units": total_units,
            "revenue": total_revenue,
            "price": round(total_revenue / total_units, 2) if total_units else 0,
            "best_week": best,
        })

    return categories


def compute_seller_stats(products):
    """Best/worst seller by revenue and by units for any product list (sodas or all products)."""
    valid = [p for p in products if p["revenue"] > 0]
    if not valid:
        return {"best_by_revenue": None, "worst_by_revenue": None, "best_by_units": None, "worst_by_units": None}
    return {
        "best_by_revenue": max(valid, key=lambda p: p["revenue"]),
        "worst_by_revenue": min(valid, key=lambda p: p["revenue"]),
        "best_by_units": max(valid, key=lambda p: p["units"]),
        "worst_by_units": min(valid, key=lambda p: p["units"]),
    }


def find_week(week_id):
    weeks = get_all_weeks()
    for w in weeks:
        if w["id"] == week_id:
            return w
    return None


def write_export_files(week):
    week_id = week["id"]
    json_path = os.path.join(EXPORT_DIR, f"week_{week_id}.json")
    csv_path = os.path.join(EXPORT_DIR, f"week_{week_id}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(week, f, indent=2, ensure_ascii=False)

    rows = []
    rows.append(["Section", "Field", "Value"])
    rows.append(["Summary", "Week", week["label"]])
    rows.append(["Summary", "Date", week["date"]])
    rows.append(["Summary", "Category", week["category"]])
    rows.append(["Summary", "Net Revenue", week["metrics"]["total_revenue"]])
    rows.append(["Summary", "Attendance", week["metrics"]["total_customers"]])
    rows.append(["Summary", "Total Orders", week["metrics"]["total_orders"]])
    rows.append([])

    for key, val in week["breakdown"].items():
        rows.append(["Revenue Breakdown", key.title(), val])

    rows.append([])
    rows.append(["Product", "Units", "Unit Price", "Revenue"])
    for p in week["top_products"]:
        rows.append([p["name"], p["units"], p["price"], p["revenue"]])

    csv_content = "\n".join(";".join(str(c) for c in row) for row in rows if row)
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    return json_path, csv_path


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/styles.css")
def serve_css():
    return send_from_directory(BASE_DIR, "styles.css")


@app.route("/app.js")
def serve_js():
    return send_from_directory(BASE_DIR, "app.js")


def parse_uploaded_csv(file_storage):
    """Read an uploaded file into memory and parse it exactly the way
    load_csv() reads the on-disk files (';'-separated, latin-1), without
    writing anything yet. Returns (raw_bytes, cleaned_df, valid_week_count)
    or raises ValueError with a human-readable reason - callers decide what
    to do with a bad file, nothing is saved to disk from in here."""
    raw = file_storage.read()
    if not raw:
        raise ValueError("The file is empty")
    try:
        text = raw.decode("latin-1")
    except UnicodeDecodeError:
        raise ValueError("Could not read the file's text encoding")
    try:
        df = pd.read_csv(io.StringIO(text), sep=";")
    except Exception as e:
        raise ValueError(f"Could not parse as a semicolon-separated CSV ({e})")
    df = clean_columns(df)
    if "Day" not in df.columns:
        raise ValueError("No 'Day' column found - is this the right file?")
    valid_weeks = int(df["Day"].apply(is_valid_day).sum())
    if valid_weeks == 0:
        raise ValueError("No rows with a valid d/m/yy date in 'Day' were found")
    return raw, df, valid_weeks


@app.route("/api/upload", methods=["POST"])
def upload_data():
    """Accepts one or both CSVs as multipart form fields named 'global' and
    'individual' (matching the two dropzones in the UI) and, once each one
    parses cleanly, overwrites the file that every other route reads from.
    A bad file is rejected before anything on disk changes."""
    global_file = request.files.get("global")
    indi_file = request.files.get("individual")

    if not global_file and not indi_file:
        return jsonify({"error": "No file received - attach a 'global' and/or 'individual' CSV"}), 400

    result = {"status": "ok"}

    # uploaded_data/ is only created once at startup - if it gets deleted or
    # evicted (e.g. by iCloud/Desktop sync) while the server keeps running,
    # writes below would 500 with a raw FileNotFoundError. Recreate it here,
    # right before we actually need it, so a vanished folder self-heals
    # instead of taking the whole upload down.
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
    except OSError as e:
        return jsonify({"error": f"Could not prepare the uploads folder: {e}"}), 500

    if global_file:
        try:
            raw, df, week_count = parse_uploaded_csv(global_file)
        except ValueError as e:
            return jsonify({"error": f"Global CSV: {e}"}), 400
        dynamic_cats = discover_dynamic_categories(df.columns)
        try:
            with open(GLOBAL_CSV, "wb") as f:
                f.write(raw)
        except OSError as e:
            return jsonify({"error": f"Could not save the global CSV to disk: {e}"}), 500
        result["global"] = {
            "filename": global_file.filename,
            "weeks_detected": week_count,
            "dynamic_categories": [c["label"] for c in dynamic_cats],
        }

    if indi_file:
        try:
            raw, df, week_count = parse_uploaded_csv(indi_file)
        except ValueError as e:
            return jsonify({"error": f"Individual products CSV: {e}"}), 400
        try:
            with open(INDI_CSV, "wb") as f:
                f.write(raw)
        except OSError as e:
            return jsonify({"error": f"Could not save the individual products CSV to disk: {e}"}), 500
        result["individual"] = {
            "filename": indi_file.filename,
            "weeks_detected": week_count,
            "products_detected": len([c for c in df.columns if c != "Day"]),
        }

    return jsonify(result)



@app.route("/api/use-default", methods=["POST"])
def use_default():
    """Explicitly discard any uploaded CSVs for this run, so the dashboard
    falls back to the bundled sample dataset. Used by the 'View sample data'
    choice on the landing gate, so it always shows the real sample - not
    whatever a previous visitor happened to upload this session."""
    for _path in (GLOBAL_CSV, INDI_CSV):
        if os.path.exists(_path):
            os.remove(_path)
    return jsonify({"status": "ok"})


@app.route("/api/status", methods=["GET"])
def data_status():
    return jsonify({
        "global_uploaded": os.path.exists(GLOBAL_CSV),
        "individual_uploaded": os.path.exists(INDI_CSV),
        # True while the dashboard is showing the bundled sample data because
        # this visitor hasn't dropped in their own CSV for that side yet.
        "using_default": is_using_default("global") or is_using_default("individual"),
        "global_using_default": is_using_default("global"),
        "individual_using_default": is_using_default("individual"),
    })


@app.route("/api/overview", methods=["GET"])
def get_overview():
    if not os.path.exists(active_csv_path("global")) or not os.path.exists(active_csv_path("individual")):
        return jsonify({"error": "CSV files not found"}), 404

    all_weeks = get_all_weeks()
    if not all_weeks:
        return jsonify({"error": "No data"}), 404

    week_id = request.args.get("week")
    scoped_week = None
    if week_id:
        scoped_week = next((w for w in all_weeks if w["id"] == week_id), None)
        if not scoped_week:
            return jsonify({"error": "Week not found"}), 404
        weeks = [scoped_week]
    else:
        weeks = all_weeks

    total_revenue = round(sum(w["metrics"]["total_revenue"] for w in weeks), 2)
    total_orders = sum(w["metrics"]["total_orders"] for w in weeks)
    total_customers = sum(w["metrics"]["total_customers"] for w in weeks)
    total_deliveries = sum(w["metrics"]["total_deliveries"] for w in weeks)
    total_popcorn = sum(w["metrics"]["total_popcorn"] for w in weeks)
    total_snowcones = sum(w["metrics"]["total_snowcones"] for w in weeks)
    total_units = sum(w["metrics"]["product_units"] for w in weeks)

    mix_keys = ["popcorn", "snowcones", "polly", "pioneer", "others"]
    mix_totals = {k: round(sum(w["breakdown"][k] for w in weeks), 2) for k in mix_keys}
    mix_total_sum = sum(mix_totals.values())
    mix_pct = {k: round((v / mix_total_sum) * 100, 1) if mix_total_sum else 0 for k, v in mix_totals.items()}

    revenue_mix_keys = ["popcorn", "snowcones", "polly", "pioneer"]
    revenue_mix_totals = {k: round(sum(w["breakdown_revenue"][k] for w in weeks), 2) for k in revenue_mix_keys}

    dynamic_cats = weeks[0]["others_categories"] if weeks else []
    others_keys = [cat["key"] for cat in dynamic_cats]
    others_labels = [cat["label"] for cat in dynamic_cats]
    others_totals = {k: round(sum(w["others_breakdown"].get(k, 0) for w in weeks), 2) for k in others_keys}
    others_values = [others_totals[k] for k in others_keys]
    # Real unit totals for each "others" sub-category, from each week's
    # others_units dict - NOT the dollar revenue values.
    others_units_totals = {k: sum(w["others_units"].get(k, 0) for w in weeks) for k in others_keys}
    others_units_values = [others_units_totals[k] for k in others_keys]

    combined_labels = ["Popcorn", "Snowcones", "Polly's Pop", "Pioneer"] + others_labels
    combined_values = [revenue_mix_totals[k] for k in revenue_mix_keys] + others_values
    # Units aligned to the same combined_labels order (revenue and unit views share one legend).
    combined_units = [mix_totals[k] for k in revenue_mix_keys] + others_units_values

    trend = [{
        "id": w["id"],
        "label": w["label"].split(" · ")[0],
        "date": w["date"],
        "revenue": w["metrics"]["total_revenue"],
        "orders": w["metrics"]["total_orders"],
        "customers": w["metrics"]["total_customers"],
        "product_units": w["metrics"]["product_units"],
        "avg_spend": w["metrics"]["avg_spend_per_attendee"],
        "deliveries": w["metrics"]["total_deliveries"],
    } for w in weeks]

    weekly_detail = build_weekly_detail()

    best_week = max(weeks, key=lambda w: w["metrics"]["total_revenue"])
    worst_week = min(weeks, key=lambda w: w["metrics"]["total_revenue"])

    soda_products = build_soda_products(weeks)
    all_products = build_all_products(weeks)
    soda_stats = compute_seller_stats(soda_products)
    product_stats = compute_seller_stats(all_products)

    # Kept as "top_products" for backward compatibility with pages that already
    # consume it (Overview, Total Products, Products Overview) — this is every
    # sellable item, not just sodas.
    top_products = all_products

    avg_revenue = round(total_revenue / len(weeks), 2) if weeks else 0
    avg_spend_per_attendee = round(total_revenue / total_customers, 2) if total_customers else 0.0

    payload = {
        "weeks_count": len(weeks),
        "scoped_week": ({
            "id": scoped_week["id"],
            "label": scoped_week["label"],
            "date": scoped_week["date"],
            "category": scoped_week["category"],
            "temperature": scoped_week["temperature"],
        } if scoped_week else None),
        "summary": {
            "total_products": len(all_products),
            "total_sodas": len(soda_products),
        },
        "metrics": {
            "total_revenue": total_revenue,
            "avg_revenue_per_week": avg_revenue,
            "total_orders": total_orders,
            "total_customers": total_customers,
            "total_deliveries": total_deliveries,
            "total_popcorn": total_popcorn,
            "total_snowcones": total_snowcones,
            "total_units": total_units,
            "avg_spend_per_attendee": avg_spend_per_attendee,
        },
        "breakdown": mix_totals,
        "breakdown_pct": mix_pct,
        "breakdown_revenue": revenue_mix_totals,
        "others_breakdown": others_totals,
        "charts": {
            "others_labels": others_labels,
            "others_values": others_values,
            "combined_labels": combined_labels,
            "combined_values": combined_values,
            "combined_units": combined_units,
        },
        "trend": trend,
        "weekly_detail": weekly_detail,
        "best_week": {"label": best_week["label"], "revenue": best_week["metrics"]["total_revenue"]},
        "worst_week": {"label": worst_week["label"], "revenue": worst_week["metrics"]["total_revenue"]},
        "top_products": top_products,
        "soda_products": soda_products,
        "seller_stats": {
            "products": product_stats,
            "sodas": soda_stats,
        },
    }

    return jsonify(payload)


@app.route("/api/categories", methods=["GET"])
def get_categories():
    if not os.path.exists(active_csv_path("global")) or not os.path.exists(active_csv_path("individual")):
        return jsonify({"error": "CSV files not found"}), 404

    all_weeks = get_all_weeks()
    if not all_weeks:
        return jsonify({"error": "No data"}), 404

    week_id = request.args.get("week")
    scoped_week = None
    if week_id:
        scoped_week = next((w for w in all_weeks if w["id"] == week_id), None)
        if not scoped_week:
            return jsonify({"error": "Week not found"}), 404
        weeks = [scoped_week]
    else:
        weeks = all_weeks

    categories = build_category_breakdown(weeks)
    valid = [c for c in categories if c["revenue"] > 0]
    best_seller = max(valid, key=lambda c: c["revenue"]) if valid else None
    worst_seller = min(valid, key=lambda c: c["revenue"]) if valid else None

    total_revenue = round(sum(c["revenue"] for c in categories), 2)
    # Kept equal to total_orders (same convention as the Overview page),
    # not a sum of the individual category unit counts below.
    total_units = sum(w["metrics"]["total_orders"] for w in weeks)
    total_customers = sum(w["metrics"]["total_customers"] for w in weeks)
    avg_spend_per_customer = round(total_revenue / total_customers, 2) if total_customers else 0.0

    return jsonify({
        "scoped_week": ({
            "id": scoped_week["id"],
            "label": scoped_week["label"],
            "date": scoped_week["date"],
            "category": scoped_week["category"],
            "temperature": scoped_week["temperature"],
        } if scoped_week else None),
        "metrics": {
            "total_revenue": total_revenue,
            "total_units": total_units,
            "avg_spend_per_customer": avg_spend_per_customer,
        },
        "best_seller": best_seller,
        "worst_seller": worst_seller,
        "categories": categories,
        "charts": {
            "units_by_category": {
                "labels": [c["name"] for c in categories],
                "values": [c["units"] for c in categories],
            },
            "revenue_by_week": {
                "labels": [w["label"].split(" · ")[0] for w in weeks],
                "values": [w["metrics"]["total_revenue"] for w in weeks],
            },
            "revenue_per_category": {
                "labels": [c["name"] for c in categories],
                "values": [c["revenue"] for c in categories],
            },
        },
    })


@app.route("/api/weeks", methods=["GET"])
def list_weeks():
    if not os.path.exists(active_csv_path("global")) or not os.path.exists(active_csv_path("individual")):
        return jsonify({"error": "CSV files not found"}), 404

    weeks = get_all_weeks()
    summary = [{
        "id": w["id"],
        "label": w["label"],
        "date": w["date"],
        "category": w["category"],
        "revenue": w["metrics"]["total_revenue"],
        "orders": w["metrics"]["total_orders"],
        "customers": w["metrics"]["total_customers"],
        "units": w["metrics"]["product_units"],
    } for w in weeks]

    return jsonify({"weeks": summary, "count": len(summary)})


@app.route("/api/weeks/<week_id>", methods=["GET"])
def get_week(week_id):
    week = find_week(week_id)
    if not week:
        return jsonify({"error": "Week not found"}), 404

    write_export_files(week)
    return jsonify(week)


@app.route("/api/data", methods=["GET"])
def get_data_legacy():
    weeks = get_all_weeks()
    if not weeks:
        return jsonify({"error": "No data"}), 404

    week_id = request.args.get("week")
    if week_id:
        week = find_week(week_id)
        if not week:
            return jsonify({"error": "Week not found"}), 404
        return jsonify(week)

    return jsonify(weeks[-1])


@app.route("/api/products", methods=["GET"])
def get_products():
    if not os.path.exists(active_csv_path("global")) or not os.path.exists(active_csv_path("individual")):
        return jsonify({"error": "CSV files not found"}), 404

    scope = request.args.get("week")
    products, weeks_meta = build_products_catalog(scope)

    week_labels = [w["label"] for w in weeks_meta]
    top_by_units = products[:10]

    timeline = []
    for p in top_by_units[:5]:
        week_map = {w["week_id"]: w["units"] for w in p["weekly"]}
        timeline.append({
            "name": p["name"],
            "data": [week_map.get(w["id"], 0) for w in weeks_meta],
        })

    peak_days = [{
        "name": p["name"],
        "units": p["best_week"]["units"] if p["best_week"] else 0,
        "week_label": p["best_week"]["week_label"] if p["best_week"] else "—",
        "date": p["best_week"]["date"] if p["best_week"] else "—",
    } for p in products if p["units"] > 0][:10]

    # "soda_total" drives the Units Sold KPI on this page, which we keep
    # equal to total_orders (same convention as Overview/Categories) rather
    # than a real sum of soda-only units.
    all_weeks = get_all_weeks()
    scoped_weeks = [w for w in all_weeks if not scope or w["id"] == scope]
    soda_total = sum(w["metrics"]["total_orders"] for w in scoped_weeks)
    total_revenue = round(sum(p["revenue"] for p in products), 2)

    return jsonify({
        "scope": scope or "all",
        "weeks": weeks_meta,
        "week_labels": week_labels,
        "products": products,
        "summary": {
            "total_products": len(products),
            "active_products": len([p for p in products if p["units"] > 0]),
            "soda_total": soda_total,
            "total_revenue": total_revenue,
        },
        "charts": {
            "top_units_labels": [p["name"] for p in top_by_units],
            "top_units_values": [p["units"] for p in top_by_units],
            "top_revenue_labels": [p["name"] for p in sorted(products, key=lambda x: x["revenue"], reverse=True)[:10]],
            "top_revenue_values": [p["revenue"] for p in sorted(products, key=lambda x: x["revenue"], reverse=True)[:10]],
            "timeline": timeline,
            "peak_days": peak_days,
        },
    })


@app.route("/api/export/products/<fmt>", methods=["GET"])
def export_products(fmt):
    scope = request.args.get("week")
    products, _ = build_products_catalog(scope)
    if not products:
        return jsonify({"error": "No products"}), 404

    filename = f"products_{scope or 'all'}.{fmt}"

    if fmt == "csv":
        rows = ["Product;Brand;Price;Units;Revenue;Best Week;Best Date;Best Week Units"]
        for p in products:
            bw = p.get("best_week") or {}
            rows.append(
                f"{p['name']};{p['brand']};{p['price']};{p['units']};{p['revenue']};"
                f"{bw.get('week_label', '')};{bw.get('date', '')};{bw.get('units', 0)}"
            )
        content = "\n".join(rows)
        return Response(
            content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    if fmt == "json":
        return Response(
            json.dumps({"products": products}, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return jsonify({"error": "Format not supported"}), 400


@app.route("/api/export/<week_id>/<fmt>", methods=["GET"])
def export_week(week_id, fmt):
    week = find_week(week_id)
    if not week:
        return jsonify({"error": "Week not found"}), 404

    json_path, csv_path = write_export_files(week)
    filename_base = f"sales_report_{week['date'].replace('/', '-')}"

    if fmt == "json":
        with open(json_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(
            content,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.json"},
        )

    if fmt == "csv":
        with open(csv_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(
            content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.csv"},
        )

    return jsonify({"error": "Format not supported. Use json or csv."}), 400


@app.route("/api/export/all/csv", methods=["GET"])
def export_all_csv():
    weeks = get_all_weeks()
    if not weeks:
        return jsonify({"error": "No data"}), 404

    global_df, _, _dynamic_cats = load_merged()
    buffer = io.StringIO()
    global_df.drop(columns=["_id"]).to_csv(buffer, sep=";", index=False)
    content = buffer.getvalue()

    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales_all_weeks.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=False, use_reloader=False, host="0.0.0.0", port=port)
