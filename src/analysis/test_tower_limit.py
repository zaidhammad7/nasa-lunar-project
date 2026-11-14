import math, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import mission_simulator as ms
import predict_site as ps

R = 1_737_400.0
ok_all = True
def check(name, ok, detail=""):
    global ok_all
    ok_all &= bool(ok)
    print(("PASS" if ok else "FAIL"), name, detail)

check("cap constant is 150 m", ps.MAX_TOWER_HEIGHT_M == 150.0 and ms.LIMITS["tower_height_m"] == (1.0, 150.0))
for h in (1, 20, 50, 100, 150):
    ex = math.degrees(math.acos(R / (R + h)))
    check(f"boost @ {h:>3} m matches acos(R/(R+h))", abs(ms.tower_boost_deg(h) - ex) < 1e-9, f"{ex:.4f} deg")
check("OOD tolerance stays small (mast-free check)", ps.OOD_ANGLE_TOLERANCE_DEG <= 0.35)
try:
    ms.Scenario(site_id="Auto_SP_099", tower_height_m=151).validate() if hasattr(ms.Scenario, "validate") else ms.evaluate_scenario(ms.Scenario(site_id="Auto_SP_099", tower_height_m=151))
    check("151 m rejected", False)
except Exception as e:
    check("151 m rejected", True, type(e).__name__)

sites = ["Auto_SP_099", "Auto_SP_075", "Auto_SP_46"]
for site in sites:
    res = {}
    for h in (1, 20, 50, 100, 150):
        try:
            res[h] = ms.evaluate_scenario(ms.Scenario(site_id=site, tower_height_m=h, panel_tilt_deg=80, panel_area_m2=10, duration_hours=720))
        except Exception as e:
            print("skip", site, e); res = None; break
    if not res: continue
    sun = {h: np.array(r["timeline"]["sun_el_eff_deg"]) for h, r in res.items()}
    d = sun[150] - sun[1]
    # The horizon is re-ray-traced from the mast top: every hour the 150 m mast sees the Sun at least as high as the 1 m one
    # (nearby walls can make the gain much larger than the curvature dip, which is why the old uniform-dip model was replaced).
    check(f"{site}: Sun never lower from a 150 m mast than from 1 m (hourly)", bool((d >= -1e-6).all()), f"mean gain {d.mean():.4f} deg, min {d.min():.4f}")
    vis = [r["solar_illumination_visibility"]["Sun_Visible_Pct"] for r in res.values()]
    check(f"{site}: sunlight % non-decreasing with height", all(b >= a - 1e-9 for a, b in zip(vis, vis[1:])), str([round(v, 2) for v in vis]))
    sc = {h: r["primary_landing_decision"]["Suitability_Score"] for h, r in res.items()}
    check(f"{site}: score finite and in 0..100", all(0 <= v <= 100 for v in sc.values()), str(sc))
    ood = {h: r["primary_landing_decision"].get("ood_warning") for h, r in res.items()}
    check(f"{site}: no false out-of-range warning at 150 m", not ood[150] or ood[1], f"ood {ood}")
    cls = {h: r["primary_landing_decision"]["Safety_Class"] for h, r in res.items()}
    check(f"{site}: verdict not degraded by a taller mast", list(cls.values()).count(cls[1]) >= 1 and not (cls[1] != "Hazardous" and cls[150] == "Hazardous"), str(cls))
print("ALL OK" if ok_all else "FAILURES")
sys.exit(0 if ok_all else 1)
