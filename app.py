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
DATA_DIR = os.path.join(BASE_DIR, "data")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
GLOBAL_CSV = os.path.join(DATA_DIR, "mlm_global.csv")
INDI_CSV = os.path.join(DATA_DIR, "mlm_indi.csv")

os.makedirs(EXPORT_DIR, exist_ok=True)


def clean_columns(df):
    df.columns = [re.sub(r"[\s\u00a0\u00ca\u00c2]+", " ", col).strip() for col in df.columns]
    return df


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
    df = pd.read_csv(path, sep=";", encoding="latin-1")
    df = clean_columns(df)
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
    global_df = load_csv(GLOBAL_CSV)
    indi_df = load_csv(INDI_CSV)

    global_df["_id"] = global_df["Day"].apply(day_to_id)
    indi_df["_id"] = indi_df["Day"].apply(day_to_id)

    return global_df, indi_df


def brand_avg_prices(global_row):
    """Real average price per unit for each brand, derived from actual sales
    totals in the global sheet. If a brand sold zero units that week there is
    no real price to derive, so we return 0 instead of inventing a number
    (units are 0 anyway, so revenue = units * price is unaffected)."""
    polly_units = to_float(global_row.get("Polly's Total Sales", 0))
    polly_revenue = to_float(global_row.get("Polly's Sales", 0))
    pioneer_units = to_float(global_row.get("Pioneer Total Sales", 0))
    pioneer_revenue = to_float(global_row.get("Pioneer Sales", 0))

    polly_price = round(polly_revenue / polly_units, 2) if polly_units else 0.0
    pioneer_price = round(pioneer_revenue / pioneer_units, 2) if pioneer_units else 0.0
    return polly_price, pioneer_price


def build_top_products(global_row, indi_row):
    products = []
    product_cols = [c for c in indi_row.index if c not in ("Day", "_id")]
    polly_price, pioneer_price = brand_avg_prices(global_row)

    for name in product_cols:
        units = int(indi_row[name])
        is_polly = name.startswith("Polly")
        brand = "Polly's Pop" if is_polly else "Pioneer"
        clean_name = re.sub(r"^(Polly|Pioneer)\s+", "", name).strip()
        avg_price = polly_price if is_polly else pioneer_price
        products.append({
            "name": f"{brand} {clean_name}",
            "units": units,
            "price": round(avg_price, 2),
            "revenue": round(units * avg_price, 2),
            "category": "soda",
        })

    # Only beverages (soda) are shown in the Top Selling Products list.
    # Popcorn/Snowcones still count toward revenue mix and delivery totals elsewhere.
    return sorted(products, key=lambda p: p["units"], reverse=True)


