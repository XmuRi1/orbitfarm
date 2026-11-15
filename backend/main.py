"""CLI: run from this directory; no third-party packages required."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from scoring import read_json,score_all_crops
from nasa_power import fetch_power_daily,convert_power,merge_farm
from live_pipeline import assess_nasa
HERE=Path(__file__).resolve().parent

def write(path:str|Path, data:dict):
    out=Path(path)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Saved: {out}")

def main():
    p=argparse.ArgumentParser(description="OrbitFarm crop/farm data integration and exploratory scoring")
    subs=p.add_subparsers(dest='command',required=True)
    demo=subs.add_parser('demo',help='Offline demo for all 10 crops')
    demo.add_argument('--output',default=str(HERE/'outputs/demo_assessment.json'))
    assess=subs.add_parser('assess',help='Score your farm observations against all crop requirements')
    assess.add_argument('--farm',required=True)
    assess.add_argument('--crops',default=str(HERE/'data/crops.json'))
    assess.add_argument('--mode',choices=['demo','strict'],default='strict')
    assess.add_argument('--output',required=True)
    nasa=subs.add_parser('nasa',help='Fetch historical NASA POWER daily values for coordinates')
    for a,t in (('--lat',float),('--lon',float)):
        nasa.add_argument(a,type=t,required=True)
    nasa.add_argument('--start',required=True,help='YYYY-MM-DD historical')
    nasa.add_argument('--end',required=True,help='YYYY-MM-DD historical')
    nasa.add_argument('--stage',default=None,help='e.g., active_growth; only if your period truly corresponds to this stage')
    nasa.add_argument('--farm-id',default='my_farm')
    nasa.add_argument('--output',required=True)
    live=subs.add_parser('nasa-assess',help='Fetch real historical NASA observations and score 10 crops')
    live.add_argument('--lat',type=float,required=True)
    live.add_argument('--lon',type=float,required=True)
    live.add_argument('--start',required=True)
    live.add_argument('--end',required=True)
    live.add_argument('--stage',choices=['active_growth'],default=None)
    live.add_argument('--mode',choices=['demo','strict'],default='demo')
    live.add_argument('--farm-id',default='selected_map_point')
    live.add_argument('--output',default=str(HERE/'outputs/nasa_live_assessment.json'))
    fixture=subs.add_parser('fixture',help='Test NASA adapter offline against an illustrative NASA-shape fixture')
    fixture.add_argument('--output',default=str(HERE/'outputs/farm_from_nasa_fixture.json'))
    merge=subs.add_parser('merge',help='Join two farm observation JSONs without overwriting duplicates')
    merge.add_argument('--base',required=True)
    merge.add_argument('--additional',required=True)
    merge.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command == 'demo':
        farm=read_json(HERE/'data/farm_demo.json');crops=read_json(HERE/'data/crops.json')
        write(args.output,score_all_crops(farm,crops,mode='demo'))
    elif args.command=='assess':
        write(args.output,score_all_crops(read_json(args.farm),read_json(args.crops),mode=args.mode))
    elif args.command=='nasa':
        raw,url=fetch_power_daily(args.lat,args.lon,args.start,args.end)
        write(args.output,convert_power(raw,lat=args.lat,lon=args.lon,start=args.start,end=args.end,
                                         stage=args.stage,farm_id=args.farm_id,source_url=url))
    elif args.command=='nasa-assess':
        data=assess_nasa({'latitude':args.lat,'longitude':args.lon,'start':args.start,
                          'end':args.end,'growth_stage':args.stage,'mode':args.mode,
                          'farm_id':args.farm_id})
        write(args.output,data)
    elif args.command=='fixture':
        raw=read_json(HERE/'data/power_fixture_synthetic.json')
        write(args.output,convert_power(raw,lat=31.25,lon=34.79,start='2025-01-01',end='2025-01-05',
                                         stage='active_growth',farm_id='DEMO_SYNTHETIC_FARM',source_url=None))
    else:
        write(args.output,merge_farm(read_json(args.base),read_json(args.additional)))

if __name__=='__main__':main()
