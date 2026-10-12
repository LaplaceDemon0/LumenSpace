"""Wavelet reading: dominant cycle vs red noise, energy bursts, cycle phase."""

import numpy as np

from terminal import wavelet_analysis as wa

DT = 1.0
MORLET_CENTER = 0.8125


def make_cwt(n, scales):
    """Real Morlet CWT in numpy (same wavelet and scale/period relation as pywt 'morl')."""
    grid = np.arange(-4 * int(max(scales)) - 8, 4 * int(max(scales)) + 9, dtype=float)

    def cwt(x):
        rows = []
        for s in scales:
            u = grid / s
            psi = np.exp(-(u**2) / 2) * np.cos(5 * u) / np.sqrt(s)
            full = np.convolve(np.asarray(x, float), psi, mode="full")
            start = (len(psi) - 1) // 2
            rows.append(full[start : start + len(x)])
        return np.array(rows)

    return cwt


def run(x, scales=None):
    n = len(x)
    scales = np.arange(1, min(64, n // 2) + 1) if scales is None else scales
    cwt = make_cwt(n, scales)
    period = scales / MORLET_CENTER * DT
    times = (1_700_000_000 + np.arange(n) * 60).tolist()
    z = (x - x.mean()) / x.std()
    wa._BACKGROUND.clear()
    return wa.analyse(z, times, DT, cwt(z), period, cwt, key="test"), times


def test_cycle_is_found_and_stands_above_red_noise():
    rng = np.random.default_rng(3)
    t = np.arange(84)
    x = np.sin(2 * np.pi * t / 9) + 0.25 * rng.standard_normal(84) + 0.01 * t
    out, _ = run(x)
    d = out["dominant"]
    assert abs(d["period"] - 9) / 9 < 0.2
    assert d["significant"] and d["strength"] > 0.5
    assert d["cycles_in_window"] > 8


def test_random_walk_is_rarely_called_a_cycle():
    hits = 0
    for seed in range(6):
        x = np.cumsum(np.random.default_rng(seed).standard_normal(84))
        out, _ = run(x)
        hits += out["dominant"]["significant"]
    assert hits <= 1  # ~5% false-positive target, a little slack for 6 seeds


def test_phase_marks_and_next_turn_match_a_known_cosine():
    n, period, crest0 = 70, 12.0, 5.0  # last bar index 69 -> falling, trough at index 71
    t = np.arange(n)
    x = np.cos(2 * np.pi * (t - crest0) / period) + 0.05 * np.random.default_rng(0).standard_normal(n)
    out, times = run(x)
    assert abs(out["dominant"]["period"] - period) < 0.7
    crests = [m["time"] for m in out["marks"] if m["kind"] == "crest" and not m["projected"]]
    expected = [times[0] + (crest0 + k * period) * 60 for k in range(7)]
    assert len(crests) >= 4
    for c in crests:
        assert min(abs(c - e) for e in expected) <= 90  # within 1.5 minutes
    ph = out["phase"]
    assert ph["state"] == "falling" and ph["next_turn"] == "trough"
    assert abs(ph["next_turn_time"] - (times[0] + 71 * 60)) <= 90
    assert all(m["time"] > times[-1] for m in out["marks"] if m["projected"])


def test_energy_burst_is_located_and_fading_is_reported():
    n = 120
    t = np.arange(n)
    env = np.exp(-((t - 35) ** 2) / (2 * 8**2))
    x = env * np.sin(2 * np.pi * t / 8) + 0.05 * np.random.default_rng(5).standard_normal(n)
    out, times = run(x)
    burst = out["energy"]["bursts"][0]
    assert burst["start"] - 120 <= times[35] <= burst["end"] + 120
    assert out["energy"]["trend"] == "fading"


def test_short_window_reports_why_it_is_unavailable():
    x = np.cumsum(np.random.default_rng(1).standard_normal(10))
    out, _ = run(x)
    assert out["available"] is False and "short" in out["reason"].lower()
