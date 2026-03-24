"""Pillow-based month calendar image renderer for the /events command."""

import calendar as cal_mod
import datetime
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Colour palette ───────────────────────────────────────────────────────────

_WHITE = (255, 255, 255)
_HEADER_BG = (30, 64, 175)       # blue-800
_HEADER_TEXT = (255, 255, 255)
_DAY_NAME_BG = (248, 250, 252)   # slate-50
_DAY_NAME_TEXT = (100, 116, 139)  # slate-500
_CELL_BORDER = (226, 232, 240)   # slate-200
_DAY_NUM = (30, 41, 55)          # slate-800
_DAY_NUM_OUTSIDE = (203, 213, 225)  # slate-300
_TODAY_BG = (219, 234, 254)      # blue-100
_TODAY_RING = (59, 130, 246)     # blue-500
_RECURRING = (59, 130, 246)      # blue-500
_ONE_TIME = (249, 115, 22)       # orange-500
_BAR_RECURRING = (147, 197, 253)   # blue-300
_BAR_ONE_TIME = (253, 186, 116)    # orange-300
_BAR_TEXT = (30, 41, 55)         # slate-800
_LEGEND_TEXT = (71, 85, 105)     # slate-600

# ── Layout constants ─────────────────────────────────────────────────────────

_PAD = 20
_HEADER_H = 50
_DAY_NAMES_H = 28
_CELL_W = 96
_CELL_H = 80
_COLS = 7
_ROWS = 6
_LEGEND_H = 36

_CANVAS_W = _PAD * 2 + _CELL_W * _COLS         # 712
_CANVAS_H = (
    _PAD + _HEADER_H + _DAY_NAMES_H + _CELL_H * _ROWS + _LEGEND_H + _PAD
)  # 614

_DOT_R = 5  # event dot radius
_BAR_H = 13
_BAR_GAP = 2

# ── Font helpers ─────────────────────────────────────────────────────────────

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
_FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = _FONT_BOLD_PATHS if bold else _FONT_PATHS
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


# ── Grid helpers ─────────────────────────────────────────────────────────────


def _grid_origin() -> tuple[int, int]:
    """Top-left corner of the grid area (first cell)."""
    return _PAD, _PAD + _HEADER_H + _DAY_NAMES_H


def _cell_box(row: int, col: int) -> tuple[int, int, int, int]:
    """Return (x1, y1, x2, y2) for a grid cell."""
    ox, oy = _grid_origin()
    x1 = ox + col * _CELL_W
    y1 = oy + row * _CELL_H
    return x1, y1, x1 + _CELL_W, y1 + _CELL_H


def _build_grid(year: int, month: int):
    """Return a 6-row × 7-col grid of (day_num, in_month) tuples.

    Days outside the month are filled with neighbouring month numbers and
    ``in_month=False``.
    """
    weeks = cal_mod.monthcalendar(year, month)
    # Pad to 6 rows
    while len(weeks) < _ROWS:
        weeks.append([0] * 7)

    # Compute previous-month day numbers for leading zeros
    if month == 1:
        prev_last = cal_mod.monthrange(year - 1, 12)[1]
    else:
        prev_last = cal_mod.monthrange(year, month - 1)[1]

    grid: list[list[tuple[int, bool]]] = []
    next_day = 1  # counter for trailing next-month days
    for week in weeks:
        row: list[tuple[int, bool]] = []
        for day in week:
            if day != 0:
                row.append((day, True))
            else:
                # Determine if this is a leading or trailing zero
                if not grid and not any(d != 0 for d in week[: week.index(0) + 1] if d != 0):
                    # Leading zeros (before first in-month day)
                    row.append((-1, False))  # placeholder, fixed below
                else:
                    row.append((next_day, False))
                    next_day += 1
        grid.append(row)

    # Fix leading zeros: fill backwards from prev_last
    first_week = grid[0]
    leading_count = sum(1 for d, m in first_week if not m)
    idx = 0
    for i, (d, m) in enumerate(first_week):
        if not m:
            first_week[i] = (prev_last - leading_count + idx + 1, False)
            idx += 1

    return grid


# ── Multi-day bar lane assignment ────────────────────────────────────────────


