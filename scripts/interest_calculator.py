#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""民间借贷利息与违约金计算器（纯 Python 标准库，无第三方依赖）。

法律依据
========
《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》
（法释〔2020〕17 号，2020-08-20 施行，2020-12-29 第二次修正）：

- 第 25 条：利率上限 = 合同成立时一年期贷款市场报价利率（LPR）的 4 倍，
  超过部分人民法院不予支持。
- 第 28 条：既未约定借期内利率，也未约定逾期利率的，出借人可主张
  自逾期还款之日起参照当时一年期 LPR 计算资金占用损失；
  约定了借期内利率但未约定逾期利率的，可按借期内利率主张逾期利息。
- 第 29 条：逾期利息、违约金或者其他费用可以一并主张，
  但总计超过合同成立时一年期 LPR 四倍的部分，人民法院不予支持。
- 第 31 条：2020-08-20 之后新受理的一审案件，借贷行为发生在 2019-08-20
  之前的，可参照起诉时一年期 LPR 的四倍确定受保护利率上限。
- 《民法典》第 680 条：借款合同对支付利息没有约定的，视为没有利息；
  自然人之间借款对利息约定不明的，视为没有利息。
- 砍头息（《民法典》第 670 条 / 民间借贷司法解释第 26 条）：利息不得
  预先在本金中扣除，预先扣除的，以实际出借金额为本金。

LPR 数据来源与更新方法
======================
一年期 LPR 由中国人民银行授权全国银行间同业拆借中心于每月 20 日
（遇节假日顺延）公布。下表只记录「利率发生调整」的日期，未调整的月份
沿用上一期利率；数据核对日期：2026-11-10。

- 中国银行 LPR 历史表（转载全国银行间同业拆借中心报价，含逐月明细）：
  https://www.boc.cn/fimarkets/lilv/fd32/201310/t20131031_2591219.html
- 浙商银行 LPR 调整表（仅列调整日）：
  https://www.zjrcbank.cn/grcbank/fzlm/lljhl/2021010815145244208/index.shtml
- 2025-05-20 一年期 LPR 由 3.10% 下调至 3.00%（中国人民银行授权公布，
  中国政府网报道）：http://www.gov.cn/zhengce/202505/content_7024586.htm

2025-05-20 至 2026-10-20 的各期一年期 LPR 均维持 3.00%，期间未再调整。

更新方法：LPR 再次调整时，在 ``LPR_TABLE`` 中按日期升序追加一行
``"YYYY-MM-DD": Decimal("0.0xxx")``（注意是小数而非百分数），
同步更新本注释中的数据核对日期和 ``scripts/tests`` 中「最新 LPR」断言。

TODO：本表已核对至 2026-10-20（一年期 LPR 维持 3.00%）；如 2026-11 以后
再有调整，需补录。2019-08-20 之前没有 LPR，相关合同按司法解释第 31 条
参照起诉时 LPR 处理（见 ``calculate_claim`` 的 ``cap_lpr_date`` 参数）。

计算口径
========
1. 日利率 = 年利率 / 365；日利息 = 本金 × 年利率 ÷ 365 × 实际天数。
2. 计息区间为左闭右开 ``[start, end)``，天数 = ``(end - start).days``，
   即「算头不算尾」。例如 2023-01-01 至 2023-07-01 计 181 天；
   若需包含结束日，请把 ``end`` 传为结束日的次日。
3. 金额四舍五入（``ROUND_HALF_UP``）保留 2 位小数。分段计息时**每段单独
   舍入后相加**，所以明细表各段利息之和恰好等于合计利息。
4. 利率上限 = 合同成立时一年期 LPR × 4，约定利率（含逾期利率）超过
   上限时按上限计算，超出部分不予支持。
5. 上限校验口径：利息 + 违约金 + 其他费用合计 ≤ 4 × LPR（合同成立时）
   × 整个借款期间 × 实际本金。本工具以「实际出借日 / 合同成立日」至
   「起诉日（未提供则为还款日）」作为整个借款期间。
6. 未约定借期内利息：自然人之间视为无息（《民法典》第 680 条）。
   逾期利息分三种情形：有约定从约定；未约定逾期利率但约定了借期内利率
   的按借期内利率；两者均未约定的按一年期 LPR。
7. 未约定逾期利率而按 LPR 计算时，默认按 LPR 调整分段计息
   （``lpr_mode="segmented"``）；部分法院按逾期日 LPR 固定计算，可用
   ``lpr_mode="snapshot"`` 复核。

命令行示例
==========
    python3 scripts/interest_calculator.py --principal 100000 \\
        --contract-date 2023-01-01 --due-date 2023-07-01 \\
        --annual-rate 0.12 --sue-date 2025-01-01

