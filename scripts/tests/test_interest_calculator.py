"""民间借贷利息计算器单元测试。

运行方式（仓库根目录）：``python3 -m pytest -q``

计算口径（与 ``interest_calculator.py`` 一致）：
- 计息区间左闭右开 ``[start, end)``，天数 = 两日期之差，算头不算尾；
- 利息 = 本金 × 年利率 × 天数 ÷ 365；
- 金额四舍五入（ROUND_HALF_UP）保留 2 位小数，分段计息时每段单独舍入后相加。

每个用例的期望值都在注释中给出计算过程，便于人工复核。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# scripts/ 目录下没有 __init__.py，直接把该目录加入 sys.path 再导入模块，
# 这样无论从仓库根目录还是用 pytest 控制台脚本运行都能导入。
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import interest_calculator as calc  # noqa: E402  （必须先插入 sys.path）

CLI = [sys.executable, str(SCRIPTS_DIR / "interest_calculator.py")]


def _run_cli(*args: str) -> "subprocess.CompletedProcess[str]":
    """运行命令行脚本并捕获输出（UTF-8）。"""
    return subprocess.run(
        [*CLI, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


# ---------------------------------------------------------------------------
# LPR 表与查询
# ---------------------------------------------------------------------------


def test_lpr_table_sorted_ascending() -> None:
    """LPR_TABLE 必须按日期升序，且利率为 Decimal 小数形式。"""
    dates = list(calc.LPR_TABLE)
    assert dates == sorted(dates), "LPR_TABLE 必须按日期升序排列"
    assert dates[0] == "2019-08-20"
    assert dates[-1] == "2025-05-20"
    assert all(isinstance(rate, Decimal) for rate in calc.LPR_TABLE.values())


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ("2019-08-20", Decimal("0.0425")),
        ("2020-04-20", Decimal("0.0385")),
        ("2021-12-20", Decimal("0.0380")),
        ("2022-08-22", Decimal("0.0365")),
        ("2023-06-20", Decimal("0.0355")),
        ("2023-08-21", Decimal("0.0345")),
        ("2024-07-22", Decimal("0.0335")),
        ("2024-10-21", Decimal("0.0310")),
        ("2025-05-20", Decimal("0.0300")),
    ],
)
def test_lpr_table_known_values(when: str, expected: Decimal) -> None:
    """抽查 LPR 调整日当天的报价（来源见模块顶部注释）。"""
    assert calc.lpr_on(when) == expected


def test_lpr_on_carries_forward_last_quote() -> None:
    """非报价日沿用最近一期 LPR。"""
    assert calc.lpr_on("2023-07-15") == Decimal("0.0355")  # 2023-06-20 报价 3.55%
    assert calc.lpr_on("2022-05-20") == Decimal("0.0370")  # 当日仅 5 年期调整
    assert calc.lpr_on("2024-02-20") == Decimal("0.0345")  # 当日仅 5 年期调整
    assert calc.lpr_on("2026-10-20") == Decimal("0.0300")  # 最新一期
    # 查表逻辑：未调整则延续上一期（这是算法行为断言，不是对未来 LPR 的预测）
    assert calc.lpr_on("2030-01-01") == Decimal("0.0300")


def test_lpr_on_before_first_quote_raises() -> None:
    """2019-08-20 之前没有 LPR，应抛出清晰 ValueError。"""
    with pytest.raises(ValueError, match="2019-08-20"):
        calc.lpr_on("2019-08-19")


def test_lpr_on_accepts_date_object() -> None:
    assert calc.lpr_on(date(2023, 1, 1)) == Decimal("0.0365")


@pytest.mark.parametrize(
    ("contract_date", "expected"),
    [
        # 2023-01-01：适用 2022-08-22 的 3.65%，3.65% × 4 = 14.6%
        ("2023-01-01", Decimal("0.146")),
        # 2024-01-01：适用 2023-08-21 的 3.45%，3.45% × 4 = 13.8%
        ("2024-01-01", Decimal("0.138")),
        # 2025-06-01：适用 2025-05-20 的 3.00%，3.00% × 4 = 12%
        ("2025-06-01", Decimal("0.120")),
    ],
)
def test_four_times_lpr_snapshot(contract_date: str, expected: Decimal) -> None:
    """4 × LPR 以合同成立日当天的 LPR 为快照，不随后续调整而变化。"""
    assert calc.four_times_lpr(contract_date) == expected


# ---------------------------------------------------------------------------
# 单利
# ---------------------------------------------------------------------------


def test_simple_interest_one_day() -> None:
    """100,000 × 12% ÷ 365 × 1 = 32.876712... → 32.88（四舍五入）。"""
    interest = calc.simple_interest("100000", "0.12", "2023-01-01", "2023-01-02")
    assert interest == Decimal("32.88")


def test_simple_interest_full_year_365_days() -> None:
    """2023-01-01 至 2024-01-01 共 365 天：100,000 × 12% × 365/365 = 12,000.00。"""
    interest = calc.simple_interest("100000", "0.12", "2023-01-01", "2024-01-01")
    assert interest == Decimal("12000.00")


def test_simple_interest_leap_year_366_days() -> None:
    """2024 年为闰年（含 2 月 29 日），2024-01-01 至 2025-01-01 共 366 天。

    100,000 × 12% × 366/365 = 12,032.8767... → 12,032.88。
    """
    interest = calc.simple_interest("100000", "0.12", "2024-01-01", "2025-01-01")
    assert interest == Decimal("12032.88")


def test_simple_interest_zero_days() -> None:
    """起止日相同（区间为空）时利息为 0，且不抛异常。"""
    assert calc.simple_interest("100000", "0.12", "2023-01-01", "2023-01-01") == Decimal(
        "0.00"
    )


def test_simple_interest_half_up_rounding() -> None:
    """验证 ROUND_HALF_UP：3668.25 × 10% ÷ 365 = 1.005 → 进位为 1.01。

    （银行家舍入 / ROUND_HALF_EVEN 会得到 1.00，本工具明确采用四舍五入。）
    """
    interest = calc.simple_interest(
        Decimal("3668.25"), Decimal("0.10"), "2024-01-01", "2024-01-02"
    )
    assert interest == Decimal("1.01")


def test_simple_interest_reversed_dates_raises() -> None:
    with pytest.raises(ValueError, match="不能早于"):
        calc.simple_interest("100000", "0.12", "2023-07-01", "2023-01-01")


@pytest.mark.parametrize(
    ("principal", "rate"),
    [
        ("-1", "0.12"),  # 本金为负
        ("100000", "-0.12"),  # 利率为负
    ],
)
def test_simple_interest_invalid_inputs_raise(principal: str, rate: str) -> None:
    with pytest.raises(ValueError):
        calc.simple_interest(principal, rate, "2023-01-01", "2023-01-02")


def test_simple_interest_rejects_nan() -> None:
    with pytest.raises(ValueError, match="有限"):
        calc.simple_interest("100000", "NaN", "2023-01-01", "2023-01-02")


# ---------------------------------------------------------------------------
# 分段计息
# ---------------------------------------------------------------------------


def test_segmented_interest_splits_on_lpr_change() -> None:
    """按 LPR 调整分段：2023-06-01 至 2023-09-01，本金 100,000。

    分段（左闭右开）：
      06-01 ~ 06-20：19 天，3.65% → 100000×0.0365×19/365 = 190.0000 → 190.00
      06-20 ~ 08-21：62 天，3.55% → 100000×0.0355×62/365 = 603.0137 → 603.01
      08-21 ~ 09-01：11 天，3.45% → 100000×0.0345×11/365 = 103.9726 → 103.97
    合计 190.00 + 603.01 + 103.97 = 896.98。
    """
    result = calc.segmented_interest("100000", calc.lpr_on, "2023-06-01", "2023-09-01")

    assert [segment.days for segment in result.segments] == [19, 62, 11]
    assert [segment.annual_rate for segment in result.segments] == [
        Decimal("0.0365"),
        Decimal("0.0355"),
        Decimal("0.0345"),
    ]
    assert [segment.interest for segment in result.segments] == [
        Decimal("190.00"),
        Decimal("603.01"),
        Decimal("103.97"),
    ]
    assert result.total == Decimal("896.98")
    # 每段单独舍入后相加，故各段之和必须等于 total。
    assert sum(segment.interest for segment in result.segments) == result.total


def test_segmented_interest_single_rate_provider() -> None:
    """利率不变时只产生一段：100000×10%×181/365 = 4958.9041 → 4958.90。"""
    provider = lambda _when: Decimal("0.10")  # noqa: E731
    result = calc.segmented_interest("100000", provider, "2023-01-01", "2023-07-01")

    assert len(result.segments) == 1
    assert result.segments[0].days == 181
    assert result.total == Decimal("4958.90")


def test_segmented_interest_zero_length() -> None:
    result = calc.segmented_interest("100000", calc.lpr_on, "2023-01-01", "2023-01-01")
    assert result.total == Decimal("0.00")
    assert result.segments == ()


def test_segmented_interest_rate_provider_must_be_callable() -> None:
    with pytest.raises(TypeError, match="可调用"):
        calc.segmented_interest("100000", "0.10", "2023-01-01", "2023-07-01")  # type: ignore[arg-type]


def test_segmented_interest_negative_rate_raises() -> None:
    provider = lambda _when: Decimal("-0.10")  # noqa: E731
    with pytest.raises(ValueError, match="不能为负数"):
        calc.segmented_interest("100000", provider, "2023-01-01", "2023-07-01")


# ---------------------------------------------------------------------------
# calculate_claim：利率上限与借期内利息
# ---------------------------------------------------------------------------


def test_calculate_claim_basic_example() -> None:
    """CLI 示例：本金 10 万，2023-01-01 合同、2023-07-01 到期，年利率 12%，2025-01-01 起诉。

    借期内：181 天 × 12% → 100000×0.12×181/365 = 5950.6849 → 5,950.68
    逾期（按借期内利率）：550 天 × 12% → 100000×0.12×550/365 = 18082.1918 → 18,082.19
    利息合计：24,032.87
    上限：4×3.65% = 14.6%，期间 731 天 → 100000×0.146×731/365 = 29,240.00
    可支持合计：100000 + 24032.87 = 124,032.87
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.12",
        sue_date="2025-01-01",
    )

    assert result.in_term_interest == Decimal("5950.68")
    assert result.overdue_interest == Decimal("18082.19")
    assert result.total_interest == Decimal("24032.87")
    assert result.overdue_mode == "按借期内利率"
    assert result.cap_annual_rate == Decimal("0.146")
    assert result.cap.cap_amount == Decimal("29240.00")
    assert result.cap.passed is True
    assert result.cap.excess == Decimal("0.00")
    assert result.total_supported == Decimal("124032.87")
    assert result.warnings == ()


