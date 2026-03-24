"""
pre_screener.py — 快照预筛选引擎 (Layer 2)

基于全市场每日快照数据做"宽松粗筛"，选出候选股票池。
核心原则：零误杀 — 不确定的条件一律视为通过，宁可多选不能漏选。
候选池后续交给 Layer 3 加载 K 线做精确筛选。
"""

import logging

logger = logging.getLogger('pre_screener')


def snapshot_check(key, cond, snap, snap_prev=None):
    """用快照数据评估单个策略条件。

    返回值:
      True  — 快照数据显示该条件可能满足（放行）
      False — 快照数据显示该条件必然不满足（排除）

    不确定时返回 True（宽松策略）。
    """
    if not cond.get('enabled', False):
        return True  # 未启用的条件不影响

    try:
        close = snap.get('close', 0)
        change_pct = snap.get('change_pct', 0)

        if key == 'limitUp':
            return change_pct >= 9.8

        elif key == 'limitDown':
            return change_pct <= -9.8

        elif key == 'volumeRatio':
            vr_min = float(cond.get('min', 2))
            vol_ratio = snap.get('vol_ratio_5')
            if vol_ratio is None:
                return True  # 无数据，放行
            return vol_ratio >= vr_min

        elif key == 'breakDayMA':
            period = int(cond.get('period', 5))
            ma_field = f'ma{period}'
            ma = snap.get(ma_field)
            if ma is None:
                return True  # 无数据，放行
            # 精确交叉需要前日数据，这里做宽松判断：close 在 MA 附近即放行
            # 用 ±3% 的容差范围
            return close >= ma * 0.97

        elif key == 'breakGolden':
            days = int(cond.get('days', 20))
            ratio = float(cond.get('ratio', 0.382))
            if days <= 20:
                high_key, low_key = 'high_20d', 'low_20d'
            else:
                high_key, low_key = 'high_60d', 'low_60d'
            high = snap.get(high_key)
            low = snap.get(low_key)
            if high is None or low is None:
                return True
            golden_level = high - (high - low) * ratio
            # 宽松: close >= golden_level * 0.97
            return close >= golden_level * 0.97

        elif key == 'bollingerUp':
            boll_upper = snap.get('boll_upper')
            if boll_upper is None:
                return True
            # 宽松: close 接近或超过上轨
            return close >= boll_upper * 0.97

        elif key == 'bollingerDown':
            boll_lower = snap.get('boll_lower')
            if boll_lower is None:
                return True
            # 宽松: close 接近或低于下轨
            return close <= boll_lower * 1.03

        elif key == 'amountHigh':
            amount = snap.get('amount', 0)
            avg_amount = snap.get('avg_amount_5')
            if avg_amount is None or avg_amount <= 0:
                return True
            # 宽松: 今日成交额 > 5日均值的 80% 就放行
            return amount > avg_amount * 0.8

        elif key == 'amountLow':
            amount = snap.get('amount', 0)
            avg_amount = snap.get('avg_amount_5')
            if avg_amount is None or avg_amount <= 0:
                return True
            # 宽松: 今日成交额 < 5日均值的 120% 就放行
            return amount < avg_amount * 1.2

        elif key == 'marketCap':
            # 快照无流通股本数据，一律放行
            return True

        else:
            # 未知条件类型（amountMultiple, amountCompare, priceCompare,
            # cupHandle, shortRise, breakMinMA, bigOrder 等）
            # 必须在 K 线层精确评估，这里一律放行
            return True

    except Exception:
        return True  # 出错时放行


def pre_screen_from_snapshots(schemes, snapshots_dict, max_candidates=500):
    """用快照数据预筛选，返回候选股票代码集合。

    Args:
        schemes: 用户策略方案列表
        snapshots_dict: {code: snapshot_dict} 全市场快照
        max_candidates: 候选池上限

    Returns:
        set[str]: 候选股票代码集合
    """
    if not schemes or not snapshots_dict:
        return set()

    # 只看启用的方案
    active_schemes = [s for s in schemes if s.get('enabled', False)]
    if not active_schemes:
        return set()

    candidates = set()

    for code, snap in snapshots_dict.items():
        if len(candidates) >= max_candidates:
            break

        for scheme in active_schemes:
            conds = scheme.get('conditions', {})
            any_enabled = False
            all_pass = True

            for key, cond in conds.items():
                if not cond.get('enabled', False):
                    continue
                any_enabled = True
                if not snapshot_check(key, cond, snap):
                    all_pass = False
                    break

            if any_enabled and all_pass:
                candidates.add(code)
                break  # 任一方案通过即加入候选

    logger.info(f'预筛选完成: {len(snapshots_dict)} 只全市场 → {len(candidates)} 只候选')
    return candidates