本工具输出仅供参考，不构成正式法律意见。
"""

from __future__ import annotations

import argparse
import bisect
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Callable, Optional, Sequence, Tuple, Union

__all__ = [
    "LPR_TABLE",
    "MIN_LPR_DATE",
    "DAYS_PER_YEAR",
    "MONEY_QUANT",
    "Number",
    "DateLike",
    "RateProvider",
    "InterestSegment",
    "SegmentedInterest",
    "CapCheckResult",
    "ClaimResult",
    "lpr_on",
    "four_times_lpr",
    "simple_interest",
    "segmented_interest",
    "cap_check",
    "calculate_claim",
    "render_report",
    "build_parser",
    "main",
]

# ---------------------------------------------------------------------------
# 类型别名与常量
# ---------------------------------------------------------------------------

#: 可接受的数值类型；float 会先转成 str 再转 Decimal，避免二进制浮点误差。
Number = Union[Decimal, int, float, str]
#: 可接受的日期类型（ISO 字符串 ``YYYY-MM-DD``、date 或 datetime）。
DateLike = Union[date, datetime, str]
#: 分段计息使用的利率提供函数：给定日期，返回该日适用的年利率（小数）。
RateProvider = Callable[[date], Number]

DAYS_PER_YEAR = Decimal(365)
MONEY_QUANT = Decimal("0.01")

#: LPR 首次报价日；此前无一年期 LPR。
MIN_LPR_DATE = date(2019, 8, 20)

# ---------------------------------------------------------------------------
# 一年期 LPR 历史表（单位：小数。4.25% 记作 0.0425）
# ---------------------------------------------------------------------------
# 只列调整日；未调整的月份沿用上一期利率。日期必须按升序排列。
LPR_TABLE: "dict[str, Decimal]" = {
    "2019-08-20": Decimal("0.0425"),  # LPR 改革后首期报价
    "2019-09-20": Decimal("0.0420"),
    "2019-11-20": Decimal("0.0415"),
    "2020-02-20": Decimal("0.0405"),
    "2020-04-20": Decimal("0.0385"),
    "2021-12-20": Decimal("0.0380"),
    "2022-01-20": Decimal("0.0370"),
    "2022-08-22": Decimal("0.0365"),
    "2023-06-20": Decimal("0.0355"),
    "2023-08-21": Decimal("0.0345"),
    "2024-07-22": Decimal("0.0335"),
    "2024-10-21": Decimal("0.0310"),
    "2025-05-20": Decimal("0.0300"),  # 截至 2026-10-20 未再调整
}
# 说明：2022-05-20、2024-02-20 仅 5 年期以上 LPR 调整，1 年期未变，
# 因此不在上表重复记录。


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _as_date(value: DateLike, *, name: str = "日期") -> date:
    """把 ISO 字符串 / date / datetime 统一转成 ``date``。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name}格式应为 YYYY-MM-DD，收到：{value!r}") from exc
    raise TypeError(f"{name}类型不支持：{type(value).__name__}")