def test_contract_lpr_snapshot_without_later_adjustment() -> None:
    """上限用合同成立日 LPR 快照：2023-01-01 为 3.65%，之后 LPR 下调不影响上限。"""
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", annual_rate="0.12"
    )
    assert result.cap_lpr == Decimal("0.0365")
    assert result.cap_annual_rate == Decimal("0.146")
    assert result.in_term_rate == Decimal("0.12")
    # 未提供起诉日，只提示「未计逾期利息」，不应有超上限提示。
    assert not any("上限" in warning for warning in result.warnings)


def test_in_term_over_cap_is_clipped() -> None:
    """约定 20% > 14.6%：按上限 14.6% 计息，超出部分不予支持。

    100000×0.146×181/365 = 7240.00（恰好为整数）。
    """
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", annual_rate="0.20"
    )

    assert result.in_term_rate == Decimal("0.146")
    assert result.in_term_interest == Decimal("7240.00")
    assert result.cap.passed is True
    assert result.total_supported == Decimal("107240.00")
    assert any("超过 4 × LPR 上限" in warning for warning in result.warnings)


def test_over_cap_whole_period_equals_cap_boundary() -> None:
    """约定 30%，借期 + 逾期均被裁剪到 14.6%，截至 2024-01-01 合计恰等于上限。

    借期内 181 天：100000×0.146×181/365 = 7240.00
    逾期  184 天：100000×0.146×184/365 = 7360.00
    合计 14,600.00；上限 100000×0.146×365/365 = 14,600.00（未超过）。
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.30",
        sue_date="2024-01-01",
    )

    assert result.in_term_interest == Decimal("7240.00")
    assert result.overdue_interest == Decimal("7360.00")
    assert result.total_interest == Decimal("14600.00")
    assert result.cap.cap_amount == Decimal("14600.00")
    assert result.cap.passed is True
    assert result.cap.excess == Decimal("0.00")


# ---------------------------------------------------------------------------
# 未约定利息 / 逾期利率三种情形
# ---------------------------------------------------------------------------


def test_no_interest_between_natural_persons() -> None:
    """自然人之间未约定利息：视为无息（《民法典》第 680 条）。"""
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", sue_date="2024-01-01"
    )

    assert result.in_term_rate is None
    assert result.in_term_interest == Decimal("0.00")
    # 未约定借期内利率、也未约定逾期利率 → 逾期按 LPR（分段）计算。
    assert result.overdue_interest == Decimal("1753.15")
    assert result.total_interest == Decimal("1753.15")
    assert any("视为无息" in warning for warning in result.warnings)


def test_no_interest_non_natural_warns_court_discretion() -> None:
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", natural_persons=False
    )
    assert result.in_term_interest == Decimal("0.00")
    assert any("酌定" in warning for warning in result.warnings)


def test_overdue_agreed_rate_is_used() -> None:
    """有约定逾期利率从约定：10% 借期内 + 12% 逾期。

    逾期 184 天：100000×0.12×184/365 = 6049.3151 → 6,049.32
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.10",
        overdue_rate="0.12",
        sue_date="2024-01-01",
    )

    assert result.overdue_mode == "约定逾期利率"
    assert result.overdue_rate_applied == Decimal("0.12")
    assert result.overdue_interest == Decimal("6049.32")
    assert result.total_interest == Decimal("11008.22")  # 4958.90 + 6049.32


