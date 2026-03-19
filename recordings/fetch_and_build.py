#!/usr/bin/env python3
"""
Fetch 1-min kline data for 50 A-shares from East Money API,
then generate a JSONL recording file for StockRadar.
Output: 2026-03-17.jsonl in the same directory as this script.
"""

import json, os, time, urllib.request, urllib.error
from collections import defaultdict

STOCKS = [
    ("0.000001", "000001", "平安银行"), ("1.600519", "600519", "贵州茅台"),
    ("0.300750", "300750", "宁德时代"), ("0.002594", "002594", "比亚迪"),
    ("0.300059", "300059", "东方财富"), ("1.601318", "601318", "中国平安"),
    ("0.002475", "002475", "立讯精密"), ("0.300124", "300124", "汇川技术"),
    ("1.688256", "688256", "寒武纪"),   ("0.002230", "002230", "科大讯飞"),
    ("0.300308", "300308", "中际旭创"), ("1.601360", "601360", "三六零"),
    ("0.300418", "300418", "昆仑万维"), ("0.002261", "002261", "拓维信息"),
    ("0.300339", "300339", "润和软件"), ("0.000977", "000977", "浪潮信息"),
    ("1.688111", "688111", "金山办公"), ("0.300474", "300474", "景嘉微"),
    ("0.002415", "002415", "海康威视"), ("1.601012", "601012", "隆基绿能"),
    ("0.300274", "300274", "阳光电源"), ("1.688012", "688012", "中微公司"),
    ("0.300033", "300033", "同花顺"),   ("0.002371", "002371", "北方华创"),
    ("1.688981", "688981", "中芯国际"), ("1.603986", "603986", "兆易创新"),
    ("0.300782", "300782", "卓胜微"),   ("0.002241", "002241", "歌尔股份"),
    ("0.300661", "300661", "圣邦股份"), ("1.688169", "688169", "石头科技"),
    ("0.002032", "002032", "苏泊尔"),   ("0.300496", "300496", "中科创达"),
    ("0.002049", "002049", "紫光国微"), ("1.688036", "688036", "传音控股"),
    ("1.600036", "600036", "招商银行"), ("0.300760", "300760", "迈瑞医疗"),
    ("1.600570", "600570", "恒生电子"), ("0.300624", "300624", "万兴科技"),
    ("0.300364", "300364", "中文在线"), ("1.688041", "688041", "海光信息"),
    ("1.601006", "601006", "大秦铁路"), ("1.600900", "600900", "长江电力"),
    ("0.000858", "000858", "五粮液"),   ("0.000568", "000568", "泸州老窖"),
    ("0.002714", "002714", "牧原股份"), ("0.300015", "300015", "爱尔眼科"),
    ("1.601899", "601899", "紫金矿业"), ("1.600031", "600031", "三一重工"),
    ("0.002352", "002352", "顺丰控股"), ("1.601888", "601888", "中国中免"),
]

DATE = "20260317"
BASE_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
    "secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57"
    "&klt=1&fqt=0&beg={date}&end={date}&lmt=240"
)

def fetch_stock(secid: str) -> dict | None:
    url = BASE_URL.format(secid=secid, date=DATE)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"  retry {attempt+1}/3 for {secid}: {e}")
            time.sleep(1)
    return None

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "2026-03-17.jsonl")

    # {code: {name, preKPrice, klines: [...]}}
    all_data = {}

    print(f"Fetching {len(STOCKS)} stocks...")
    for i, (secid, code, name) in enumerate(STOCKS):
        print(f"[{i+1}/{len(STOCKS)}] {code} {name} ...", end=" ", flush=True)
        raw = fetch_stock(secid)
        if raw and raw.get("data") and raw["data"].get("klines"):
            d = raw["data"]
            all_data[code] = {
                "name": d["name"],
                "preKPrice": d["preKPrice"],
                "klines": d["klines"],
            }
            print(f"OK ({len(d['klines'])} bars)")
        else:
            print("FAILED")
        time.sleep(0.08)  # be polite

    if not all_data:
        print("No data fetched, aborting.")
        return

    # Collect all unique time slots across all stocks
    time_slots = set()
    parsed = {}  # code -> {time_str: (open, close, high, low, vol, amount)}
    for code, info in all_data.items():
        parsed[code] = {}
        for line in info["klines"]:
            parts = line.split(",")
            dt_str = parts[0]           # "2026-03-17 HH:MM"
            t = dt_str.split(" ")[1]    # "HH:MM"
            t_full = t + ":00"          # "HH:MM:00"
            time_slots.add(t_full)
            parsed[code][t_full] = {
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "vol": int(parts[5]),
                "amount": float(parts[6]),
            }

    sorted_times = sorted(time_slots)

    # Build JSONL: one line per minute
    lines = []
    for t in sorted_times:
        snapshot = {}
        for code, info in all_data.items():
            bars = parsed[code]
            if t not in bars:
                continue

            # Compute cumulative volume and amount up to this minute
            cum_vol = 0
            cum_amount = 0.0
            for t2 in sorted_times:
                if t2 > t:
                    break
                if t2 in bars:
                    cum_vol += bars[t2]["vol"]
                    cum_amount += bars[t2]["amount"]

            b = bars[t]
            snapshot[code] = {
                "name": info["name"],
                "now": b["close"],
                "close": info["preKPrice"],
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "turnover": cum_vol,
                "volume": round(cum_amount, 2),
            }

        if snapshot:
            lines.append(json.dumps({"t": t, "s": snapshot}, ensure_ascii=False))

    os.makedirs(script_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nDone! Wrote {len(lines)} lines to {out_path}")

if __name__ == "__main__":
    main()