def _assign_bar_lanes(
    multi_day: list[dict], year: int, month: int, grid: list
) -> list[dict]:
    """Assign a vertical lane to each multi-day bar segment per grid row.

    Returns a list of drawable bar segments:
        {row, col_start, col_end, lane, summary, is_recurring}
    """
    # Build day → (row, col) mapping for in-month days
    day_to_cell: dict[int, tuple[int, int]] = {}
    for r, week in enumerate(grid):
        for c, (day, in_month) in enumerate(week):
            if in_month:
                day_to_cell[day] = (r, c)

    first_of_month = datetime.date(year, month, 1)
    _, last_day = cal_mod.monthrange(year, month)
    last_of_month = datetime.date(year, month, last_day)

    segments: list[dict] = []
    for ev in multi_day:
        start = max(ev["start_date"], first_of_month)
        end = min(ev["end_date"], last_of_month)
        if start > last_of_month or end < first_of_month:
            continue

        # Collect cells this bar occupies
        cells: list[tuple[int, int]] = []
        d = start
        while d <= end:
            if d.day in day_to_cell:
                cells.append(day_to_cell[d.day])
            d += datetime.timedelta(days=1)
        if not cells:
            continue

        # Split into row-contiguous segments
        current_row = cells[0][0]
        seg_start_col = cells[0][1]
        seg_end_col = cells[0][1]
        for r, c in cells[1:]:
            if r == current_row:
                seg_end_col = c
            else:
                segments.append(
                    {
                        "row": current_row,
                        "col_start": seg_start_col,
                        "col_end": seg_end_col,
                        "summary": ev["summary"],
                        "is_recurring": ev["is_recurring"],
                    }
                )
                current_row = r
                seg_start_col = c
                seg_end_col = c
        segments.append(
            {
                "row": current_row,
                "col_start": seg_start_col,
                "col_end": seg_end_col,
                "summary": ev["summary"],
                "is_recurring": ev["is_recurring"],
            }
        )

    # Assign lanes per row (simple greedy: first-come-first-lane)
    row_lanes: dict[int, list[list[int]]] = {}  # row -> list of occupied col ranges per lane
    for seg in segments:
        r = seg["row"]
        if r not in row_lanes:
            row_lanes[r] = []
        placed = False
        for lane_idx, occupied in enumerate(row_lanes[r]):
            # Check overlap
            if not any(
                seg["col_start"] <= oc <= seg["col_end"] for oc in occupied
            ):
                occupied.extend(range(seg["col_start"], seg["col_end"] + 1))
                seg["lane"] = lane_idx
                placed = True
                break
        if not placed:
            seg["lane"] = len(row_lanes[r])
            row_lanes[r].append(
                list(range(seg["col_start"], seg["col_end"] + 1))
            )

    return segments


# ── Main render function ─────────────────────────────────────────────────────