def test_overdue_agreed_rate_over_cap_is_clipped() -> None:
    """约定逾期利率 15% > 14.6%：按 14.6% 计算。

    184 天：100000×0.146×184/365 = 7360.00。
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.10",
        overdue_rate="0.15",
        sue_date="2024-01-01",
    )

    assert result.overdue_rate_applied == Decimal("0.146")
    assert result.overdue_interest == Decimal("7360.00")
    assert any("约定逾期年利率" in warning for warning in result.warnings)


def test_overdue_falls_back_to_in_term_rate() -> None:
    """未约定逾期利率但约定了借期内利率 10%：逾期也按 10% 计算。

    借期内 181 天 4,958.90 + 逾期 184 天 5,041.10 = 10,000.00（整一年）。
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.10",
        sue_date="2024-01-01",
    )

    assert result.overdue_mode == "按借期内利率"
    assert result.overdue_rate_applied == Decimal("0.10")
    assert result.overdue_interest == Decimal("5041.10")
    assert result.total_interest == Decimal("10000.00")


def test_overdue_lpr_segmented() -> None:
    """两者均未约定：逾期利息按 LPR 分段（2023-07-01 至 2024-01-01）。

    07-01 ~ 08-21：51 天，3.55% → 496.0274 → 496.03
    08-21 ~ 01-01：133 天，3.45% → 1257.1233 → 1,257.12
    合计 1,753.15。
    """
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", sue_date="2024-01-01"
    )

    assert result.overdue_mode == "LPR分段"
    assert result.overdue_interest == Decimal("1753.15")
    overdue_segments = [seg for seg in result.segments if seg.label == "逾期（LPR分段）"]
    assert [segment.days for segment in overdue_segments] == [51, 133]
    assert [segment.interest for segment in overdue_segments] == [
        Decimal("496.03"),
        Decimal("1257.12"),
    ]


