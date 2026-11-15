"""NASA POWER daily -> canonical OrbitFarm observations.

Explicitly historical, not a future forecast. API fetching occurs only when
called at runtime with internet access, never while preparing the demo.
"""
from __future__ import annotations
import json
from datetime import date
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT="https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETERS = ("T2M", "T2M_MAX", "T2M_MIN", "RH2M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN")
MAPPING = {
 "T2M": ("CLIM_001", "°C", "mean_daily_mean_over_period", "mean"),
 "T2M_MIN": ("CLIM_002", "°C", "minimum_daily_minimum_over_period", "min"),
 "T2M_MAX": ("CLIM_003", "°C", "maximum_daily_maximum_over_period", "max"),
 "RH2M": ("CLIM_008", "%", "mean_daily_mean_over_period", "mean"),
 "PRECTOTCORR": ("CLIM_007", "mm per period", "sum_daily_precipitation_over_period", "sum"),
 "ALLSKY_SFC_SW_DWN": ("CLIM_009", "MJ/m²/day", "mean_daily_total_over_period", "mean")
}

def power_url(lat: float, lon:float, start:str, end:str)->str:
    s=date.fromisoformat(start);e=date.fromisoformat(end)
    if s > e or e >= date.today():
        raise ValueError("Use a historical date range ending before today")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Coordinates out of bounds")
    query=urlencode({"latitude":lat,"longitude":lon,"start":s.strftime('%Y%m%d'),
                     "end":e.strftime('%Y%m%d'),"community":"AG",
                     "parameters":",".join(PARAMETERS),"format":"JSON", "time-standard":"LST"})
    return ENDPOINT+"?"+query


def fetch_power_daily(lat:float,lon:float,start:str,end:str)->tuple[dict,str]:
    url=power_url(lat,lon,start,end)
    req=Request(url,headers={"User-Agent":"OrbitFarm-MVP/1.0 (educational NASA Space Apps prototype)"})
    with urlopen(req,timeout=35) as response:
        data=json.load(response)
    return data,url


def convert_power(payload:dict, *, lat:float,lon:float,start:str,end:str,
                  stage:str|None=None,farm_id:str="nasa_farm",source_url:str|None=None) -> dict:
    """Reshape a real NASA response or an explicitly synthetic test fixture.

    Missing values -999 are discarded. Reject wrong units rather than guessing.
    >= 90% coverage per parameter is required for a period aggregate.
    """
    values=((payload.get("properties") or {}).get("parameter") or {})
    units=(payload.get("parameters") or {})
    if not values:
        raise ValueError("NASA POWER payload lacks properties.parameter")
    expected_dates={d.strftime('%Y%m%d') for d in _date_range(date.fromisoformat(start),date.fromisoformat(end))}
    n_days=len(expected_dates)
    observations=[]; gaps=[]
    for nasa_key in PARAMETERS:
        canonical,unit,agg,method=MAPPING[nasa_key]
        src=values.get(nasa_key)
        if not isinstance(src,dict):
            gaps.append(f"NASA missing {nasa_key}")
            continue
        declared=(units.get(nasa_key) or {}).get("units")
        # AG community most commonly reports solar MJ/m²/day and precipitation mm/day.
        expected={"T2M": {"C","°C"},"T2M_MIN":{"C","°C"},
                  "T2M_MAX":{"C","°C"},"RH2M":{"%","%"},
                  "PRECTOTCORR":{"mm/day","mm d-1"},
                  "ALLSKY_SFC_SW_DWN":{"MJ/m^2/day","MJ/m²/day","MJ m-2 day-1","kW-hr/m^2/day","kWh/m²/day"}}[nasa_key]
        if declared not in expected:
            gaps.append(f"NASA {nasa_key}: unexpected or absent units {declared!r}; skipped")
            continue
        cleaned=[float(v) for k,v in src.items() if k in expected_dates and type(v) in (float,int) and v > -990]
        # Some NASA POWER community formats express surface solar radiation in kWh/m²/day.
        # Convert only when units explicitly require it: 1 kWh = 3.6 MJ.
        if nasa_key == "ALLSKY_SFC_SW_DWN" and declared in ("kW-hr/m^2/day", "kWh/m²/day"):
            cleaned = [v * 3.6 for v in cleaned]
        threshold = 1.0 if method == "sum" else 0.90
        if len(cleaned)/n_days < threshold:
            gaps.append(f"NASA {nasa_key}: {len(cleaned)}/{n_days} days; need at least {threshold:.0%} coverage")
            continue
        if method=="sum":value=sum(cleaned)
        elif method=="min":value=min(cleaned)
        elif method=="max":value=max(cleaned)
        else:value=sum(cleaned)/len(cleaned)
        observations.append({"parameter_id":canonical,"value":round(value,4),"unit":unit,
                             "aggregation":agg,"context":{"start_date":start,"end_date":end,"growth_stage":stage,
                                                             "time_standard":"LST","days_available":len(cleaned),"days_requested":n_days},
                             "source":{"name":"NASA_POWER_DAILY_AG","url":source_url,
                                       "synthetic":bool(payload.get("_synthetic_test_fixture",False))}})
    return {"schema_version":"1.0.0","farm_id":farm_id,
            "demo_only":bool(payload.get("_synthetic_test_fixture",False)),
            "location":{"latitude":lat,"longitude":lon},
            "scenario":{"date_start":start,"date_end":end,"stage_assigned_by_user":stage,
                         "kind":"historical_observation_not_forecast"},
            "observations":observations,"water_balance":None,"data_gaps":gaps,
            "warnings":["NASA POWER point data may differ from conditions at your actual farm.",
                        "The selected date window does not establish the planting date or growth stage of any crop.",
                        "CLIM_007 is total precipitation, not effective crop-available rainfall or ETc."]}


def _date_range(start:date,end:date):
    from datetime import timedelta
    while start <= end:
        yield start
        start+=timedelta(days=1)


def merge_farm(base:dict, additional:dict) -> dict:
    """Merge soil observations into a NASA-derived farm, reject incompatible sites.
    Duplicate parameter IDs are rejected to prevent silent overwrite.
    """
    if base.get('location') != additional.get('location'):
        raise ValueError('Farm coordinates differ; refusing to merge')
    if base.get('farm_id') != additional.get('farm_id'):
        raise ValueError('farm_id differs; refusing to merge')
    ids={x['parameter_id'] for x in base.get('observations',[])}
    duplicate=ids & {x['parameter_id'] for x in additional.get('observations',[])}
    if duplicate:
        raise ValueError('Duplicate parameters: '+str(sorted(duplicate)))
    merged=json.loads(json.dumps(base))
    merged['observations']+=additional.get('observations',[])
    merged['demo_only']=bool(base.get('demo_only') or additional.get('demo_only'))
    merged['merged_sources']=[base.get('farm_id'),additional.get('farm_id')]
    return merged
