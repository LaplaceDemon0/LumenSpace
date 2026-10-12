"""Exploratory embedding helpers, deliberately unavailable on tiny windows."""

import numpy as np
from scipy.spatial.distance import cdist
from sklearn.metrics import mutual_info_score


def estimate(x):
    if len(x) < 100:
        raise ValueError("Embedding helpers need at least 100 bars. Select a longer range.")
    bins = np.unique(np.quantile(x, np.linspace(0, 1, 13)))
    digitized = np.digitize(x, bins[1:-1])
    lags = list(range(1, min(33, len(x) // 4)))
    information = [float(mutual_info_score(digitized[:-lag], digitized[lag:])) for lag in lags]
    minima = [
        i
        for i in range(1, len(information) - 1)
        if information[i] < information[i - 1] and information[i] < information[i + 1]
    ]
    tau = lags[minima[0]] if minima else lags[int(np.argmin(information))]
    dimensions, ratios = [], []
    for m in range(1, 7):
        count = len(x) - m * tau
        if count < 10:
            break
        cloud = np.column_stack([x[j * tau : j * tau + count] for j in range(m)])
        distance = cdist(cloud, cloud)
        temporal = abs(np.arange(count)[:, None] - np.arange(count)[None, :])
        distance[temporal <= tau] = np.inf
        neighbor = np.argmin(distance, axis=1)
        d = distance[np.arange(count), neighbor]
        extra = abs(x[m * tau : m * tau + count] - x[m * tau + neighbor])
        false = (extra / np.maximum(d, 1e-12) > 10) | (
            np.sqrt(d * d + extra * extra) / max(np.std(x), 1e-12) > 2
        )
        dimensions.append(m)
        ratios.append(float(false.mean()))
    recommended = next((m for m, r in zip(dimensions, ratios) if r < 0.05), dimensions[-1])
    return {
        "lags": lags,
        "mutual_information": information,
        "dimensions": dimensions,
        "false_neighbor_fraction": ratios,
        "suggested_tau": tau,
        "suggested_dimension": max(2, recommended),
        "note": "Histogram mutual information and thresholded false neighbors are exploratory. Validate across longer independent windows.",
    }