def test_overdue_lpr_snapshot_mode() -> None:
    """snapshot 口径：按逾期日 LPR 3.55% 固定计算 184 天。

    100000×0.0355×184/365 = 1789.5890 → 1,789.59。
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        sue_date="2024-01-01",
        lpr_mode="snapshot",
    )

    assert result.overdue_mode == "LPR快照（逾期日）"
    assert result.overdue_rate_applied == Decimal("0.0355")
    assert result.overdue_interest == Decimal("1789.59")
    assert len(result.segments) == 1  # 无借期内分段（未约定利息），仅一段逾期


# ---------------------------------------------------------------------------
# 砍头息
# ---------------------------------------------------------------------------


def test_kou_tou_xi_uses_actual_disbursed_principal() -> None:
    """砍头息：借条 100,000、实际出借 95,000，以 95,000 为本金计息。

    借期内 181 天 × 10%：95000×0.10×181/365 = 4710.9589 → 4,710.96
    上限（181 天）：95000×0.146×181/365 = 6878.00
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.10",
        actual_disbursed="95000",
    )

    assert result.claimed_principal == Decimal("100000.00")
    assert result.principal == Decimal("95000.00")
    assert result.in_term_interest == Decimal("4710.96")
    assert result.cap.base_principal == Decimal("95000.00")
    assert result.cap.cap_amount == Decimal("6878.00")
    assert result.total_supported == Decimal("99710.96")  # 95000 + 4710.96
    assert any("砍头息" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# 利息 + 违约金 + 其他费用合计上限
# ---------------------------------------------------------------------------


def test_penalty_pushes_total_over_cap() -> None:
    """利息已达上限 14,600，再加违约金 1,000 → 超出部分 1,000 不予支持。

    利息：14,600.00（365 天 × 14.6%）；主张费用合计 15,600.00；
    上限 14,600.00；可支持 14,600.00；超出 1,000.00；
    可支持合计 = 100000 + 14600 = 114,600.00。
    """
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.146",
        penalty="1000",
        sue_date="2024-01-01",
    )

    assert result.total_interest == Decimal("14600.00")
    assert result.claimed_fees_total == Decimal("15600.00")
    assert result.cap.passed is False
    assert result.cap.supported_total == Decimal("14600.00")
    assert result.excess_fees == Decimal("1000.00")
    assert result.penalty_headroom == Decimal("0.00")
    assert result.total_supported == Decimal("114600.00")
    assert any("违约金" in warning for warning in result.warnings)


