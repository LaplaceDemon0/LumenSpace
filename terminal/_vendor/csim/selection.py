def select_sources(features, rules, n, L, include_launch=False, cap=200):
    stop = n + 1 if include_launch else n
    # Ages 1..L; including launch adds age 0 without dropping the oldest source.
    f = features.iloc[max(0, n - L) : stop]
    mask = (f["range"] > 0) & f.selection_scale.gt(0) & f.range_ratio.ge(rules.range_min)
    for name in ("body", "upper", "lower"):
        mask &= f[name + "_pct"].between(
            getattr(rules, name + "_min"), getattr(rules, name + "_max")
        )
    if rules.direction != "any":
        mask &= f.direction.eq(1 if rules.direction == "bullish" else -1)
    chosen = f[mask]
    if getattr(rules, "top_n", 0) and len(chosen) > rules.top_n:
        # Significance filter: strongest candles by range relative to the prior scale (ties: newest).
        chosen = (
            chosen.assign(_pos=range(len(chosen)))
            .sort_values(["range_ratio", "_pos"], ascending=False)
            .head(rules.top_n)
        )
        return sorted(chosen.index.tolist())[-cap:]
    return chosen.index.tolist()[-cap:]
