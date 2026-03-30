import subprocess
import re
import time
import math

try:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Rectangle
    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False

def get_wifi_signal_power():
    try:
        # Run system_profiler to get WiFi info
        result = subprocess.run(
            ['system_profiler', 'SPAirPortDataType'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Parse the output to find signal power
        for line in result.stdout.split('\n'):
            if 'Signal / Noise:' in line:
                # Extract the signal strength (first dBm value)
                match = re.search(r'(-\d+)\s+dBm', line)
                if match:
                    return int(match.group(1))
        
        return None
        
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_distance_label(signal_dbm):
    """Return simple wording for current estimated proximity."""
    if signal_dbm >= -50:
        return "Close"
    if signal_dbm >= -70:
        return "Moderately far"
    if signal_dbm >= -85:
        return "Far"
    return "Very far / signal lost"


def estimate_distance_meters(signal_dbm, tx_power_at_1m=-40, path_loss_exponent=3.0):
    """Estimate distance from RSSI using a log-distance path loss model.

    This is a rough indoor estimate and can vary a lot with walls/obstacles.
    """
    distance_m = 10 ** ((tx_power_at_1m - signal_dbm) / (10 * path_loss_exponent))
    distance_m = max(0.3, distance_m)

    # Provide a loose uncertainty band for indoor environments.
    lower = distance_m * 0.7
    upper = distance_m * 1.5
    return distance_m, lower, upper


def estimate_router_position(
    samples,
    room_width_m,
    room_length_m,
    grid_steps=100,
    path_loss_exponent=2.4,
    min_distance_m=0.35,
    wall_margin_m=0.25,
):
    """Estimate router coordinates directly from RSSI patterns.

    We fit (x, y) by minimizing RSSI residuals, while auto-estimating signal level
    at 1m for each candidate location. This is usually more stable than converting
    each RSSI reading to meters with a fixed calibration.
    """
    if len(samples) < 3:
        return None

    margin_x = min(wall_margin_m, room_width_m / 4)
    margin_y = min(wall_margin_m, room_length_m / 4)
    x_min, x_max = margin_x, max(margin_x, room_width_m - margin_x)
    y_min, y_max = margin_y, max(margin_y, room_length_m - margin_y)

    if x_max <= x_min:
        x_min, x_max = 0.0, room_width_m
    if y_max <= y_min:
        y_min, y_max = 0.0, room_length_m

    best_xy = None
    best_error = float("inf")

    for ix in range(grid_steps + 1):
        x = x_min + (x_max - x_min) * (ix / grid_steps)
        for iy in range(grid_steps + 1):
            y = y_min + (y_max - y_min) * (iy / grid_steps)

            # For fixed (x, y), best RSSI@1m constant has closed form mean.
            a_values = []
            distances = []
            for sample in samples:
                sx, sy = sample["pos"]
                d = max(math.hypot(x - sx, y - sy), min_distance_m)
                distances.append(d)
                a_values.append(sample["signal"] + 10 * path_loss_exponent * math.log10(d))

            a_hat = sum(a_values) / len(a_values)

            err = 0.0
            for idx, sample in enumerate(samples):
                modeled_rssi = a_hat - 10 * path_loss_exponent * math.log10(distances[idx])
                err += (sample["signal"] - modeled_rssi) ** 2

            if err < best_error:
                best_error = err
                best_xy = (x, y)

    return best_xy


def _map_to_grid(x, y, room_width_m, room_length_m, grid_w, grid_h):
    gx = int(round((x / room_width_m) * (grid_w - 1))) if room_width_m > 0 else 0
    gy = int(round((y / room_length_m) * (grid_h - 1))) if room_length_m > 0 else 0
    gx = max(0, min(grid_w - 1, gx))
    gy = max(0, min(grid_h - 1, gy))
    return gx, gy


def print_room_graph(room_width_m, room_length_m, samples, estimate_xy):
    """Print an ASCII top-view map with visited corners and estimated router location."""
    grid_w = 41
    grid_h = 17

    canvas = [[" " for _ in range(grid_w)] for _ in range(grid_h)]

    for x in range(grid_w):
        canvas[0][x] = "-"
        canvas[grid_h - 1][x] = "-"
    for y in range(grid_h):
        canvas[y][0] = "|"
        canvas[y][grid_w - 1] = "|"

    canvas[0][0] = "+"
    canvas[0][grid_w - 1] = "+"
    canvas[grid_h - 1][0] = "+"
    canvas[grid_h - 1][grid_w - 1] = "+"

    for idx, sample in enumerate(samples, start=1):
        x, y = sample["pos"]
        gx, gy = _map_to_grid(x, y, room_width_m, room_length_m, grid_w, grid_h)
        gy = (grid_h - 1) - gy
        marker = str(min(idx, 9))
        canvas[gy][gx] = marker

    if estimate_xy is not None:
        ex, ey = estimate_xy
        gx, gy = _map_to_grid(ex, ey, room_width_m, room_length_m, grid_w, grid_h)
        gy = (grid_h - 1) - gy
        canvas[gy][gx] = "R"

    print("\nRoom map (top view)")
    for row in canvas:
        print("".join(row))

    print("Legend: 1..4 = measured stages, R = estimated router")


def render_room_plot(room_width_m, room_length_m, samples, estimate_xy, stage_label):
    """Render a cleaner room map using matplotlib and save it as PNG."""
    if not HAS_MATPLOTLIB:
        print("Matplotlib not available. Falling back to ASCII map.")
        print_room_graph(room_width_m, room_length_m, samples, estimate_xy)
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    # Room outline
    ax.add_patch(
        Rectangle((0, 0), room_width_m, room_length_m, fill=False, linewidth=2.0, edgecolor="#1f2937")
    )

    if samples:
        xs = [s["pos"][0] for s in samples]
        ys = [s["pos"][1] for s in samples]
        ax.plot(xs, ys, color="#2563eb", linewidth=1.6, alpha=0.8, label="Path")
        ax.scatter(xs, ys, s=40, color="#2563eb", alpha=0.9)

        # Label only stage corner points to keep chart readable.
        for sample in samples:
            if "chunk" not in sample["label"].lower():
                x, y = sample["pos"]
                label = str(sample["stage"])
                ax.text(x, y, f" {label}", fontsize=9, color="#111827", va="bottom")

    if estimate_xy is not None:
        ex, ey = estimate_xy
        ax.scatter([ex], [ey], s=140, marker="*", color="#dc2626", label="Estimated Router")
        ax.text(ex, ey, " R", fontsize=10, color="#991b1b", va="bottom")

    corners = [
        ("BR", (room_width_m, 0.0)),
        ("BL", (0.0, 0.0)),
        ("TL", (0.0, room_length_m)),
        ("TR", (room_width_m, room_length_m)),
    ]
    for name, (cx, cy) in corners:
        ax.scatter([cx], [cy], s=20, color="#111827")
        ax.text(cx, cy, f" {name}", fontsize=8, color="#374151", va="top")

    pad_x = max(room_width_m * 0.08, 0.6)
    pad_y = max(room_length_m * 0.08, 0.6)
    ax.set_xlim(-pad_x, room_width_m + pad_x)
    ax.set_ylim(-pad_y, room_length_m + pad_y)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.25)
    ax.set_xlabel("Room width (m)")
    ax.set_ylabel("Room length (m)")
    ax.set_title(f"WiFi Room Map - {stage_label}")
    ax.legend(loc="best")

    safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", stage_label.strip().lower())
    output_file = f"wifi_map_{safe_label}.png"
    fig.savefig(output_file, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved map image: {output_file}")


def read_signal_with_retries(sample_interval=2, max_retries=3):
    """Read WiFi signal with retries; return None if all attempts fail."""
    signal = get_wifi_signal_power()
    retries = 0
    while signal is None and retries < max_retries:
        print("No signal read, retrying...")
        time.sleep(sample_interval)
        signal = get_wifi_signal_power()
        retries += 1
    return signal


def prompt_turn_delta(prompt_text, default_zero=True):
    """Prompt turn angle where left is positive and right is negative."""
    while True:
        raw = input(prompt_text).strip().lower()
        if not raw:
            return 0.0 if default_zero else 90.0
        if raw in {"0", "+0", "-0"}:
            return 0.0

        m = re.match(r"^(left|right)\s+(\d+(?:\.\d+)?)$", raw)
        if not m:
            print("Invalid format. Use 'left <angle>', 'right <angle>', or '0'.")
            continue

        direction = m.group(1)
        angle = float(m.group(2))
        if angle <= 0 or angle >= 180:
            print("Angle must be between 0 and 180 degrees.")
            continue
        return angle if direction == "left" else -angle


def collect_corner_turn():
    """Ask for corner turn to set heading for the next leg."""
    print("At corner: enter turn for NEXT leg (example: left 95 or right 80).")
    return prompt_turn_delta("Corner turn: ", default_zero=False)


def collect_leg_steps(target_label, sample_interval, start_pos, start_heading_deg, chunk_length_m):
    """Collect per-done measurements and optional per-done turns (curved edges)."""
    done_chunks = 0
    done_samples = []
    cur_x, cur_y = start_pos
    cur_heading = start_heading_deg

    print(f"\nMove toward {target_label}.")
    print("Type 'done' every time you move 2 steps. Type 'corner' when you reach it.")

    while True:
        command = input("Command (done/corner): ").strip().lower()
        if command == "done":
            done_chunks += 1

            # Move one chunk along current heading.
            rad = math.radians(cur_heading)
            cur_x += chunk_length_m * math.cos(rad)
            cur_y += chunk_length_m * math.sin(rad)

            signal = read_signal_with_retries(sample_interval=sample_interval)
            if signal is None:
                print("Could not read signal for this chunk; continuing.")
            else:
                distance_m, low_m, high_m = estimate_distance_meters(signal)
                done_samples.append(
                    {
                        "chunk": done_chunks,
                        "signal": signal,
                        "pos": (cur_x, cur_y),
                        "distance_m": distance_m,
                    }
                )
                print(
                    f"Chunk {done_chunks}: {signal} dBm | {get_distance_label(signal)} | "
                    f"~{distance_m:.1f} m ({low_m:.1f}-{high_m:.1f} m)"
                )

            turn_delta = prompt_turn_delta(
                "Turn before next done? (left/right angle or 0, Enter=0): ",
                default_zero=True,
            )
            cur_heading += turn_delta
            continue

        if command == "corner":
            if done_chunks == 0:
                print("No movement recorded yet. Add at least one 'done' before 'corner'.")
                continue
            return done_samples, (cur_x, cur_y), cur_heading

        print("Invalid input. Use only 'done' or 'corner'.")


def normalize_geometry(samples, corner_positions):
    """Shift coordinates to positive space for plotting/estimation."""
    points = [s["pos"] for s in samples] + list(corner_positions.values())
    min_x = min(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_x = max(p[0] for p in points)
    max_y = max(p[1] for p in points)

    norm_samples = []
    for s in samples:
        ns = dict(s)
        ns["pos"] = (s["pos"][0] - min_x, s["pos"][1] - min_y)
        norm_samples.append(ns)

    norm_corners = {}
    for k, (x, y) in corner_positions.items():
        norm_corners[k] = (x - min_x, y - min_y)

    width = max(1.0, max_x - min_x)
    length = max(1.0, max_y - min_y)
    return norm_samples, norm_corners, width, length


def ensure_four_corners(corner_positions):
    """Fill missing corner ids for plotting at early stages."""
    if not corner_positions:
        return {1: (0.0, 0.0), 2: (0.0, 0.0), 3: (0.0, 0.0), 4: (0.0, 0.0)}

    last_key = max(corner_positions.keys())
    last_pos = corner_positions[last_key]
    full = dict(corner_positions)
    for k in range(1, 5):
        if k not in full:
            full[k] = last_pos
    return full


def estimate_room_dimensions(leg_lengths_m):
    """Estimate width/length from traversed edge lengths."""
    width_candidates = []
    length_candidates = []

    if len(leg_lengths_m) >= 1:
        width_candidates.append(leg_lengths_m[0])
    if len(leg_lengths_m) >= 3:
        width_candidates.append(leg_lengths_m[2])
    if len(leg_lengths_m) >= 2:
        length_candidates.append(leg_lengths_m[1])

    if width_candidates:
        width_m = sum(width_candidates) / len(width_candidates)
    elif length_candidates:
        width_m = length_candidates[0]
    else:
        width_m = 4.0

    if length_candidates:
        length_m = sum(length_candidates) / len(length_candidates)
    elif width_candidates:
        length_m = width_candidates[0]
    else:
        length_m = 4.0

    width_m = max(width_m, 1.0)
    length_m = max(length_m, 1.0)
    return width_m, length_m


def build_corner_positions_from_path(leg_lengths_m, turn_angles_deg, initial_heading_deg=180.0):
    """Build corner coordinates from measured leg lengths and turn angles.

    - leg_lengths_m: length of each traversed edge (C1->C2, C2->C3, ...)
    - turn_angles_deg: signed turn at each intermediate corner (+left, -right)
    """
    # Always build a full 4-corner frame so plotting/labels work at every stage.
    full_legs = list(leg_lengths_m[:3])
    while len(full_legs) < 3:
        full_legs.append(4.0)

    full_turns = list(turn_angles_deg[:2])
    while len(full_turns) < 2:
        full_turns.append(90.0)

    points = [(0.0, 0.0)]  # C1 start
    heading_deg = initial_heading_deg

    for idx, leg_m in enumerate(full_legs):
        px, py = points[-1]
        rad = math.radians(heading_deg)
        nx = px + leg_m * math.cos(rad)
        ny = py + leg_m * math.sin(rad)
        points.append((nx, ny))

        if idx < len(full_turns):
            heading_deg += full_turns[idx]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, min_y = min(xs), min(ys)
    max_x, max_y = max(xs), max(ys)

    shifted = [(x - min_x, y - min_y) for (x, y) in points]
    corner_positions = {i + 1: shifted[i] for i in range(4)}
    plot_width = max(1.0, max_x - min_x)
    plot_length = max(1.0, max_y - min_y)
    return corner_positions, plot_width, plot_length


def get_corner_positions_from_measurements(leg_lengths_m):
    """Build corner coordinates directly from measured edge lengths."""
    bottom_width = leg_lengths_m[0] if len(leg_lengths_m) >= 1 else 4.0
    left_height = leg_lengths_m[1] if len(leg_lengths_m) >= 2 else 4.0
    top_width = leg_lengths_m[2] if len(leg_lengths_m) >= 3 else bottom_width

    bottom_width = max(bottom_width, 1.0)
    left_height = max(left_height, 1.0)
    top_width = max(top_width, 1.0)

    corner_positions = {
        1: (bottom_width, 0.0),
        2: (0.0, 0.0),
        3: (0.0, left_height),
        4: (top_width, left_height),
    }

    plot_width = max(bottom_width, top_width)
    plot_length = left_height
    return corner_positions, plot_width, plot_length


def get_stage_start_and_prev_heading(leg_lengths_m, turn_angles_deg, move_idx, initial_heading_deg=180.0):
    """Return current leg start point and incoming heading before this stage's turn."""
    completed_legs = max(0, move_idx - 2)
    x, y = 0.0, 0.0
    heading_deg = initial_heading_deg

    for leg_i in range(completed_legs):
        leg_m = leg_lengths_m[leg_i]
        rad = math.radians(heading_deg)
        x += leg_m * math.cos(rad)
        y += leg_m * math.sin(rad)
        if leg_i < len(turn_angles_deg):
            heading_deg += turn_angles_deg[leg_i]

    return (x, y), heading_deg


def infer_turn_angle_from_signals(
    done_signals,
    corner_signal,
    start_pos,
    prev_heading_deg,
    leg_m,
    done_chunks,
    router_estimate,
):
    """Infer turn angle by matching measured done/corner distances to router distance model."""
    if router_estimate is None or done_chunks <= 0:
        return 90.0

    rx, ry = router_estimate
    measured_signals = list(done_signals) + [corner_signal]
    measured_distances = [estimate_distance_meters(s)[0] for s in measured_signals]
    fractions = [i / done_chunks for i in range(1, done_chunks + 1)] + [1.0]

    best_angle = 90.0
    best_error = float("inf")

    for candidate_turn in range(-150, 151, 2):
        if abs(candidate_turn) < 20:
            continue

        heading_deg = prev_heading_deg + candidate_turn
        rad = math.radians(heading_deg)
        err = 0.0

        for frac, meas_d in zip(fractions, measured_distances):
            px = start_pos[0] + leg_m * frac * math.cos(rad)
            py = start_pos[1] + leg_m * frac * math.sin(rad)
            modeled_d = max(0.1, math.hypot(px - rx, py - ry))
            err += (modeled_d - meas_d) ** 2

        if err < best_error:
            best_error = err
            best_angle = float(candidate_turn)

    return best_angle


def update_sample_positions(samples, corner_positions):
    """Re-anchor corner/chunk sample positions to measured corner geometry."""

    for sample in samples:
        stage = sample.get("stage")
        if stage not in corner_positions:
            continue

        label = sample.get("label", "").lower()
        if "chunk" in label and "frac" in sample and (stage - 1) in corner_positions:
            start_x, start_y = corner_positions[stage - 1]
            end_x, end_y = corner_positions[stage]
            frac = max(0.0, min(1.0, float(sample["frac"])))
            sample["pos"] = (
                start_x + (end_x - start_x) * frac,
                start_y + (end_y - start_y) * frac,
            )
        else:
            sample["pos"] = corner_positions[stage]


def print_corner_distances_to_router(estimate_xy, room_width_m, room_length_m):
    """Print estimated router distance from each room corner."""
    if estimate_xy is None:
        print("Corner distances: router estimate not available yet.")
        return

    ex, ey = estimate_xy
    corners = [
        ("Bottom-right (start)", (room_width_m, 0.0)),
        ("Bottom-left", (0.0, 0.0)),
        ("Top-left", (0.0, room_length_m)),
        ("Top-right", (room_width_m, room_length_m)),
    ]
    print("Estimated distance from each corner to router:")
    for name, (cx, cy) in corners:
        dist = math.hypot(ex - cx, ey - cy)
        print(f"- {name}: ~{dist:.1f} m")


def render_room_plot_measured(corner_positions, plot_width_m, plot_length_m, samples, estimate_xy, stage_label):
    """Render map using measured corner geometry and sample spacing."""
    if not HAS_MATPLOTLIB:
        print("Matplotlib not available. Falling back to ASCII map.")
        print_room_graph(plot_width_m, plot_length_m, samples, estimate_xy)
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    c1 = corner_positions[1]
    c2 = corner_positions[2]
    c3 = corner_positions[3]
    c4 = corner_positions[4]
    room_poly = [c2, c1, c4, c3]

    ax.add_patch(
        Polygon(room_poly, closed=True, fill=False, linewidth=2.0, edgecolor="#1f2937")
    )

    if samples:
        xs = [s["pos"][0] for s in samples]
        ys = [s["pos"][1] for s in samples]
        ax.plot(xs, ys, color="#2563eb", linewidth=1.6, alpha=0.8, label="Path")
        ax.scatter(xs, ys, s=40, color="#2563eb", alpha=0.9)

        for sample in samples:
            if "chunk" not in sample["label"].lower():
                x, y = sample["pos"]
                label = str(sample["stage"])
                ax.text(x, y, f" {label}", fontsize=9, color="#111827", va="bottom")

    if estimate_xy is not None:
        ex, ey = estimate_xy
        ax.scatter([ex], [ey], s=140, marker="*", color="#dc2626", label="Estimated Router")
        ax.text(ex, ey, " R", fontsize=10, color="#991b1b", va="bottom")

    corners = [
        ("C1", c1),
        ("C2", c2),
        ("C3", c3),
        ("C4", c4),
    ]
    for name, (cx, cy) in corners:
        ax.scatter([cx], [cy], s=20, color="#111827")
        ax.text(cx, cy, f" {name}", fontsize=8, color="#374151", va="top")

    pad_x = max(plot_width_m * 0.08, 0.6)
    pad_y = max(plot_length_m * 0.08, 0.6)
    ax.set_xlim(-pad_x, plot_width_m + pad_x)
    ax.set_ylim(-pad_y, plot_length_m + pad_y)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.25)
    ax.set_xlabel("X distance (m)")
    ax.set_ylabel("Y distance (m)")
    ax.set_title(f"WiFi Measured Map - {stage_label}")
    ax.legend(loc="best")

    safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", stage_label.strip().lower())
    output_file = f"wifi_map_{safe_label}.png"
    fig.savefig(output_file, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved map image: {output_file}")


def print_corner_distances_to_router_measured(estimate_xy, corner_positions):
    """Print estimated router distance from each measured corner."""
    if estimate_xy is None:
        print("Corner distances: router estimate not available yet.")
        return

    ex, ey = estimate_xy
    corners = [
        ("Corner 1 (start-right)", corner_positions[1]),
        ("Corner 2", corner_positions[2]),
        ("Corner 3", corner_positions[3]),
        ("Corner 4", corner_positions[4]),
    ]
    print("Estimated distance from each corner to router:")
    for name, (cx, cy) in corners:
        dist = math.hypot(ex - cx, ey - cy)
        print(f"- {name}: ~{dist:.1f} m")


if __name__ == "__main__":
    sample_interval = 2
    step_length_m = 0.70
    steps_per_done = 2

    print("WiFi room mapping mode")
    print("Start from the RIGHT corner of the room.")
    print("Use only 'done' and 'corner' during movement stages.")
    print("No room-size input needed; room dimensions are estimated from your steps.\n")

    print("Stage 1/4: At RIGHT corner (start)")
    print("Type 'corner' when you are at the starting right corner.")
    while input("Command (corner): ").strip().lower() != "corner":
        print("Please type 'corner' when you are ready at the start corner.")

    start_signal = read_signal_with_retries(sample_interval=sample_interval)
    if start_signal is None:
        print("Could not get start signal. Exiting.")
        exit(1)

    start_distance, start_low, start_high = estimate_distance_meters(start_signal)
    chunk_length_m = step_length_m * steps_per_done
    current_pos = (0.0, 0.0)
    current_heading_deg = 180.0
    corner_positions = {1: current_pos}

    samples = [
        {
            "stage": 1,
            "label": "Right corner (start)",
            "pos": current_pos,
            "signal": start_signal,
            "distance_m": start_distance,
        }
    ]

    # Planned sequence from user request:
    # right corner -> opposite corner -> next corner -> opposite corner
    movement_targets = [
        "OPPOSITE corner",
        "NEXT corner",
        "OPPOSITE corner",
    ]

    full_corners = ensure_four_corners(corner_positions)
    norm_samples, norm_corners, room_width_m, room_length_m = normalize_geometry(samples, full_corners)
    estimate_xy = estimate_router_position(norm_samples, room_width_m, room_length_m)
    print(
        f"Stage 1 reading: {start_signal} dBm | {get_distance_label(start_signal)} | "
        f"~{start_distance:.1f} m ({start_low:.1f}-{start_high:.1f} m)"
    )
    render_room_plot_measured(
        norm_corners,
        room_width_m,
        room_length_m,
        norm_samples,
        estimate_xy,
        "stage_1_start",
    )

    for move_idx, target in enumerate(movement_targets, start=2):
        done_samples, current_pos, current_heading_deg = collect_leg_steps(
            target,
            sample_interval=sample_interval,
            start_pos=current_pos,
            start_heading_deg=current_heading_deg,
            chunk_length_m=chunk_length_m,
        )

        signal = read_signal_with_retries(sample_interval=sample_interval)

        if signal is None:
            print("Failed to read signal at this stage. Skipping this point.")
            continue

        distance_m, low_m, high_m = estimate_distance_meters(signal)

        # Add intermediate samples measured at each 'done' chunk with true walked positions.
        for chunk in done_samples:
            samples.append(
                {
                    "stage": move_idx,
                    "label": f"{target} chunk {chunk['chunk']}",
                    "pos": chunk["pos"],
                    "signal": chunk["signal"],
                    "distance_m": chunk["distance_m"],
                }
            )

        corner_positions[move_idx] = current_pos

        samples.append(
            {
                "stage": move_idx,
                "label": target,
                "pos": current_pos,
                "signal": signal,
                "distance_m": distance_m,
            }
        )

        full_corners = ensure_four_corners(corner_positions)
        norm_samples, norm_corners, room_width_m, room_length_m = normalize_geometry(samples, full_corners)
        estimate_xy = estimate_router_position(norm_samples, room_width_m, room_length_m)

        print(
            f"Stage {move_idx} reading: {signal} dBm | {get_distance_label(signal)} | "
            f"~{distance_m:.1f} m ({low_m:.1f}-{high_m:.1f} m)"
        )
        print(
            f"Estimated room size so far: width ~{room_width_m:.1f} m, "
            f"length ~{room_length_m:.1f} m"
        )

        if estimate_xy is not None:
            ex, ey = estimate_xy
            user_x, user_y = norm_corners[move_idx]
            from_you = math.hypot(ex - user_x, ey - user_y)
            print(
                f"Current router estimate: x={ex:.2f} m, y={ey:.2f} m | "
                f"~{from_you:.1f} m from your current corner"
            )
        else:
            print("Current router estimate: need at least 3 measured points.")

        print_corner_distances_to_router_measured(estimate_xy, norm_corners)
        render_room_plot_measured(
            norm_corners,
            room_width_m,
            room_length_m,
            norm_samples,
            estimate_xy,
            f"stage_{move_idx}",
        )

        if move_idx < 4:
            corner_turn = collect_corner_turn()
            current_heading_deg += corner_turn

    print("\nMapping complete.")
    if len(samples) < 3:
        print("Not enough measurements to estimate router position.")
    else:
        full_corners = ensure_four_corners(corner_positions)
        norm_samples, norm_corners, room_width_m, room_length_m = normalize_geometry(samples, full_corners)
        final_est = estimate_router_position(norm_samples, room_width_m, room_length_m)
        if final_est is None:
            print("Could not determine router position.")
        else:
            ex, ey = final_est
            print(f"Final router estimate: x={ex:.2f} m, y={ey:.2f} m")
            print("Use this as a rough estimate; walls and reflections can shift RSSI-based distance.")
            render_room_plot_measured(
                norm_corners,
                room_width_m,
                room_length_m,
                norm_samples,
                final_est,
                "final",
            )