def test_other_fees_count_toward_cap() -> None:
    """其他费用同样计入利息 + 违约金 + 其他费用合计上限。"""
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.146",
        other_fees="1000",
        sue_date="2024-01-01",
    )

    assert result.claimed_fees_total == Decimal("15600.00")
    assert result.cap.supported_total == Decimal("14600.00")
    assert result.excess_fees == Decimal("1000.00")


def test_penalty_headroom_is_reported() -> None:
    """未超上限时给出违约金可支持空间。

    借期内利息 5,950.68；上限（181 天）7,240.00；
    可支持空间 = 7240.00 - 5950.68 = 1,289.32，违约金 1,000 未超。
    """
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", annual_rate="0.12", penalty="1000"
    )

    assert result.penalty_headroom == Decimal("1289.32")
    assert result.cap.passed is True
    assert result.cap.excess == Decimal("0.00")
    assert result.total_supported == Decimal("106950.68")  # 100000 + 5950.68 + 1000


def test_cap_check_direct_over_limit() -> None:
    """直接调用 cap_check：100000 × 14.6% × 365/365 = 14,600 上限。"""
    cap = calc.cap_check(
        "100000",
        "2023-01-01",
        "2023-01-01",
        "2024-01-01",
        total_claimed="15600",
    )

    assert cap.days == 365
    assert cap.cap_annual_rate == Decimal("0.146")
    assert cap.cap_amount == Decimal("14600.00")
    assert cap.claimed_total == Decimal("15600.00")
    assert cap.supported_total == Decimal("14600.00")
    assert cap.excess == Decimal("1000.00")
    assert cap.headroom == Decimal("0.00")
    assert cap.passed is False


def test_cap_check_direct_within_limit() -> None:
    cap = calc.cap_check(
        "100000", "2023-01-01", "2023-01-01", "2024-01-01", total_claimed="10000"
    )
    assert cap.cap_amount == Decimal("14600.00")
    assert cap.supported_total == Decimal("10000.00")
    assert cap.excess == Decimal("0.00")
    assert cap.headroom == Decimal("4600.00")
    assert cap.passed is True


# ---------------------------------------------------------------------------
# 日期边界与异常输入
# ---------------------------------------------------------------------------


def test_sue_date_omitted_means_no_overdue_interest() -> None:
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", annual_rate="0.12"
    )
    assert result.overdue_interest == Decimal("0.00")
    assert result.overdue_mode == "无"
    assert any("未提供起诉日" in warning for warning in result.warnings)


def test_sue_date_equals_due_date_has_no_overdue_interest() -> None:
    result = calc.calculate_claim(
        "100000",
        "2023-01-01",
        "2023-07-01",
        annual_rate="0.12",
        sue_date="2023-07-01",
    )
    assert result.overdue_interest == Decimal("0.00")
    assert result.overdue_mode == "无"


def test_due_date_before_borrow_date_raises() -> None:
    with pytest.raises(ValueError, match="不能早于"):
        calc.calculate_claim("100000", "2023-07-01", "2023-01-01")


def test_sue_date_before_due_date_raises() -> None:
    with pytest.raises(ValueError, match="提前到期"):
        calc.calculate_claim(
            "100000", "2023-01-01", "2023-07-01", sue_date="2023-06-01"
        )


def test_principal_must_be_positive() -> None:
    with pytest.raises(ValueError, match="必须大于 0"):
        calc.calculate_claim("0", "2023-01-01", "2023-07-01")


