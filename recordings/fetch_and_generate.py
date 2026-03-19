#!/usr/bin/env python3
"""
Fetch 50 A-stock 1-min klines from eastmoney and generate JSONL recording.
Usage: python3 fetch_and_generate.py
"""
import json, urllib.request, time, sys, os

STOCKS = [
    ("0.000001", "平安银行"), ("1.600519", "贵州茅台"), ("0.300750", "宁德时代"),
    ("0.002594", "比亚迪"), ("0.300059", "东方财富"), ("1.601318", "中国平安"),
    ("0.002475", "立讯精密"), ("0.300124", "汇川技术"), ("1.688256", "寒武纪"),
    ("0.002230", "科大讯飞"), ("0.300308", "中际旭创"), ("1.601360", "三六零"),
    ("0.300418", "昆仑万维"), ("0.002261", "拓维信息"), ("0.300339", "润和软件"),
    ("0.000977", "浪潮信息"), ("1.688111", "金山办公"), ("0.300474", "景嘉微"),
    ("0.002415", "海康威视"), ("1.601012", "隆基绿能"), ("0.300274", "阳光电源"),
    ("1.688012", "中微公司"), ("0.300033", "同花顺"), ("0.002371", "北方华创"),
    ("1.688981", "中芯国际"), ("1.603986", "兆易创新"), ("0.300782", "卓胜微"),
    ("0.002241", "歌尔股份"), ("0.300661", "圣邦股份"), ("1.688169", "石头科技"),
    ("0.002032", "苏泊尔"), ("0.300496", "中科创达"), ("0.002049", "紫光国微"),
    ("1.688036", "传音控股"), ("1.600036", "招商银行"), ("0.300760", "迈瑞医疗"),
    ("1.600570", "恒生电子"), ("0.300624", "万兴科技"), ("0.300364", "中文在线"),
    ("1.688041", "海光信息"), ("1.601006", "大秦铁路"), ("1.600900", "长江电力"),
    ("0.000858", "五粮液"), ("0.000568", "泸州老窖"), ("0.002714", "牧原股份"),
    ("0.300015", "爱尔眼科"), ("1.601899", "紫金矿业"), ("1.600031", "三一重工"),
    ("0.002352", "顺丰控股"), ("1.601888", "中国中免"),
]

URL_TPL = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=1&fqt=0&beg=20260317&end=20260317&lmt=240"

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "2026-03-17.jsonl")

# Try to load cached raw data
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".raw_cache.json")

def fetch_stock(secid):
    url = URL_TPL.format(secid=secid)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def main():
    # Load cache if exists
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
    
    # Fetch all stocks
    all_data = {}
    for secid, name in STOCKS:
        code = secid.split(".")[1]
        if code in cache:
            all_data[code] = cache[code]
            print(f"  [cache] {code} {name}")
            continue
        print(f"  Fetching {code} {name}...", end=" ", flush=True)
        try:
            resp = fetch_stock(secid)
            data = resp.get("data")
            if not data or not data.get("klines"):
                print("NO DATA")
                continue
            all_data[code] = {
                "name": data["name"],
                "preKPrice": data["preKPrice"],
                "klines": data["klines"],
            }
            print(f"OK ({len(data['klines'])} bars)")
        except Exception as e:
            print(f"ERROR: {e}")
        time.sleep(0.3)  # rate limit
    
    # Save cache
    with open(CACHE_FILE, "w") as f:
        json.dump(all_data, f, ensure_ascii=False)
    
    print(f"\nFetched {len(all_data)} stocks. Generating JSONL...")
    
    # Parse klines and aggregate by minute
    # time_map: { "HH:MM:SS": { code: {name, now, close, open, high, low, turnover, volume} } }
    time_map = {}
    
    for code, stock_data in all_data.items():
        name = stock_data["name"]
        pre_close = stock_data["preKPrice"]
        klines = stock_data["klines"]
        
        cum_vol = 0
        cum_amount = 0.0
        
        for kline_str in klines:
            parts = kline_str.split(",")
            # datetime,open,close,high,low,vol,amount
            dt = parts[0]        # "2026-03-17 09:31"
            k_open = float(parts[1])
            k_close = float(parts[2])
            k_high = float(parts[3])
            k_low = float(parts[4])
            k_vol = int(parts[5])
            k_amount = float(parts[6])
            
            cum_vol += k_vol
            cum_amount += k_amount
            
            # Extract time part -> "HH:MM:SS"
            time_part = dt.split(" ")[1]
            time_key = time_part + ":00"  # "09:31:00"
            
            if time_key not in time_map:
                time_map[time_key] = {}
            
            time_map[time_key][code] = {
                "name": name,
                "now": k_close,
                "close": pre_close,
                "open": k_open,
                "high": k_high,
                "low": k_low,
                "turnover": cum_vol,
                "volume": cum_amount,
            }
    
    # Sort by time and write JSONL
    sorted_times = sorted(time_map.keys())
    
    with open(OUTPUT, "w", encoding="utf-8") as f:
        for t in sorted_times:
            row = {"t": t, "s": time_map[t]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    
    print(f"Done! {len(sorted_times)} time points, {len(all_data)} stocks.")
    print(f"Output: {OUTPUT}")

if __name__ == "__main__":
    main()
