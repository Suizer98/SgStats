from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date

import pandas as pd

from app.constants import (
    FALLBACK_YEARS,
    GRAIN_LABELS,
    MAX_CORRELATIONS,
    MAX_MEASURES,
    MAX_OUTLIERS,
    MAX_PERIODS,
    MAX_SCALE_RATIO,
    MAX_SERIES,
    MIN_CORRELATION_POINTS,
    MIN_OUTLIER_POINTS,
    MISSING_MARKERS,
    MONTHS,
    OPEN_ENDED,
    OUTLIER_Z,
    PREFERRED_MEASURES,
    SECTORS,
    SKIP_NUMERIC,
    TIME_HINTS,
)
from app.core.settings import DATA_DIR


def current_year() -> int:
    return date.today().year


def stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> set[str]:
    return {stem(item) for item in re.findall(r"[a-z][a-z]+", str(text).lower())}


def tokens_match(left: str, right: str) -> bool:
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 5 and longer.startswith(shorter)


def relevance(text: str, tokens: set[str]) -> int:
    words = tokenize(text)
    return sum(1 for token in tokens if any(tokens_match(token, word) for word in words))


def parse_query(query: str) -> dict:
    years = sorted({int(item) for item in re.findall(r"\b(?:19|20)\d{2}\b", query)})
    lowered = query.lower()
    now = current_year()
    if len(years) >= 2:
        year_from, year_to = years[0], years[-1]
    elif years:
        open_ended = OPEN_ENDED.search(lowered) or re.search(r"\bfrom\s+(?:19|20)\d{2}\b", lowered)
        year_from, year_to = years[0], now if open_ended else years[0]
    else:
        year_from, year_to = now - 9, now
    sector = None
    for key, name in SECTORS.items():
        if key in lowered:
            sector = name
            break
    return {"year_from": year_from, "year_to": year_to, "sector": sector}


def parse_period(value) -> tuple[str, int, str] | None:
    """Map a period label from any source to (sortable label, year, grain)."""
    text = str(value).strip()
    year = r"((?:19|20)\d{2})"
    if match := re.fullmatch(year, text):
        return text, int(text), "year"
    if match := re.fullmatch(year + r"\s*[-/ ]?\s*Q([1-4])", text, re.I) or re.fullmatch(year + r"\s*([1-4])Q", text, re.I):
        return f"{match[1]}-Q{match[2]}", int(match[1]), "quarter"
    if match := re.fullmatch(r"([1-4])Q\s*" + year, text, re.I):
        return f"{match[2]}-Q{match[1]}", int(match[2]), "quarter"
    if match := re.fullmatch(year + r"\s*[-/ ]?\s*H([12])", text, re.I) or re.fullmatch(year + r"\s*([12])H", text, re.I):
        return f"{match[1]}-H{match[2]}", int(match[1]), "half"
    if match := re.fullmatch(year + r"-(\d{1,2})(?:-\d{1,2})?(?:[T ].*)?", text):
        month = int(match[2])
        if 1 <= month <= 12:
            return f"{match[1]}-{month:02d}", int(match[1]), "month"
    if match := re.fullmatch(year + r"\s*([A-Za-z]{3})[A-Za-z]*", text):
        month = MONTHS.get(match[2].lower())
        if month:
            return f"{match[1]}-{month:02d}", int(match[1]), "month"
    if match := re.fullmatch(year + r"\s*/\s*\d{2,4}", text):
        return match[1], int(match[1]), "year"
    return None


def to_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def clean_label(text) -> str:
    label = re.sub(r"\s+", " ", str(text)).strip()
    if re.fullmatch(r"[a-z0-9_ ]+", label):
        label = label.replace("_", " ").title()
    return label


def is_wide(records: list[dict]) -> bool:
    if not records:
        return False
    return sum(1 for key in records[0] if parse_period(key)) >= 2