def _as_decimal(value: Number, *, name: str = "数值") -> Decimal:
    """把数值统一转成 Decimal，并拒绝 NaN / Infinity。"""
    if isinstance(value, bool):  # bool 是 int 的子类，单独拦截
        raise TypeError(f"{name}不能是布尔值")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        result = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace("，", "")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{name}无法解析为数字：{value!r}") from exc
    else:
        raise TypeError(f"{name}类型不支持：{type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"{name}必须是有限数值")
    return result


def _as_money(value: Number, *, name: str = "金额") -> Decimal:
    """转为金额并校验非负（不强制舍入，由计算处统一舍入）。"""
    result = _as_decimal(value, name=name)
    if result < 0:
        raise ValueError(f"{name}不能为负数：{result}")
    return result


def _as_rate(value: Number, *, name: str = "利率") -> Decimal:
    """转为年利率（小数形式）并校验非负。"""
    result = _as_decimal(value, name=name)
    if result < 0:
        raise ValueError(f"{name}不能为负数：{result}")
    return result


def _money(value: Decimal) -> Decimal:
    """金额四舍五入保留 2 位小数（ROUND_HALF_UP，即常见的「四舍五入」）。"""
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _raw_interest(principal: Decimal, annual_rate: Decimal, days: int) -> Decimal:
    """未舍入的利息 = 本金 × 年利率 × 天数 / 365。"""
    return principal * annual_rate * Decimal(days) / DAYS_PER_YEAR


def _validate_period(start: date, end: date, *, name: str = "计息期间") -> None:
    if end < start:
        raise ValueError(f"{name}结束日 {end.isoformat()} 不能早于开始日 {start.isoformat()}")


# ---------------------------------------------------------------------------
# LPR 查询
# ---------------------------------------------------------------------------


def lpr_on(when: DateLike) -> Decimal:
    """查询指定日期适用的一年期 LPR（小数形式）。

    采用「最近一次已公布报价」原则：若该日期不是报价日，则沿用之前最近一期
    的利率。日期早于 2019-08-20（无 LPR）时抛出 ``ValueError``。

    >>> lpr_on("2023-07-15")
    Decimal('0.0355')
    >>> lpr_on(date(2024, 1, 1))
    Decimal('0.0345')
    """
    target = _as_date(when)
    iso_dates = sorted(LPR_TABLE)
    if not iso_dates:
        raise ValueError("LPR_TABLE 为空，无法查询 LPR")
    first = date.fromisoformat(iso_dates[0])
    if target < first:
        raise ValueError(
            f"{target.isoformat()} 早于 LPR 首次报价日 {first.isoformat()}，"
            "没有「合同成立时一年期 LPR」；2019-08-20 之前的借贷可按司法解释"
            "第 31 条参照起诉时 LPR 确定上限（见 calculate_claim 的 cap_lpr_date 参数）"
        )
    keys = [date.fromisoformat(item) for item in iso_dates]
    index = bisect.bisect_right(keys, target) - 1
    return LPR_TABLE[iso_dates[index]]


def four_times_lpr(contract_date: DateLike) -> Decimal:
    """返回合同成立时一年期 LPR 的 4 倍（小数形式，即司法保护利率上限）。"""
    return lpr_on(contract_date) * Decimal(4)


# ---------------------------------------------------------------------------
# 单利与分段计息
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterestSegment:
    """一段固定利率的计息明细。

    属性
    ----
    label: 段类型说明，如「借期内」「逾期（约定）」「逾期（LPR分段）」。
    start / end: 计息区间 ``[start, end)``。
    days: 实际天数 ``(end - start).days``。
    annual_rate: 该段适用年利率（小数）。
    principal: 该段计息本金。
    interest: 该段利息，已四舍五入保留 2 位小数。
    """

    label: str
    start: date
    end: date
    days: int
    annual_rate: Decimal
    principal: Decimal
    interest: Decimal

    def to_dict(self) -> "dict[str, object]":
        """转成可 JSON 序列化的字典（金额与利率用字符串避免精度丢失）。"""
        return {
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "annual_rate": str(self.annual_rate),
            "principal": str(self.principal),
            "interest": str(self.interest),
        }


@dataclass(frozen=True)
class SegmentedInterest:
    """分段计息结果：``total`` 为各段舍入后利息之和，``segments`` 为明细。"""

    total: Decimal
    segments: Tuple[InterestSegment, ...]

    def to_dict(self) -> "dict[str, object]":
        return {
            "total": str(self.total),
            "segments": [segment.to_dict() for segment in self.segments],
        }


def _build_segment(
    principal: Decimal,
    annual_rate: Decimal,
    start: date,
    end: date,
    label: str,
) -> InterestSegment:
    """构造一段固定利率的计息明细（调用方保证 ``end >= start``）。"""
    days = (end - start).days
    return InterestSegment(
        label=label,
        start=start,
        end=end,
        days=days,
        annual_rate=annual_rate,
        principal=principal,
        interest=_money(_raw_interest(principal, annual_rate, days)),
    )


def simple_interest(
    principal: Number,
    annual_rate: Number,
    start: DateLike,
    end: DateLike,
) -> Decimal:
    """按实际天数计算单利，返回保留 2 位小数的利息。

    公式：``本金 × 年利率 ÷ 365 × (end - start).days``。
    计息区间左闭右开，含起始日、不含结束日；``start == end`` 时为 0。

    >>> simple_interest("100000", "0.12", "2023-01-01", "2023-01-02")
    Decimal('32.88')
    """
    money = _as_money(principal, name="本金")
    rate = _as_rate(annual_rate, name="年利率")
    start_date = _as_date(start, name="计息开始日")
    end_date = _as_date(end, name="计息结束日")
    _validate_period(start_date, end_date)
    return _build_segment(money, rate, start_date, end_date, "单利").interest


def segmented_interest(
    principal: Number,
    rate_provider: RateProvider,
    start: DateLike,
    end: DateLike,
    *,
    label: str = "分段",
) -> SegmentedInterest:
    """按 ``rate_provider`` 给出的适用利率分段计算单利。

    函数假定利率是「分段常数」的（LPR 即如此）：逐日探测利率变化点，
    在变化点切分区间，每段单独计息并舍入到 2 位小数后相加。

    ``rate_provider`` 接受一个 ``date`` 并返回该日适用的年利率（小数），
    例如传入本模块的 :func:`lpr_on` 即按 LPR 调整分段。

    >>> result = segmented_interest("100000", lpr_on, "2023-06-01", "2023-09-01")
    >>> [segment.days for segment in result.segments]
    [19, 62, 11]
    """
    money = _as_money(principal, name="本金")
    start_date = _as_date(start, name="计息开始日")
    end_date = _as_date(end, name="计息结束日")
    if not callable(rate_provider):
        raise TypeError("rate_provider 必须是可调用对象（date -> 年利率）")
    _validate_period(start_date, end_date)

    if start_date == end_date:
        return SegmentedInterest(total=Decimal("0.00"), segments=())

    segments: "list[InterestSegment]" = []
    segment_start = start_date
    segment_rate = _as_rate(rate_provider(start_date), name="分段利率")

    probe = start_date + timedelta(days=1)
    while probe < end_date:
        current_rate = _as_rate(rate_provider(probe), name="分段利率")
        if current_rate != segment_rate:
            segments.append(
                _build_segment(money, segment_rate, segment_start, probe, label)
            )
            segment_start = probe
            segment_rate = current_rate
        probe += timedelta(days=1)

    segments.append(_build_segment(money, segment_rate, segment_start, end_date, label))
    total = sum((segment.interest for segment in segments), Decimal("0.00"))
    return SegmentedInterest(total=_money(total), segments=tuple(segments))


# ---------------------------------------------------------------------------
# 4 × LPR 上限校验
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapCheckResult:
    """4 × LPR 上限校验结果。

    上限金额 = 基数本金 × 上限年利率 × 期间天数 / 365。
    ``claimed_total`` 为本次主张的「利息 + 违约金 + 其他费用」合计。
    ``supported_total`` 为法院可支持金额（不超过上限），``excess`` 为超出部分。
    """

    base_principal: Decimal
    cap_annual_rate: Decimal
    start: date
    end: date
    days: int
    cap_amount: Decimal
    claimed_total: Decimal
    supported_total: Decimal
    excess: Decimal
    headroom: Decimal
    passed: bool

    def to_dict(self) -> "dict[str, object]":
        return {
            "base_principal": str(self.base_principal),
            "cap_annual_rate": str(self.cap_annual_rate),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "cap_amount": str(self.cap_amount),
            "claimed_total": str(self.claimed_total),
            "supported_total": str(self.supported_total),
            "excess": str(self.excess),
            "headroom": str(self.headroom),
            "passed": self.passed,
        }


def cap_check(
    principal: Number,
    contract_date: Optional[DateLike],
    start: DateLike,
    end: DateLike,
    total_claimed: Number,
    *,
    cap_annual_rate: Optional[Number] = None,
) -> CapCheckResult:
    """校验「利息 + 违约金 + 其他费用」是否超过 4 × LPR 上限。

    参数
    ----
    principal: 最初本金（砍头息情形为实际出借金额）。
    contract_date: 合同成立日，用于查合同成立时 LPR；若已通过
        ``cap_annual_rate`` 直接给出上限年利率，可传 ``None``。
    start / end: 整个借款期间 ``[start, end)``。
    total_claimed: 主张的利息 + 违约金 + 其他费用合计。
    cap_annual_rate: 可选的 4 × LPR 上限年利率（小数），用于 2019-08-20 前
        合同按起诉时 LPR 计算的特殊情形；不传则由 ``contract_date`` 查表。

    返回
    ----
    :class:`CapCheckResult`，其中 ``supported_total`` 为可支持金额。
    """
    base = _as_money(principal, name="本金")
    claimed = _as_money(total_claimed, name="主张金额合计")
    start_date = _as_date(start, name="借款期间开始日")
    end_date = _as_date(end, name="借款期间结束日")
    _validate_period(start_date, end_date, name="借款期间")

    if cap_annual_rate is not None:
        rate = _as_rate(cap_annual_rate, name="上限年利率")
    else:
        if contract_date is None:
            raise ValueError("未提供 contract_date 时必须给出 cap_annual_rate")
        rate = four_times_lpr(contract_date)

    days = (end_date - start_date).days
    cap_amount = _money(_raw_interest(base, rate, days))
    supported = min(claimed, cap_amount)
    return CapCheckResult(
        base_principal=base,
        cap_annual_rate=rate,
        start=start_date,
        end=end_date,
        days=days,
        cap_amount=cap_amount,
        claimed_total=claimed,
        supported_total=supported,
        excess=claimed - supported,
        headroom=max(cap_amount - claimed, Decimal("0.00")),
        passed=claimed <= cap_amount,
    )


# ---------------------------------------------------------------------------
# 诉请计算
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimResult:
    """一次诉请计算的完整结果。

    金额字段均为 2 位小数的 :class:`~decimal.Decimal`；日期为 ``date``。
    ``total_claimed`` / ``total_supported`` 包含本金。
    """

    claimed_principal: Decimal
    principal: Decimal
    borrow_date: date
    contract_date: date
    due_date: date
    sue_date: Optional[date]
    cap_lpr_date: date
    cap_lpr: Decimal
    cap_annual_rate: Decimal
    in_term_rate: Optional[Decimal]
    in_term_interest: Decimal
    overdue_interest: Decimal
    overdue_rate_applied: Optional[Decimal]
    overdue_mode: str
    total_interest: Decimal
    penalty: Decimal
    other_fees: Decimal
    claimed_fees_total: Decimal
    supported_fees_total: Decimal
    excess_fees: Decimal
    penalty_headroom: Decimal
    total_claimed: Decimal
    total_supported: Decimal
    cap: CapCheckResult
    segments: Tuple[InterestSegment, ...]
    warnings: Tuple[str, ...]

    @property
    def lending_period_days(self) -> int:
        """整个借款期间的天数（用于上限校验）。"""
        return self.cap.days

    def to_dict(self) -> "dict[str, object]":
        """转成可 JSON 序列化的字典。"""
        return {
            "claimed_principal": str(self.claimed_principal),
            "principal": str(self.principal),
            "borrow_date": self.borrow_date.isoformat(),
            "contract_date": self.contract_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "sue_date": self.sue_date.isoformat() if self.sue_date else None,
            "cap_lpr_date": self.cap_lpr_date.isoformat(),
            "cap_lpr": str(self.cap_lpr),
            "cap_annual_rate": str(self.cap_annual_rate),
            "in_term_rate": None if self.in_term_rate is None else str(self.in_term_rate),
            "in_term_interest": str(self.in_term_interest),
            "overdue_interest": str(self.overdue_interest),
            "overdue_rate_applied": (
                None if self.overdue_rate_applied is None else str(self.overdue_rate_applied)
            ),
            "overdue_mode": self.overdue_mode,
            "total_interest": str(self.total_interest),
            "penalty": str(self.penalty),
            "other_fees": str(self.other_fees),
            "claimed_fees_total": str(self.claimed_fees_total),
            "supported_fees_total": str(self.supported_fees_total),
            "excess_fees": str(self.excess_fees),
            "penalty_headroom": str(self.penalty_headroom),
            "total_claimed": str(self.total_claimed),
            "total_supported": str(self.total_supported),
            "cap": self.cap.to_dict(),
            "segments": [segment.to_dict() for segment in self.segments],
            "warnings": list(self.warnings),
        }


def calculate_claim(
    principal: Number,
    contract_date: DateLike,
    due_date: DateLike,
    *,
    sue_date: Optional[DateLike] = None,
    annual_rate: Optional[Number] = None,
    overdue_rate: Optional[Number] = None,
    penalty: Number = "0",
    other_fees: Number = "0",
    actual_disbursed: Optional[Number] = None,
    natural_persons: bool = True,
    lpr_mode: str = "segmented",
    cap_lpr_date: Optional[DateLike] = None,
    borrow_date: Optional[DateLike] = None,
) -> ClaimResult:
    """计算民间借贷诉请中的本金、利息、违约金及 4 × LPR 上限校验。

    参数
    ----
    principal: 借条 / 合同载明的本金（元）。
    contract_date: 合同成立日，用于快照「合同成立时一年期 LPR」。
    due_date: 约定还款日；逾期利息自该日起算。
    sue_date: 起诉日 / 计算截止日。不传则只计算到还款日、不计逾期利息。
    annual_rate: 借期内约定年利率（小数，0.12 表示 12%）；不传视为未约定。
    overdue_rate: 约定逾期年利率（小数）；不传则按业务规则推定。
    penalty: 违约金金额（元，固定金额）。
    other_fees: 其他费用金额（元），与利息、违约金合并受上限约束。
    actual_disbursed: 实际出借金额（砍头息时小于借条本金，以实际金额为本金）。
    natural_persons: 双方是否均为自然人；影响未约定利息时的提示（《民法典》
        第 680 条）。
    lpr_mode: 未约定任何利率时逾期利息的 LPR 口径：
        ``"segmented"``（默认，按 LPR 调整分段）或 ``"snapshot"``
        （按逾期日 LPR 固定计算）。
    cap_lpr_date: 仅用于合同成立日早于 2019-08-20 的情形，指定确定上限所
        参照的「起诉时」LPR 日期（司法解释第 31 条）。
    borrow_date: 实际出借日，默认等于 ``contract_date``；用于借期内利息起算
        及整个借款期间起算。

    返回
    ----
    :class:`ClaimResult`。

    异常
    ----
    ``ValueError``：金额 / 日期 / 利率非法，或缺少预 2019-08-20 合同所需参数。
    ``TypeError``：参数类型不支持。
    """
    claimed_principal = _as_money(principal, name="借条本金")
    if claimed_principal <= 0:
        raise ValueError("借条本金必须大于 0")
    contract = _as_date(contract_date, name="合同成立日")
    due = _as_date(due_date, name="还款日")
    borrow = _as_date(borrow_date, name="实际出借日") if borrow_date is not None else contract
    sue = _as_date(sue_date, name="起诉日") if sue_date is not None else None

    if not isinstance(natural_persons, bool):
        raise TypeError("natural_persons 必须是 bool")
    if lpr_mode not in ("segmented", "snapshot"):
        raise ValueError("lpr_mode 只能是 'segmented' 或 'snapshot'")

    _validate_period(borrow, due, name="借款期间（出借日至还款日）")
    if sue is not None:
        if sue < borrow:
            raise ValueError("起诉日不能早于实际出借日")
        if sue < due:
            raise ValueError("起诉日早于还款日，本工具未支持提前到期 / 加速到期情形")

    # 砍头息：以实际出借金额为本金（《民法典》第 670 条）。
    warnings: "list[str]" = []
    if actual_disbursed is not None:
        actual = _as_money(actual_disbursed, name="实际出借金额")
        if actual <= 0:
            raise ValueError("实际出借金额必须大于 0")
        if actual > claimed_principal:
            raise ValueError("实际出借金额不能大于借条本金")
        if actual < claimed_principal:
            warnings.append(
                f"砍头息：借条本金 {_fmt_money(claimed_principal)} 元，"
                f"实际出借 {_fmt_money(actual)} 元；依《民法典》第 670 条，"
                "以实际出借金额为本金计息。"
            )
        principal_used = actual
    else:
        principal_used = claimed_principal

    annual = _as_rate(annual_rate, name="借期内年利率") if annual_rate is not None else None
    overdue = _as_rate(overdue_rate, name="逾期年利率") if overdue_rate is not None else None
    penalty_amount = _as_money(penalty, name="违约金")
    other_amount = _as_money(other_fees, name="其他费用")

    # 2019-08-20 之前无 LPR：按司法解释第 31 条参照起诉时 LPR。
    if contract < MIN_LPR_DATE:
        if cap_lpr_date is None:
            raise ValueError(
                f"合同成立日 {contract.isoformat()} 早于 LPR 首次报价日 "
                f"{MIN_LPR_DATE.isoformat()}，没有「合同成立时一年期 LPR」；"
                "请用 cap_lpr_date 指定起诉时（或参照时点）的日期，"
                "按司法解释第 31 条参照起诉时 LPR 的 4 倍确定上限"
            )
        reference_date = _as_date(cap_lpr_date, name="上限参照 LPR 日期")
        warnings.append(
            "合同成立日早于 2019-08-20：依司法解释第 31 条，"
            f"参照 {reference_date.isoformat()} 的一年期 LPR 的四倍确定利率上限。"
        )
    else:
        if cap_lpr_date is not None:
            raise ValueError("cap_lpr_date 仅用于合同成立日早于 2019-08-20 的情形")
        reference_date = contract

    reference_lpr = lpr_on(reference_date)
    cap_rate = reference_lpr * Decimal(4)

    # ---------------- 借期内利息 ----------------
    segments: "list[InterestSegment]" = []
    in_term_rate: Optional[Decimal]
    if annual is None:
        in_term_rate = None
        in_term_interest = Decimal("0.00")
        if natural_persons:
            warnings.append(
                "未约定借期内利息：自然人之间借款视为无息（《民法典》第 680 条）。"
            )
        else:
            warnings.append(
                "未约定借期内利息：依《民法典》第 680 条，借款合同对支付利息没有"
                "约定的视为没有利息；非自然人之间约定不明的利息可能由法院酌定，"
                "本工具按无息保守计算。"
            )
    else:
        in_term_rate = min(annual, cap_rate)
        if annual > cap_rate:
            warnings.append(
                f"约定借期内年利率 {_fmt_rate(annual)} 超过 4 × LPR 上限 "
                f"{_fmt_rate(cap_rate)}，超出部分不予支持，本工具按上限计算。"
            )
        segment = _build_segment(principal_used, in_term_rate, borrow, due, "借期内")
        segments.append(segment)
        in_term_interest = segment.interest

    # ---------------- 逾期利息 ----------------
    overdue_segments: "list[InterestSegment]" = []
    overdue_interest = Decimal("0.00")
    overdue_rate_applied: Optional[Decimal] = None
    overdue_mode = "无"
    if sue is not None and sue > due:
        if overdue is not None:
            overdue_rate_applied = min(overdue, cap_rate)
            if overdue > cap_rate:
                warnings.append(
                    f"约定逾期年利率 {_fmt_rate(overdue)} 超过 4 × LPR 上限 "
                    f"{_fmt_rate(cap_rate)}，超出部分不予支持，本工具按上限计算。"
                )
            segment = _build_segment(
                principal_used, overdue_rate_applied, due, sue, "逾期（约定）"
            )
            overdue_segments.append(segment)
            overdue_interest = segment.interest
            overdue_mode = "约定逾期利率"
        elif annual is not None:
            assert in_term_rate is not None  # annual 非空时必然已赋值
            overdue_rate_applied = in_term_rate
            segment = _build_segment(
                principal_used, in_term_rate, due, sue, "逾期（按借期内利率）"
            )
            overdue_segments.append(segment)
            overdue_interest = segment.interest
            overdue_mode = "按借期内利率"
        else:
            if lpr_mode == "segmented":
                segmented = segmented_interest(
                    principal_used, lpr_on, due, sue, label="逾期（LPR分段）"
                )
                overdue_segments.extend(segmented.segments)
                overdue_interest = segmented.total
                overdue_mode = "LPR分段"
                warnings.append(
                    "借期内利率与逾期利率均未约定：依司法解释第 28 条，"
                    "逾期利息按逾期期间各段一年期 LPR 计算（本工具默认分段口径）。"
                )
            else:
                snapshot_rate = lpr_on(due)
                overdue_rate_applied = snapshot_rate
                segment = _build_segment(
                    principal_used, snapshot_rate, due, sue, "逾期（LPR快照）"
                )
                overdue_segments.append(segment)
                overdue_interest = segment.interest
                overdue_mode = "LPR快照（逾期日）"
                warnings.append(
                    "借期内利率与逾期利率均未约定：按逾期日一年期 LPR 固定计算"
                    "（部分法院采用该口径）。"
                )
    elif sue is None:
        warnings.append("未提供起诉日：只计算到约定还款日，未计逾期利息。")

    segments.extend(overdue_segments)
    total_interest = in_term_interest + overdue_interest
    claimed_fees_total = total_interest + penalty_amount + other_amount

    # ---------------- 4 × LPR 上限校验 ----------------
    cap_end = sue if sue is not None else due
    cap = cap_check(
        principal_used,
        reference_date,
        borrow,
        cap_end,
        claimed_fees_total,
        cap_annual_rate=cap_rate,
    )
    penalty_headroom = max(
        cap.cap_amount - total_interest - other_amount, Decimal("0.00")
    )
    if penalty_amount > penalty_headroom:
        warnings.append(
            f"违约金 {_fmt_money(penalty_amount)} 元超过扣除利息、其他费用后的"
            f"上限空间 {_fmt_money(penalty_headroom)} 元；利息、违约金、其他费用"
            "合计超过 4 × LPR 的部分不予支持。"
        )

    return ClaimResult(
        claimed_principal=claimed_principal,
        principal=principal_used,
        borrow_date=borrow,
        contract_date=contract,
        due_date=due,
        sue_date=sue,
        cap_lpr_date=reference_date,
        cap_lpr=reference_lpr,
        cap_annual_rate=cap_rate,
        in_term_rate=in_term_rate,
        in_term_interest=in_term_interest,
        overdue_interest=overdue_interest,
        overdue_rate_applied=overdue_rate_applied,
        overdue_mode=overdue_mode,
        total_interest=total_interest,
        penalty=penalty_amount,
        other_fees=other_amount,
        claimed_fees_total=claimed_fees_total,
        supported_fees_total=cap.supported_total,
        excess_fees=cap.excess,
        penalty_headroom=penalty_headroom,
        total_claimed=principal_used + claimed_fees_total,
        total_supported=principal_used + cap.supported_total,
        cap=cap,
        segments=tuple(segments),
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------


def _fmt_money(amount: Decimal) -> str:
    """金额显示：千分位 + 2 位小数，如 ``100,000.00``。"""
    return f"{amount:,.2f}"


def _fmt_rate(rate: Decimal) -> str:
    """利率显示：百分数 + 2 位小数，如 ``3.65%``。"""
    return f"{rate * Decimal(100):.2f}%"


def _display_width(text: str) -> int:
    """计算终端显示宽度（中日韩全角字符按 2 列计）。"""
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text
    )


def _pad(text: str, width: int, *, align: str = "left") -> str:
    """按终端显示宽度补空格（避免中文导致表格错位）。"""
    padding = " " * max(width - _display_width(text), 0)
    return text + padding if align == "left" else padding + text


def render_report(result: ClaimResult) -> str:
    """把 :class:`ClaimResult` 渲染成适合命令行打印的中文明细表。"""
    line = "=" * 68
    thin = "-" * 68
    lines: "list[str]" = [
        line,
        "民间借贷利息与违约金计算明细",
        "依据：法释〔2020〕17 号（利率上限 = 合同成立时一年期 LPR × 4）",
        line,
        "【基本参数】",
        f"  借条本金：              {_fmt_money(result.claimed_principal)} 元",
        f"  实际计息本金：          {_fmt_money(result.principal)} 元",
        f"  实际出借日：            {result.borrow_date.isoformat()}",
        f"  合同成立日：            {result.contract_date.isoformat()}",
        f"  约定还款日：            {result.due_date.isoformat()}",
        f"  起诉日 / 截止日：       "
        f"{result.sue_date.isoformat() if result.sue_date else '未提供（计至还款日）'}",
        f"  上限参照 LPR 日期：     {result.cap_lpr_date.isoformat()}",
        f"  参照一年期 LPR：        {_fmt_rate(result.cap_lpr)}",
        f"  四倍上限年利率：        {_fmt_rate(result.cap_annual_rate)}",
        "",
        "【计息明细】（区间左闭右开，算头不算尾；每段利息四舍五入至分）",
    ]

    if result.segments:
        header = (
            f"  {_pad('期间', 25)}"
            f"{_pad('天数', 6, align='right')}"
            f"{_pad('年利率', 10, align='right')}"
            f"{_pad('利息(元)', 16, align='right')}"
            f"  类型"
        )
        lines.append(header)
        lines.append("  " + "-" * 64)
        for segment in result.segments:
            lines.append(
                f"  {_pad(f'{segment.start.isoformat()} ~ {segment.end.isoformat()}', 25)}"
                f"{_pad(str(segment.days), 6, align='right')}"
                f"{_pad(_fmt_rate(segment.annual_rate), 10, align='right')}"
                f"{_pad(_fmt_money(segment.interest), 16, align='right')}"
                f"  {segment.label}"
            )
    else:
        lines.append("  （无计息区间）")

    lines.extend(
        [
            "",
            "【利息与费用】",
            f"  借期内利息：            {_fmt_money(result.in_term_interest)} 元"
            + (
                f"（适用年利率 {_fmt_rate(result.in_term_rate)}）"
                if result.in_term_rate is not None
                else "（未约定，视为无息）"
            ),
            f"  逾期利息：              {_fmt_money(result.overdue_interest)} 元"
            f"（{result.overdue_mode}）",
            f"  利息合计：              {_fmt_money(result.total_interest)} 元",
            f"  违约金：                {_fmt_money(result.penalty)} 元",
            f"  其他费用：              {_fmt_money(result.other_fees)} 元",
            f"  主张费用合计（息+违约金+其他）：{_fmt_money(result.claimed_fees_total)} 元",
            "",
            "【4 × LPR 上限校验】",
            f"  借款期间：              {result.cap.start.isoformat()} ~ "
            f"{result.cap.end.isoformat()}（{result.cap.days} 天）",
            f"  上限金额：              {_fmt_money(result.cap.cap_amount)} 元"
            f"（{_fmt_money(result.principal)} × {_fmt_rate(result.cap_annual_rate)}"
            f" × {result.cap.days}/365）",
            f"  主张费用合计：          {_fmt_money(result.cap.claimed_total)} 元",
            f"  可支持费用合计：        {_fmt_money(result.cap.supported_total)} 元",
            f"  超出部分（不予支持）：  {_fmt_money(result.cap.excess)} 元",
            "  结论：                  "
            + (
                "未超过 4 × LPR 上限。"
                if result.cap.passed
                else "超过 4 × LPR 上限，超出部分人民法院不予支持。"
            ),
            f"  违约金可支持空间：      {_fmt_money(result.penalty_headroom)} 元"
            "（扣除利息、其他费用后的上限余额）",
            "",
            "【合计】",
            f"  本金：                  {_fmt_money(result.principal)} 元",
            f"  可支持利息及费用：      {_fmt_money(result.cap.supported_total)} 元",
            f"  可支持合计：            {_fmt_money(result.total_supported)} 元",
        ]
    )
    if result.excess_fees > 0:
        lines.append(f"  主张合计（含不予支持部分）：{_fmt_money(result.total_claimed)} 元")

    lines.append("")
    lines.append("【提示】")
    if result.warnings:
        lines.extend(f"  - {warning}" for warning in result.warnings)
    else:
        lines.append("  - 无特别提示。")
    lines.extend(
        [
            "",
            thin,
            "说明：本工具结果仅供参考，不构成正式法律意见；具体以法院认定为准。",
            line,
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 命令行接口
# ---------------------------------------------------------------------------


def _parse_money(value: str) -> Decimal:
    """argparse 金额解析：允许千分位、￥/¥/元，必须非负。"""
    text = value.strip().replace(",", "").replace("，", "")
    for symbol in ("¥", "￥", "元"):
        text = text.replace(symbol, "")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"金额格式不正确：{value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise argparse.ArgumentTypeError(f"金额必须是非负有限数值：{value!r}")
    return amount


def _parse_rate(value: str) -> Decimal:
    """argparse 利率解析：支持 ``0.12`` 或 ``12%`` 两种写法，必须非负。"""
    text = value.strip()
    try:
        rate = Decimal(text[:-1]) / Decimal(100) if text.endswith("%") else Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"利率格式不正确：{value!r}") from exc
    if not rate.is_finite() or rate < 0:
        raise argparse.ArgumentTypeError(f"利率必须是非负有限数值：{value!r}")
    return rate


def _parse_date(value: str) -> date:
    """argparse 日期解析：要求 ISO 格式 ``YYYY-MM-DD``。"""
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"日期格式应为 YYYY-MM-DD，收到：{value!r}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="interest_calculator.py",
        description=(
            "民间借贷利息与违约金计算器（法释〔2020〕17 号口径）："
            "按合同成立时一年期 LPR 的 4 倍校验利率上限，并按实际天数分段计息。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 scripts/interest_calculator.py \\\n"
            "    --principal 100000 --contract-date 2023-01-01 \\\n"
            "    --due-date 2023-07-01 --annual-rate 0.12 --sue-date 2025-01-01\n\n"
            "利率可写 0.12 或 12%；金额可写 100000 或 100,000；日期为 YYYY-MM-DD。\n"
            "计息区间左闭右开（算头不算尾），金额四舍五入保留 2 位小数。"
        ),
    )
    parser.add_argument(
        "--principal", required=True, type=_parse_money, metavar="金额",
        help="借条 / 合同载明的本金（元）",
    )
    parser.add_argument(
        "--contract-date", required=True, type=_parse_date, metavar="YYYY-MM-DD",
        help="合同成立日（用于快照合同成立时一年期 LPR）",
    )
    parser.add_argument(
        "--due-date", required=True, type=_parse_date, metavar="YYYY-MM-DD",
        help="约定还款日（逾期利息自该日起算）",
    )
    parser.add_argument(
        "--sue-date", type=_parse_date, metavar="YYYY-MM-DD", default=None,
        help="起诉日 / 计算截止日；不传则只计至还款日，不计逾期利息",
    )
    parser.add_argument(
        "--annual-rate", type=_parse_rate, metavar="年利率", default=None,
        help="借期内约定年利率（小数或百分数，如 0.12 / 12%%）；不传视为未约定",
    )
    parser.add_argument(
        "--overdue-rate", type=_parse_rate, metavar="年利率", default=None,
        help="约定逾期年利率；不传则按借期内利率或 LPR 推定",
    )
    parser.add_argument(
        "--penalty", type=_parse_money, metavar="金额", default=Decimal("0"),
        help="违约金金额（元，固定金额）",
    )
    parser.add_argument(
        "--other-fees", type=_parse_money, metavar="金额", default=Decimal("0"),
        help="其他费用金额（元），与利息、违约金合并受 4 × LPR 上限约束",
    )
    parser.add_argument(
        "--actual-disbursed", type=_parse_money, metavar="金额", default=None,
        help="实际出借金额（砍头息情形，以实际出借金额为本金）",
    )
    parser.add_argument(
        "--borrow-date", type=_parse_date, metavar="YYYY-MM-DD", default=None,
        help="实际出借日，默认等于合同成立日",
    )
    parser.add_argument(
        "--lpr-mode", choices=("segmented", "snapshot"), default="segmented",
        help="均未约定利率时的逾期 LPR 口径：segmented=按 LPR 调整分段（默认），"
             "snapshot=按逾期日 LPR 固定",
    )
    parser.add_argument(
        "--non-natural-persons", action="store_true",
        help="至少一方非自然人（影响未约定利息的提示口径）",
    )
    parser.add_argument(
        "--cap-lpr-date", type=_parse_date, metavar="YYYY-MM-DD", default=None,
        help="仅用于合同成立日早于 2019-08-20 的情形：参照起诉时 LPR 的日期",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口；参数或业务校验失败时以退出码 2 报错。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = calculate_claim(
            principal=args.principal,
            contract_date=args.contract_date,
            due_date=args.due_date,
            sue_date=args.sue_date,
            annual_rate=args.annual_rate,
            overdue_rate=args.overdue_rate,
            penalty=args.penalty,
            other_fees=args.other_fees,
            actual_disbursed=args.actual_disbursed,
            natural_persons=not args.non_natural_persons,
            lpr_mode=args.lpr_mode,
            cap_lpr_date=args.cap_lpr_date,
            borrow_date=args.borrow_date,
        )
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(render_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