def build_week_payload(global_row, indi_row, index, prev_global_row=None):
    revenue = to_float(global_row["Net Sales"])
    prev_revenue = float(prev_global_row["Net Sales"]) if prev_global_row is not None else 0

    popcorn_units = int(to_float(global_row["Popcorn"]))
    snowcone_units = int(to_float(global_row["Snowcones"]))
    
    # For Polly's Pop and Pioneer, we sum the units from the indi_row based on the product names starting with "Polly" or "Pioneer"
    polly_units = sum(int(v) for k, v in indi_row.items() if k.startswith("Polly"))
    pioneer_units = sum(int(v) for k, v in indi_row.items() if k.startswith("Pioneer"))
    
    # Real unit counts for the "others" sub-categories, straight from their
    # dedicated unit columns in the CSV (Chairs, Pop-a-shot, Raffle Tickets,
    # Nee-Dohs, Candy) - NOT the "Others" $ column, which is a revenue total.
    others_chairs_units = int(to_float(global_row.get("Chairs", 0)))
    others_pop_a_shot_units = int(to_float(global_row.get("Pop-a-shot", 0)))
    others_raffle_units = int(to_float(global_row.get("Raffle-Tickets", 0)))
    others_nee_dohs_units = int(to_float(global_row.get("Nee-Dohs", 0)))
    others_candy_units = int(to_float(global_row.get("Candy", 0)))
    others_units = (others_chairs_units + others_pop_a_shot_units + others_raffle_units
                     + others_nee_dohs_units + others_candy_units)

    mix = {
        "popcorn": popcorn_units,
        "snowcones": snowcone_units,
        "polly": polly_units,
        "pioneer": pioneer_units,
        "others": others_units,
    }
    mix_total = sum(mix.values())
    mix_pct = {k: round((v / mix_total) * 100, 1) if mix_total else 0 for k, v in mix.items()}

    top_products = build_top_products(global_row, indi_row)
    soda_total = sum(p["units"] for p in top_products)  # sodas only (Polly's + Pioneer)
    product_units = int(to_float(global_row["Total Sales"]))  # kept equal to total_orders, same number

    # Real dollar revenue for each "others" sub-category, from its dedicated
    # sales column (Chairs Sale, Pop-A-Shot Sales, Raffle Tickets Sales,
    # Nee-Dohs Sale, Candy Sales) - these are the actual $ columns, distinct
    # from the unit-count columns used above.
    others_breakdown = {
        "chairs": round(to_float(global_row.get("Chairs Sale", 0)), 2),
        "pop_a_shot": round(to_float(global_row.get("Pop-A-Shot Sales", 0)), 2),
        "raffle_tickets": round(to_float(global_row.get("Raffle-Tickets Sales", 0)), 2),
        "nee_dohs": round(to_float(global_row.get("Nee-Dohs Sale", 0)), 2),
        "candy": round(to_float(global_row.get("Candy Sales", 0)), 2),
    }
    others_labels = ["Chairs", "Pop-A-Shot", "Raffle Tickets", "Nee-Dohs", "Candy"]
    others_values = [others_breakdown["chairs"], others_breakdown["pop_a_shot"],
                      others_breakdown["raffle_tickets"], others_breakdown["nee_dohs"], others_breakdown["candy"]]
    # Real unit counts aligned to others_labels order (for the units chart).
    others_units_list = [others_chairs_units, others_pop_a_shot_units, others_raffle_units,
                          others_nee_dohs_units, others_candy_units]

    # Real dollar revenue for Polly's Pop / Pioneer straight from the sales
    # columns (not an estimate), so these categories reflect actual sales.
    polly_revenue = round(to_float(global_row.get("Polly's Sales", 0)), 2)
    pioneer_revenue = round(to_float(global_row.get("Pioneer Sales", 0)), 2)

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
        "others": round(sum(others_breakdown.values()), 2),
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
            "total_chairs": int(to_float(global_row.get("Chairs", 0))),
            "total_pop_a_shot": int(to_float(global_row.get("Pop-a-shot", 0))),
            "total_raffle_tickets": int(to_float(global_row.get("Raffle-Tickets", 0))),
            "total_nee_dohs": int(to_float(global_row.get("Nee-Dohs", 0))),
            "total_candy": int(to_float(global_row.get("Candy", 0))),
            "avg_spend_per_attendee": avg_spend,
        },
        "breakdown": mix,
        "breakdown_pct": mix_pct,
        "breakdown_revenue": mix_revenue,
        "others_breakdown": others_breakdown,
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
    global_df, indi_df = load_merged()
    weeks = []
    product_cols = [c for c in indi_df.columns if c not in ("Day", "_id")]

    for i, (_, grow) in enumerate(global_df.iterrows()):
        prev = global_df.iloc[i - 1] if i > 0 else None
        indi_match = indi_df[indi_df["_id"] == grow["_id"]]
        if indi_match.empty:
            # No soda-flavor row for this week in mlm_indi.csv - use zeros for
            # the soda breakdown only, but still keep this week's real data
            # (Popcorn, Snowcones, Chairs, Nee-Dohs, Candy, etc. all come from
            # mlm_global.csv and must not be dropped just because the
            # separate soda-flavor file is missing this day).
            indi_row = pd.Series({c: 0 for c in product_cols})
        else:
            indi_row = indi_match.iloc[0]
        weeks.append(build_week_payload(grow, indi_row, i, prev))

    return weeks