def normalize_wide(records: list[dict], measure: str = "Value") -> list[dict]:
    """Unindented labels start a section; indented rows in later sections are breakdowns and get the section name."""
    rows = []
    section = first_section = None
    for record in records:
        periods = {key: parsed for key in record if (parsed := parse_period(key))}
        label_key = next(
            (key for key in record if key not in periods and key != "_id" and isinstance(record[key], str)),
            None,
        )
        raw = str(record[label_key]) if label_key else ""
        series = clean_label(raw) if label_key else measure
        if raw and not raw[0].isspace():
            section = series
            first_section = first_section or series
        elif section and section != first_section:
            series = f"{series} ({section})"
        for key, (period, year, grain) in periods.items():
            number = to_number(record[key])
            if number is not None:
                rows.append({"period": period, "grain": grain, "series": series, "measure": measure, "value": number})
    return rows


def find_time_column(frame: pd.DataFrame) -> str | None:
    hinted = sorted(frame.columns, key=lambda name: 0 if any(hint in name.lower() for hint in TIME_HINTS) else 1)
    for column in hinted:
        sample = frame[column].dropna().astype(str).head(50)
        if len(sample) and sample.map(lambda item: parse_period(item) is not None).mean() >= 0.8:
            return column
    return None


def numeric_columns(frame: pd.DataFrame, exclude: set[str]) -> list[str]:
    found = []
    for column in frame.columns:
        if column in exclude or SKIP_NUMERIC.search(column.lower()):
            continue
        present = frame[column].dropna().astype(str).str.strip()
        present = present[~present.str.lower().isin(MISSING_MARKERS)]
        if len(present) and present.map(lambda item: to_number(item) is not None).mean() >= 0.8:
            found.append(column)
    return found


def rank_measures(columns: list[str], tokens: set[str]) -> list[str]:
    def score(item: tuple[int, str]) -> tuple:
        index, column = item
        preferred = any(word in column.lower() for word in PREFERRED_MEASURES)
        return (-relevance(column, tokens), 0 if preferred else 1, -index)

    return [column for _, column in sorted(enumerate(columns), key=score)][:MAX_MEASURES]


def series_column(frame: pd.DataFrame, exclude: set[str]) -> str | None:
    best = None
    for column in frame.columns:
        if column in exclude:
            continue
        count = frame[column].astype(str).nunique()
        if 2 <= count <= 12 and (best is None or count < best[1]):
            best = (column, count)
    return best[0] if best else None


def normalize_long(records: list[dict], titles: dict | None = None, tokens: set[str] | None = None) -> list[dict]:
    titles = titles or {}
    frame = pd.DataFrame(records).drop(columns=["_id"], errors="ignore")
    if frame.empty:
        return []
    time_col = find_time_column(frame)
    if time_col is None:
        return []
    parsed = frame[time_col].map(parse_period)
    frame = frame[parsed.notna()]
    parsed = parsed[parsed.notna()]
    measures = rank_measures(numeric_columns(frame, {time_col}), tokens or set())
    series_col = series_column(frame, {time_col, *measures})
    rows: list[dict] = []
    for column in measures:
        measure = clean_label(titles.get(column, column))
        values = frame[column].map(to_number)
        series = frame[series_col].map(clean_label) if series_col else measure
        part = pd.DataFrame(
            {
                "period": parsed.map(lambda item: item[0]),
                "grain": parsed.map(lambda item: item[2]),
                "series": series,
                "measure": measure,
                "value": values,
            }
        ).dropna(subset=["value"])
        rows.extend(part.to_dict(orient="records"))
    return rows


