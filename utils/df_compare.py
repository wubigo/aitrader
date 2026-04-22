import pandas as pd

f1 = "future_expires.csv"
f2 = "date-ic-all.csv"
df1 = pd.read_csv(f1)
df2 = pd.read_csv(f2)
df1["datetime"] = pd.to_datetime(df1["datetime"], errors="coerce").dt.tz_localize(None)
df2["date"] = pd.to_datetime(df2["date"], errors="coerce").dt.tz_localize(None)
m = df1[["datetime", "KQ.m@CFFEX.IC"]].dropna().copy()
m["date"] = m["datetime"].dt.normalize()
x = df2[["date", "KQ.m@CFFEX.IC"]].dropna().copy()
x["date"] = x["date"].dt.normalize()
merged = m.merge(x, on="date", how="inner", suffixes=("_f1", "_f2"))
merged["equal"] = merged["KQ.m@CFFEX.IC_f1"].astype(str) == merged[
    "KQ.m@CFFEX.IC_f2"
].astype(str)
out = merged[["date", "KQ.m@CFFEX.IC_f1", "KQ.m@CFFEX.IC_f2", "equal"]].copy()
out["date"] = out["date"].dt.strftime("%Y-%m-%d")
out.to_csv("kq_compare_by_date.csv", index=False)
summary = pd.DataFrame(
    {
        "matched_dates": [len(out)],
        "equal_count": [int(out["equal"].sum())],
        "different_count": [int((~out["equal"]).sum())],
        "all_equal": [bool(out["equal"].all()) if len(out) > 0 else False],
    }
)