def test_actual_disbursed_cannot_exceed_principal() -> None:
    with pytest.raises(ValueError, match="不能大于借条本金"):
        calc.calculate_claim(
            "100000", "2023-01-01", "2023-07-01", actual_disbursed="100001"
        )


@pytest.mark.parametrize(
    ("kwargs", "exception"),
    [
        ({"penalty": "-1"}, ValueError),
        ({"other_fees": "-1"}, ValueError),
        ({"annual_rate": "-0.1"}, ValueError),
        ({"overdue_rate": "-0.1"}, ValueError),
        ({"lpr_mode": "daily"}, ValueError),
        ({"natural_persons": "yes"}, TypeError),
    ],
)
def test_calculate_claim_invalid_arguments_raise(
    kwargs: "dict[str, object]", exception: "type[Exception]"
) -> None:
    with pytest.raises(exception):
        calc.calculate_claim("100000", "2023-01-01", "2023-07-01", **kwargs)  # type: ignore[arg-type]


def test_contract_before_2019_requires_cap_lpr_date() -> None:
    """2019-08-20 前无 LPR，必须指定参照日期（司法解释第 31 条）。"""
    with pytest.raises(ValueError, match="cap_lpr_date"):
        calc.calculate_claim("100000", "2018-06-01", "2018-12-01", annual_rate="0.12")


def test_contract_before_2019_with_cap_lpr_date() -> None:
    """参照 2025-01-01 的 LPR 3.10% → 上限 12.4%。"""
    result = calc.calculate_claim(
        "100000",
        "2018-06-01",
        "2018-12-01",
        annual_rate="0.12",
        cap_lpr_date="2025-01-01",
    )

    assert result.cap_lpr == Decimal("0.031")
    assert result.cap_annual_rate == Decimal("0.124")
    assert any("第 31 条" in warning for warning in result.warnings)


def test_cap_lpr_date_rejected_for_post_2019_contract() -> None:
    with pytest.raises(ValueError, match="仅用于"):
        calc.calculate_claim(
            "100000",
            "2023-01-01",
            "2023-07-01",
            cap_lpr_date="2025-01-01",
        )


def test_claim_result_is_json_serializable() -> None:
    result = calc.calculate_claim(
        "100000", "2023-01-01", "2023-07-01", annual_rate="0.12"
    )
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "借期内" in payload
    assert result.lending_period_days == 181


# ---------------------------------------------------------------------------
# 命令行接口
# ---------------------------------------------------------------------------


def test_cli_help_works() -> None:
    completed = _run_cli("--help")
    assert completed.returncode == 0
    assert "民间借贷利息与违约金计算器" in completed.stdout
    assert "--principal" in completed.stdout


def test_cli_sample_output() -> None:
    completed = _run_cli(
        "--principal",
        "100000",
        "--contract-date",
        "2023-01-01",
        "--due-date",
        "2023-07-01",
        "--annual-rate",
        "0.12",
        "--sue-date",
        "2025-01-01",
    )
    assert completed.returncode == 0, completed.stderr
    assert "29,240.00" in completed.stdout  # 4 × LPR 上限金额
    assert "124,032.87" in completed.stdout  # 可支持合计
    assert "未超过 4 × LPR 上限" in completed.stdout


def test_cli_accepts_percent_rate_and_penalty() -> None:
    completed = _run_cli(
        "--principal",
        "100,000",
        "--contract-date",
        "2023-01-01",
        "--due-date",
        "2023-07-01",
        "--annual-rate",
        "12%",
        "--penalty",
        "1000",
    )
    assert completed.returncode == 0, completed.stderr
    assert "5,950.68" in completed.stdout
    assert "1,289.32" in completed.stdout  # 违约金可支持空间


def test_cli_invalid_date_reports_clear_error() -> None:
    completed = _run_cli(
        "--principal", "100000", "--contract-date", "2023-13-01", "--due-date", "2023-07-01"
    )
    assert completed.returncode == 2
    assert "日期格式应为 YYYY-MM-DD" in completed.stderr


def test_cli_business_error_exit_code() -> None:
    completed = _run_cli(
        "--principal", "100000", "--contract-date", "2023-07-01", "--due-date", "2023-01-01"
    )
    assert completed.returncode == 2
    assert "不能早于" in completed.stderr


def test_cli_missing_required_argument() -> None:
    completed = _run_cli("--contract-date", "2023-01-01", "--due-date", "2023-07-01")
    assert completed.returncode == 2
    assert "--principal" in completed.stderr