def normalize_singstat(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        series = clean_label(row.get("rowText") or row.get("series") or "Value")
        measure = clean_label(row.get("uoM") or "Value")
        for cell in row.get("columns") or []:
            parsed = parse_period(cell.get("key", ""))
            number = to_number(cell.get("value"))
            if parsed and number is not None:
                out.append({"period": parsed[0], "grain": parsed[2], "series": series, "measure": measure, "value": number})
    return out


def finish_rows(rows: list[dict], year_from: int, year_to: int) -> tuple[list[dict], str | None, str]:
    """Keep the dominant grain and requested years; fall back to the latest years when the range is not covered."""
    if not rows:
        return [], None, ""
    grain = Counter(row["grain"] for row in rows).most_common(1)[0][0]
    same = [row for row in rows if row["grain"] == grain]
    kept = [row for row in same if year_from <= int(row["period"][:4]) <= year_to]
    note = ""
    if not kept:
        years = sorted({int(row["period"][:4]) for row in same})[-FALLBACK_YEARS:]
        kept = [row for row in same if int(row["period"][:4]) in years]
        note = f"No data for {year_from}-{year_to}; showing latest available {years[0]}-{years[-1]}."
    elif (latest := max(row["period"] for row in kept)) and int(latest[:4]) < year_to - 1:
        note = f"Latest published period is {latest}, earlier than the requested {year_to}."
    cleaned = [{key: value for key, value in row.items() if key != "grain"} for row in kept]
    return cleaned, grain, note


def find_outliers(frame: pd.DataFrame) -> list[dict]:
    """Robust z-score (median and MAD) per series; values are flagged, never removed."""
    if not {"series", "period", "value"} <= set(frame.columns):
        return []
    found = []
    for series, part in frame.groupby("series", sort=False):
        values = part["value"].astype(float)
        if len(values) < MIN_OUTLIER_POINTS:
            continue
        median = values.median()
        spread = (values - median).abs().median() * 1.4826
        if spread == 0:
            continue
        scores = (values - median).abs() / spread
        for index in scores[scores > OUTLIER_Z].index:
            found.append({"series": str(series), "period": str(part.at[index, "period"]), "value": float(values[index])})
    return found[:MAX_OUTLIERS]


def quality_check(
    frame: pd.DataFrame,
    required: list[str] | None = None,
    source_records: int | None = None,
    normalised_rows: int | None = None,
    in_range_rows: int | None = None,
) -> dict:
    required = required or []
    missing = [col for col in required if col not in frame.columns]
    before = len(frame)
    cleaned = frame.drop_duplicates().dropna(how="all")
    nulls = {col: int(cleaned[col].isna().sum()) for col in cleaned.columns}
    if "value" in cleaned.columns:
        cleaned = cleaned.dropna(subset=["value"])
    outliers = find_outliers(cleaned)
    checks = []
    if source_records is not None and normalised_rows is not None:
        checks.append(f"Parsed {source_records:,} source records into {normalised_rows:,} numeric period rows.")
    if normalised_rows is not None and in_range_rows is not None and normalised_rows > in_range_rows:
        checks.append(
            f"Kept {in_range_rows:,} rows in the requested period and dropped {normalised_rows - in_range_rows:,}."
        )
    if in_range_rows is not None and in_range_rows > before:
        checks.append(f"Averaged {in_range_rows:,} records into {before:,} period rows.")
    duplicates = before - len(frame.drop_duplicates())
    if duplicates:
        checks.append(f"Removed {duplicates:,} duplicate rows.")
    if nulls.get("value"):
        checks.append(f"Dropped {nulls['value']:,} rows with no numeric value.")
    if missing:
        checks.append(f"Missing required columns: {', '.join(missing)}.")
    if outliers:
        sample = outliers[0]
        checks.append(
            f"Flagged {len(outliers)} possible outlier(s), e.g. {sample['series']} {sample['period']} = {sample['value']:,}."
        )
    series = int(cleaned["series"].nunique()) if "series" in cleaned.columns else 0
    periods = sorted(cleaned["period"].unique()) if "period" in cleaned.columns else []
    return {
        "rows": int(len(cleaned)),
        "missing_columns": missing,
        "nulls": nulls,
        "duplicates_removed": int(duplicates),
        "series": series,
        "periods": len(periods),
        "coverage": f"{periods[0]} to {periods[-1]}" if periods else "",
        "outliers": outliers,
        "checks": checks,
        "ok": not missing and len(cleaned) > 0,
        "frame": cleaned,
    }


def normalize_any(records: list[dict], titles: dict | None = None, tokens: set[str] | None = None) -> list[dict]:
    if is_wide(records):
        return normalize_wide(records)
    return normalize_long(records, titles, tokens)


def read_excel(filename: str) -> list[dict]:
    frame = pd.read_excel(DATA_DIR / filename)
    return frame.where(frame.notna(), None).to_dict(orient="records")


def load_snapshot(filename: str, year_from: int, year_to: int, tokens: set[str] | None = None) -> dict:
    path = DATA_DIR / filename
    singstat = False
    if filename.endswith(".xlsx"):
        records = read_excel(filename)
        fmt = "xlsx"
    elif filename.endswith(".csv"):
        records = pd.read_csv(path).to_dict(orient="records")
        fmt = "csv"
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload["records"] if isinstance(payload, dict) else payload
        singstat = isinstance(payload, dict) and payload.get("provider") == "singstat"
        fmt = "json"
    normalised = normalize_singstat(records) if singstat else normalize_any(records, tokens=tokens)
    rows, grain, note = finish_rows(normalised, year_from, year_to)
    checked = quality_check(pd.DataFrame(rows), ["period", "value"], len(records), len(normalised), len(rows))
    return {
        "format": fmt,
        "grain": grain,
        "note": note,
        "quality": {k: v for k, v in checked.items() if k != "frame"},
        "records": rows,
    }


def unit_symbol(measure: str) -> str:
    return "%" if measure.lower() in ("per cent", "percent", "%", "percentage") else ""


def comparable_series(part: pd.DataFrame, ordered: list[str]) -> list[str]:
    """Drop series on a wildly different scale from the lead series so one axis stays readable."""
    if not ordered:
        return []
    size = part.groupby("series")["value"].apply(lambda values: values.abs().mean())
    lead = size[ordered[0]]
    kept = [ordered[0]]
    for name in ordered[1:]:
        ratio = (max(lead, size[name]) + 1) / (min(lead, size[name]) + 1)
        if ratio <= MAX_SCALE_RATIO:
            kept.append(name)
    return kept


def build_chart(dataset: dict, measure: str, part: pd.DataFrame, tokens: set[str]) -> tuple[dict, pd.DataFrame, list[str]]:
    grain = dataset.get("grain") or "year"
    part = part.copy()
    notes = []
    if part.duplicated(["period", "series"]).any():
        notes.append(f"average per {grain}")
    if grain != "year" and part["period"].nunique() > MAX_PERIODS:
        part["period"] = part["period"].str[:4]
        grain = "year"
        notes = ["annual average"]
    order = list(dict.fromkeys(part["series"]))
    by_relevance = sorted(order, key=lambda name: (-relevance(name, tokens), order.index(name)))
    ranked = comparable_series(part, by_relevance)[:MAX_SERIES]
    grouped = part[part["series"].isin(ranked)].groupby(["period", "series"], as_index=False)["value"].mean()
    wide = grouped.pivot(index="period", columns="series", values="value").sort_index()[ranked].round(2)
    keys = {name: f"s{index}" for index, name in enumerate(ranked)}
    data = [
        {"period": period, **{keys[name]: float(value) for name, value in row.items() if pd.notna(value)}}
        for period, row in wide.iterrows()
    ]
    title = dataset.get("title") or dataset.get("source", "Dataset")
    labels = {name: (title if name == measure else name) for name in ranked}
    wide = wide.rename(columns=labels)
    subtitle = [dataset.get("source", ""), measure]
    if len(ranked) < len(order):
        subtitle.append(f"{len(ranked)} of {len(order)} series")
    subtitle.extend(notes)
    if dataset.get("note"):
        subtitle.append(dataset["note"])
    chart = {
        "id": f"{dataset.get('dataset_id') or dataset.get('source', 'data')}-{re.sub(r'[^a-z0-9]+', '-', measure.lower())}",
        "title": title,
        "subtitle": " · ".join(item for item in subtitle if item),
        "type": "bar" if len(data) <= 3 else "line",
        "xKey": "period",
        "xLabel": GRAIN_LABELS.get(grain, "Period"),
        "yLabel": measure,
        "unit": unit_symbol(measure),
        "series": [{"key": keys[name], "label": labels[name]} for name in ranked],
        "data": data,
    }
    return chart, wide, notes


def summarise(datasets: list[dict], tokens: set[str] | None = None) -> dict:
    tokens = tokens or set()
    metrics = []
    charts = []
    facts: list[float] = []

    for dataset in datasets:
        frame = pd.DataFrame(dataset.get("records") or [])
        if frame.empty or not {"period", "series", "measure", "value"} <= set(frame.columns):
            continue
        for measure, part in frame.groupby("measure", sort=False):
            chart, wide, notes = build_chart(dataset, str(measure), part, tokens)
            if not chart["data"]:
                continue
            charts.append(chart)
            facts.extend(float(value) for value in wide.to_numpy().ravel() if pd.notna(value))
            steps = wide.pct_change(fill_method=None).mul(100).round(1).to_numpy().ravel()
            facts.extend(float(value) for value in steps if pd.notna(value) and abs(value) != float("inf"))
            for name in list(wide.columns)[:2]:
                column = wide[name].dropna()
                if column.empty:
                    continue
                latest = float(column.iloc[-1])
                start = float(column.iloc[0])
                detail = f"{measure}, {column.index[-1]}"
                change = None
                if len(column) >= 2 and chart["unit"] == "%":
                    change = round(latest - start, 2)
                    detail += f" · {change:+.1f} pp since {column.index[0]} ({start:,.1f}%)"
                elif len(column) >= 2 and start > 0 and latest >= 0:
                    change = round((latest - start) / start * 100, 1)
                    detail += f" · {change:+.1f}% since {column.index[0]} ({start:,.1f})"
                elif len(column) >= 2:
                    change = round(latest - start, 2)
                    detail += f" · {change:+,.1f} since {column.index[0]} ({start:,.1f})"
                if change is not None:
                    facts.extend([start, change])
                if notes:
                    detail += f" · {notes[0]}"
                metrics.append(
                    {
                        "label": name,
                        "value": latest,
                        "unit": chart["unit"],
                        "detail": detail,
                        "change": change,
                    }
                )
                facts.append(latest)
        facts.extend(float(row["value"]) for row in dataset.get("records", []) if isinstance(row.get("value"), (int, float)))

    correlations = find_correlations(charts)
    facts.extend(item["r"] for item in correlations)
    return {"metrics": metrics[:6], "charts": charts[:6], "facts": facts, "correlations": correlations}


def chart_columns(chart: dict) -> dict[str, pd.Series]:
    columns = {}
    for series in chart["series"]:
        values = {row["period"]: row[series["key"]] for row in chart["data"] if series["key"] in row}
        columns[series["label"]] = pd.Series(values, dtype=float)
    return columns


def find_correlations(charts: list[dict]) -> list[dict]:
    """Pearson r between the lead series of each chart and every other series sharing its periods."""
    if not charts:
        return []
    lead_chart = charts[0]
    lead_name = lead_chart["series"][0]["label"] if lead_chart["series"] else None
    if lead_name is None:
        return []
    lead = chart_columns(lead_chart)[lead_name]
    lead_base = base_label(lead_name)
    found = []
    for chart in charts:
        for name, column in chart_columns(chart).items():
            if chart is lead_chart and base_label(name) == lead_base:
                continue
            aligned = pd.concat([lead, column], axis=1, join="inner").dropna()
            if len(aligned) < MIN_CORRELATION_POINTS or aligned.nunique().min() < 2:
                continue
            r = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
            if pd.isna(r):
                continue
            found.append(
                {
                    "a": lead_name,
                    "b": name,
                    "b_source": chart["title"],
                    "r": round(r, 2),
                    "periods": len(aligned),
                    "strength": correlation_strength(r),
                }
            )
    found.sort(key=lambda item: -abs(item["r"]))
    return found[:MAX_CORRELATIONS]


def base_label(name: str) -> str:
    """Drop qualifiers such as '(Seasonally Adjusted)' so variants of one series are not correlated with each other."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip().lower()


def correlation_strength(r: float) -> str:
    size = abs(r)
    direction = "positive" if r >= 0 else "negative"
    if size >= 0.7:
        return f"strong {direction}"
    if size >= 0.4:
        return f"moderate {direction}"
    return "weak"