def render_calendar_image(
    year: int,
    month: int,
    processed: dict,
    today: datetime.date,
) -> io.BytesIO:
    """Render a month-view calendar as a PNG and return it as a BytesIO buffer.

    ``processed`` is the dict returned by ``process_month_events()``.
    """
    day_markers = processed["day_markers"]
    multi_day = processed["multi_day"]

    img = Image.new("RGB", (_CANVAS_W, _CANVAS_H), _WHITE)
    draw = ImageDraw.Draw(img)

    font_header = _load_font(22, bold=True)
    font_day_name = _load_font(13, bold=True)
    font_day_num = _load_font(14)
    font_day_num_bold = _load_font(14, bold=True)
    font_bar = _load_font(10)
    font_legend = _load_font(12)

    # ── Header ───────────────────────────────────────────────────────────────
    draw.rectangle(
        [_PAD, _PAD, _CANVAS_W - _PAD, _PAD + _HEADER_H], fill=_HEADER_BG
    )
    month_name = cal_mod.month_name[month]
    header_text = f"{month_name} {year}"
    bbox = font_header.getbbox(header_text)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((_CANVAS_W - tw) / 2, _PAD + 12),
        header_text,
        fill=_HEADER_TEXT,
        font=font_header,
    )

    # ── Day-of-week names ────────────────────────────────────────────────────
    day_names_y = _PAD + _HEADER_H
    draw.rectangle(
        [_PAD, day_names_y, _CANVAS_W - _PAD, day_names_y + _DAY_NAMES_H],
        fill=_DAY_NAME_BG,
    )
    for col, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        cx = _PAD + col * _CELL_W + _CELL_W // 2
        bbox = font_day_name.getbbox(name)
        nw = bbox[2] - bbox[0]
        draw.text(
            (cx - nw // 2, day_names_y + 7),
            name,
            fill=_DAY_NAME_TEXT,
            font=font_day_name,
        )

    # ── Grid cells ───────────────────────────────────────────────────────────
    grid = _build_grid(year, month)

    for row_idx, week in enumerate(grid):
        for col_idx, (day, in_month) in enumerate(week):
            x1, y1, x2, y2 = _cell_box(row_idx, col_idx)

            # Cell background
            is_today = (
                in_month
                and today.year == year
                and today.month == month
                and today.day == day
            )
            if is_today:
                draw.rectangle([x1, y1, x2, y2], fill=_TODAY_BG)

            # Cell border
            draw.rectangle([x1, y1, x2, y2], outline=_CELL_BORDER, width=1)

            # Day number
            num_str = str(day)
            color = _DAY_NUM if in_month else _DAY_NUM_OUTSIDE
            num_font = font_day_num_bold if is_today else font_day_num
            if is_today:
                # Draw a circle behind the day number
                bbox = num_font.getbbox(num_str)
                nw = bbox[2] - bbox[0]
                nh = bbox[3] - bbox[1]
                cx = x1 + 18
                cy = y1 + 16
                r = max(nw, nh) // 2 + 5
                draw.ellipse(
                    [cx - r, cy - r, cx + r, cy + r], fill=_TODAY_RING
                )
                draw.text(
                    (cx - nw // 2, cy - nh // 2 - 1),
                    num_str,
                    fill=_WHITE,
                    font=num_font,
                )
            else:
                draw.text(
                    (x1 + 8, y1 + 6), num_str, fill=color, font=font_day_num
                )

            # Event dots (only for in-month days)
            if in_month:
                d = datetime.date(year, month, day)
                markers = day_markers.get(d)
                if markers:
                    dot_y = y1 + 34
                    dots: list[tuple] = []
                    if markers["recurring"]:
                        dots.append(_RECURRING)
                    if markers["one_time"]:
                        dots.append(_ONE_TIME)
                    total_w = len(dots) * (_DOT_R * 2) + (len(dots) - 1) * 6
                    start_x = x1 + (_CELL_W - total_w) // 2
                    for i, clr in enumerate(dots):
                        cx = start_x + i * (_DOT_R * 2 + 6) + _DOT_R
                        draw.ellipse(
                            [
                                cx - _DOT_R,
                                dot_y - _DOT_R,
                                cx + _DOT_R,
                                dot_y + _DOT_R,
                            ],
                            fill=clr,
                        )

    # ── Multi-day bars ───────────────────────────────────────────────────────
    bar_segments = _assign_bar_lanes(multi_day, year, month, grid)
    for seg in bar_segments:
        lane = seg.get("lane", 0)
        if lane > 1:
            continue  # max 2 bar lanes per row
        x1_cell, y1_cell, _, _ = _cell_box(seg["row"], seg["col_start"])
        _, _, x2_cell, _ = _cell_box(seg["row"], seg["col_end"])

        bar_y = y1_cell + 46 + lane * (_BAR_H + _BAR_GAP)
        bar_color = _BAR_RECURRING if seg["is_recurring"] else _BAR_ONE_TIME
        draw.rounded_rectangle(
            [x1_cell + 3, bar_y, x2_cell - 3, bar_y + _BAR_H],
            radius=4,
            fill=bar_color,
        )
        # Bar label (clipped to bar width)
        bar_w = (x2_cell - 3) - (x1_cell + 3)
        if bar_w > 30:
            label = seg["summary"]
            bbox = font_bar.getbbox(label)
            tw = bbox[2] - bbox[0]
            if tw > bar_w - 8:
                # Truncate
                while tw > bar_w - 14 and len(label) > 1:
                    label = label[:-1]
                    bbox = font_bar.getbbox(label)
                    tw = bbox[2] - bbox[0]
                label += "…"
            draw.text(
                (x1_cell + 7, bar_y + 1),
                label,
                fill=_BAR_TEXT,
                font=font_bar,
            )

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_y = _PAD + _HEADER_H + _DAY_NAMES_H + _CELL_H * _ROWS + 8

    # Recurring dot + label
    lx = _PAD + 10
    draw.ellipse(
        [lx, legend_y + 4, lx + 10, legend_y + 14], fill=_RECURRING
    )
    draw.text(
        (lx + 16, legend_y + 1), "Recurring", fill=_LEGEND_TEXT, font=font_legend
    )

    # One-time dot + label
    lx2 = _PAD + 120
    draw.ellipse(
        [lx2, legend_y + 4, lx2 + 10, legend_y + 14], fill=_ONE_TIME
    )
    draw.text(
        (lx2 + 16, legend_y + 1), "One-time", fill=_LEGEND_TEXT, font=font_legend
    )

    # ── Export ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
