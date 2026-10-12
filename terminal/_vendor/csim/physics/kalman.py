import numpy as np


def filter_state(closes, measurement_noise=0.02, process_noise=0.01):
    """Causal constant-acceleration filter; returned covariance is in normalized units."""
    F = np.array([[1, 1, 0.5], [0, 1, 1], [0, 0, 1.0]])
    H = np.array([[1.0, 0, 0]])
    mean, cov = np.array([closes[0], 0.0, 0.0]), np.eye(3)
    Q = process_noise * np.eye(3)
    for p in closes:
        mean, cov = F @ mean, F @ cov @ F.T + Q
        K = cov @ H.T / float((H @ cov @ H.T)[0, 0] + measurement_noise)
        mean += K[:, 0] * (p - mean[0])
        # Joseph form preserves symmetry and positive semidefiniteness.
        J = np.eye(3) - K @ H
        cov = J @ cov @ J.T + measurement_noise * K @ K.T
    return mean, cov