def build_products_catalog(scope_week_id=None):
    global_df, indi_df = load_merged()
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
        polly_price, pioneer_price = brand_avg_prices(grow)

        for name in product_cols:
            units = int(indi_row[name])
            is_polly = name.startswith("Polly")
            brand = "Polly's Pop" if is_polly else "Pioneer"
            clean_name = re.sub(r"^(Polly|Pioneer)\s+", "", name).strip()
            display_name = f"{brand} {clean_name}"
            price = polly_price if is_polly else pioneer_price

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
            entry["revenue"] += round(units * price, 2)
            entry["weekly"].append({
                "week_id": wm["id"],
                "week_label": wm["label"],
                "date": wm["date"],
                "units": units,
                "revenue": round(units * price, 2),
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
        "chairs": w["metrics"]["total_chairs"],
        "pop_a_shot": w["metrics"]["total_pop_a_shot"],
        "raffle_tickets": w["metrics"]["total_raffle_tickets"],
        "nee_dohs": w["metrics"]["total_nee_dohs"],
        "candy": w["metrics"]["total_candy"],
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
    chairs + pop-a-shot + raffle tickets + nee-dohs + candy. Built on top of
    build_soda_products so soda flavors and non-soda categories share one list."""
    totals = {p["name"]: dict(p) for p in build_soda_products(weeks)}

    # (display name, category key, per-week units getter, per-week revenue getter)
    extra_categories = [
        ("Popcorn", "popcorn", lambda w: w["metrics"]["total_popcorn"], lambda w: w["breakdown_revenue"]["popcorn"]),
        ("Snowcones", "snowcones", lambda w: w["metrics"]["total_snowcones"], lambda w: w["breakdown_revenue"]["snowcones"]),
        ("Chairs", "chairs", lambda w: w["metrics"]["total_chairs"], lambda w: w["others_breakdown"]["chairs"]),
        ("Pop-A-Shot", "pop_a_shot", lambda w: w["metrics"]["total_pop_a_shot"], lambda w: w["others_breakdown"]["pop_a_shot"]),
        ("Raffle Tickets", "raffle_tickets", lambda w: w["metrics"]["total_raffle_tickets"], lambda w: w["others_breakdown"]["raffle_tickets"]),
        ("Nee-Dohs", "nee_dohs", lambda w: w["metrics"]["total_nee_dohs"], lambda w: w["others_breakdown"]["nee_dohs"]),
        ("Candy", "candy", lambda w: w["metrics"]["total_candy"], lambda w: w["others_breakdown"]["candy"]),
    ]

    for name, category, units_fn, revenue_fn in extra_categories:
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

    return sorted(totals.values(), key=lambda p: p["revenue"], reverse=True)


def build_category_breakdown(weeks):
    """Group every sellable item into 9 broad categories (all Polly's Pop
    flavors combined into one row, all Pioneer flavors combined into another)
    instead of listing every individual flavor."""
    cat_defs = [
        ("Popcorn", "popcorn"),
        ("Snowcones", "snowcones"),
        ("Polly's Pop", "polly"),
        ("Pioneer", "pioneer"),
        ("Chairs", "chairs"),
        ("Pop-A-Shot", "pop_a_shot"),
        ("Raffle Tickets", "raffle_tickets"),
        ("Nee-Dohs", "nee_dohs"),
        ("Candy", "candy"),
    ]
    weekly_by_cat = {key: [] for _, key in cat_defs}

    for w in weeks:
        polly_units = sum(p["units"] for p in w["top_products"] if p["name"].startswith("Polly's Pop"))
        pioneer_units = sum(p["units"] for p in w["top_products"] if p["name"].startswith("Pioneer"))

        per_week_values = {
            "popcorn": (w["metrics"]["total_popcorn"], w["breakdown_revenue"]["popcorn"]),
            "snowcones": (w["metrics"]["total_snowcones"], w["breakdown_revenue"]["snowcones"]),
            "polly": (polly_units, w["breakdown_revenue"]["polly"]),
            "pioneer": (pioneer_units, w["breakdown_revenue"]["pioneer"]),
            "chairs": (w["metrics"]["total_chairs"], w["others_breakdown"]["chairs"]),
            "pop_a_shot": (w["metrics"]["total_pop_a_shot"], w["others_breakdown"]["pop_a_shot"]),
            "raffle_tickets": (w["metrics"]["total_raffle_tickets"], w["others_breakdown"]["raffle_tickets"]),
            "nee_dohs": (w["metrics"]["total_nee_dohs"], w["others_breakdown"]["nee_dohs"]),
            "candy": (w["metrics"]["total_candy"], w["others_breakdown"]["candy"]),
        }

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


@app.route("/api/overview", methods=["GET"])
def get_overview():
    if not os.path.exists(GLOBAL_CSV) or not os.path.exists(INDI_CSV):
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

    others_keys = ["chairs", "pop_a_shot", "raffle_tickets", "nee_dohs", "candy"]
    others_totals = {k: round(sum(w["others_breakdown"][k] for w in weeks), 2) for k in others_keys}
    others_labels = ["Chairs", "Pop-A-Shot", "Raffle Tickets", "Nee-Dohs", "Candy"]
    others_values = [others_totals[k] for k in others_keys]
    # Real unit totals for each "others" sub-category, from the week metrics
    # (total_chairs, total_pop_a_shot, etc.) - NOT the dollar revenue values.
    others_unit_metric_keys = {
        "chairs": "total_chairs",
        "pop_a_shot": "total_pop_a_shot",
        "raffle_tickets": "total_raffle_tickets",
        "nee_dohs": "total_nee_dohs",
        "candy": "total_candy",
    }
    others_units_totals = {k: sum(w["metrics"][m] for w in weeks) for k, m in others_unit_metric_keys.items()}
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
    if not os.path.exists(GLOBAL_CSV) or not os.path.exists(INDI_CSV):
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
    if not os.path.exists(GLOBAL_CSV) or not os.path.exists(INDI_CSV):
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
    if not os.path.exists(GLOBAL_CSV) or not os.path.exists(INDI_CSV):
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

    global_df, _ = load_merged()
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
