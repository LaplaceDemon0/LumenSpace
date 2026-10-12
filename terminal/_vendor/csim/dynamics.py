import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp


def simulate(surface, launch, cfg):
    def rhs(x, s):
        y, v, q = s
        return [v, float(surface.force(x, y)) - cfg.damping * v + q, -q / cfg.tau]

    sol = solve_ivp(
        rhs,
        (0, cfg.horizon),
        [launch.y0, launch.v0, launch.q0],
        rtol=cfg.rtol,
        atol=cfg.atol,
        max_step=cfg.max_step,
        dense_output=True,
    )
    if not sol.success:
        raise RuntimeError(f"Solver failed: {sol.message}")
    x = np.linspace(0, cfg.horizon, cfg.horizon * cfg.samples_per_bar + 1)
    y, v, q = sol.sol(x)
    force = surface.force(x, y)
    result = pd.DataFrame(
        {
            "x": x,
            "y": y,
            "price": launch.price + launch.scale * y,
            "velocity": v,
            "acceleration": force - cfg.damping * v + q,
            "q": q,
            "Z": surface.z(x, y),
            "force": force,
        }
    )
    if not np.isfinite(result.to_numpy()).all():
        raise RuntimeError("Simulation diverged")
    return result
