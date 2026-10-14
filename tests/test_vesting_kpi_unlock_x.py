import pytest
import json
from gltest import *
from conftest import sim_installMocks


@pytest.fixture
def contract(direct_deploy):
    return direct_deploy("contracts/vesting_kpi_unlock_x.py")


def test_initial_state_and_domain_management(contract, direct_vm, direct_alice, direct_bob):
    # Initial state checks
    assert contract.get_schedule_count() == 0
    owner_str = contract.get_owner().lower()
    expected_sender = direct_vm.sender.hex().lower() if isinstance(direct_vm.sender, bytes) else str(direct_vm.sender).lower()
    if not expected_sender.startswith("0x"):
        expected_sender = "0x" + expected_sender
    assert owner_str == expected_sender

    # Default canonical analytics domains
    assert contract.is_analytics_domain_allowed("defillama.com") is True
    assert contract.is_analytics_domain_allowed("api.llama.fi") is True
    assert contract.is_analytics_domain_allowed("dune.com") is True
    assert contract.is_analytics_domain_allowed("api.dune.com") is True
    assert contract.is_analytics_domain_allowed("github.com") is True
    assert contract.is_analytics_domain_allowed("api.github.com") is True
    assert contract.is_analytics_domain_allowed("etherscan.io") is True
    assert contract.is_analytics_domain_allowed("api.etherscan.io") is True
    assert contract.is_analytics_domain_allowed("mock-analytics.genlayer.com") is True
    assert contract.is_analytics_domain_allowed("untrusted-fake-metrics.org") is False

    # Owner adds custom allowed metrics domain
    contract.add_allowed_analytics_domain("tokenterminal.com")
    assert contract.is_analytics_domain_allowed("tokenterminal.com") is True

    # Owner removes allowed metrics domain
    contract.remove_allowed_analytics_domain("tokenterminal.com")
    assert contract.is_analytics_domain_allowed("tokenterminal.com") is False

    # Non-owner cannot add domain
    direct_vm.sender = direct_bob
    with pytest.raises(Exception, match="Only contract owner can add allowed domains"):
        contract.add_allowed_analytics_domain("fraud-stats.io")

    # Non-owner cannot remove domain
    with pytest.raises(Exception, match="Only contract owner can remove allowed domains"):
        contract.remove_allowed_analytics_domain("dune.com")


def test_create_vesting_schedule_success(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 10000  # Funder locks 10,000 GEN

    sid = contract.create_vesting_schedule(
        beneficiary=direct_alice,
        kpi_metric_description="DeFiLlama TVL exceeds $10,000,000 with minimum 100,000 total volume",
        metrics_url="https://api.llama.fi/protocol/sample-protocol",
        duration_sec=86400 * 30
    )

    assert sid == "1"
    assert contract.get_schedule_count() == 1

    s = json.loads(contract.get_schedule("1"))
    assert s["schedule_id"] == "1"
    assert s["funder"] == direct_bob.as_hex.lower()
    assert s["beneficiary"] == direct_alice.as_hex.lower()
    assert s["kpi_metric_description"] == "DeFiLlama TVL exceeds $10,000,000 with minimum 100,000 total volume"
    assert s["metrics_url"] == "https://api.llama.fi/protocol/sample-protocol"
    assert s["allocated_amount"] == "10000"
    assert s["released_amount"] == "0"
    assert s["status"] == "ACTIVE"
    assert s["last_verdict"] == "PENDING"
    assert "Awaiting autonomous metric evaluation" in s["last_reason"]


def test_create_vesting_schedule_validations(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_bob

    # 1. Zero allocation
    direct_vm.value = 0
    with pytest.raises(Exception, match="Vesting allocation must be greater than 0 GEN"):
        contract.create_vesting_schedule(
            beneficiary=direct_alice,
            kpi_metric_description="Mainnet transaction count exceeds 500,000",
            metrics_url="https://api.etherscan.io/api?module=stats",
            duration_sec=86400 * 30
        )

    # 2. Self-beneficiary
    direct_vm.value = 5000
    with pytest.raises(Exception, match="Funder cannot set self as beneficiary"):
        contract.create_vesting_schedule(
            beneficiary=direct_bob,
            kpi_metric_description="Mainnet transaction count exceeds 500,000",
            metrics_url="https://api.etherscan.io/api?module=stats",
            duration_sec=86400 * 30
        )

    # 3. KPI description too short
    with pytest.raises(Exception, match="kpi_metric_description must be detailed"):
        contract.create_vesting_schedule(
            beneficiary=direct_alice,
            kpi_metric_description="TVL high",
            metrics_url="https://api.etherscan.io/api?module=stats",
            duration_sec=86400 * 30
        )

    # 4. Invalid URL scheme
    with pytest.raises(Exception, match="metrics_url must start with http:// or https://"):
        contract.create_vesting_schedule(
            beneficiary=direct_alice,
            kpi_metric_description="Mainnet transaction count exceeds 500,000",
            metrics_url="ftp://api.etherscan.io/stats",
            duration_sec=86400 * 30
        )

    # 5. Domain not whitelisted
    with pytest.raises(Exception, match="is not in the allowed domain whitelist"):
        contract.create_vesting_schedule(
            beneficiary=direct_alice,
            kpi_metric_description="Mainnet transaction count exceeds 500,000",
            metrics_url="https://untrusted-metrics-source.xyz/stats",
            duration_sec=86400 * 30
        )


def test_evaluate_kpi_achieved_full_unlock(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 25000  # 25,000 GEN allocated

    sid = contract.create_vesting_schedule(
        beneficiary=direct_alice,
        kpi_metric_description="DeFiLlama TVL surpasses $10,000,000 USD",
        metrics_url="https://api.llama.fi/protocol/dex-alpha",
        duration_sec=86400 * 60
    )

    # Install Mocks for achieved milestone
    sim_installMocks({
        "web_mocks": {
            ".*llama.fi.*": {
                "status": 200,
                "body": "Official DeFiLlama Protocol Metrics for dex-alpha: Current TVL is $14,250,000 USD. 24h trading volume is $2,100,000 USD. Staking active."
            }
        },
        "llm_mocks": {
            ".*": {
                "verdict": "KPI_ACHIEVED",
                "confidence": 99,
                "reason": "Verified on-chain TVL of $14.25M exceeds agreed threshold of $10M."
            }
        }
    }, vm=direct_vm)

    # Evaluate and unlock KPI
    contract.evaluate_and_unlock_kpi(sid)

    s = json.loads(contract.get_schedule(sid))
    assert s["status"] == "COMPLETED"
    assert s["last_verdict"] == "KPI_ACHIEVED"
    assert s["released_amount"] == "25000"
    assert "exceeds agreed threshold of $10M" in s["last_reason"]

    # Subsequent evaluation fails since all funds are unlocked
    with pytest.raises(Exception, match="Schedule is not in ACTIVE state"):
        contract.evaluate_and_unlock_kpi(sid)


def test_evaluate_kpi_missed_funds_retained(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 15000

    sid = contract.create_vesting_schedule(
        beneficiary=direct_alice,
        kpi_metric_description="GitHub Release version v2.0 published with 50+ stars",
        metrics_url="https://api.github.com/repos/sample/repo/releases",
        duration_sec=86400 * 45
    )

    # Install Mocks: Milestone not yet reached
    sim_installMocks({
        "web_mocks": {
            ".*github.com.*": {
                "status": 200,
                "body": "Repository sample/repo: Latest release is v1.2.0. Total stars: 18. Release v2.0 is currently in alpha milestone."
            }
        },
        "llm_mocks": {
            ".*": {
                "verdict": "KPI_MISSED",
                "confidence": 95,
                "reason": "Observed latest release is v1.2.0 with 18 stars, failing required v2.0 threshold."
            }
        }
    }, vm=direct_vm)

    contract.evaluate_and_unlock_kpi(sid)

    s = json.loads(contract.get_schedule(sid))
    assert s["status"] == "ACTIVE"  # Remains active in escrow
    assert s["last_verdict"] == "KPI_MISSED"
    assert s["released_amount"] == "0"
    assert "failing required v2.0 threshold" in s["last_reason"]


def test_evaluate_kpi_insufficient_data_offline_or_404(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 12000

    sid = contract.create_vesting_schedule(
        beneficiary=direct_alice,
        kpi_metric_description="Dune Analytics query demonstrates 50,000 monthly active wallets",
        metrics_url="https://api.dune.com/api/v1/query/12345/results",
        duration_sec=86400 * 30
    )

    # Web endpoint returns 404
    sim_installMocks({
        "web_mocks": {
            ".*dune.com.*": {
                "status": 404,
                "body": "404 Not Found - Query execution endpoint unavailable"
            }
        }
    }, vm=direct_vm)

    contract.evaluate_and_unlock_kpi(sid)

    s = json.loads(contract.get_schedule(sid))
    assert s["status"] == "ACTIVE"
    assert s["last_verdict"] == "INSUFFICIENT_DATA"
    assert s["released_amount"] == "0"
    assert "Metrics endpoint is offline, blank, or returned 404/Error" in s["last_reason"]


def test_clawback_unvested_funds_success(contract, direct_vm, direct_alice, direct_bob):
    from datetime import datetime, timezone, timedelta
    t_start = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    direct_vm.warp(t_start.isoformat())

    direct_vm.sender = direct_bob
    direct_vm.value = 18000
    duration_days = 30

    sid = contract.create_vesting_schedule(
        beneficiary=direct_alice,
        kpi_metric_description="Mainnet transaction count exceeds 500,000",
        metrics_url="https://api.etherscan.io/api?module=proxy",
        duration_sec=86400 * duration_days
    )

    # Warp past schedule maturity (35 days later)
    direct_vm.warp((t_start + timedelta(days=duration_days + 5)).isoformat())

    # Funder reclaims unvested funds
    contract.clawback_unvested_funds(sid)

    s = json.loads(contract.get_schedule(sid))
    assert s["status"] == "TERMINATED"
    assert s["released_amount"] == "0"
    assert "Unvested funds clawed back by funder" in s["last_reason"]


def test_clawback_unvested_funds_validations(contract, direct_vm, direct_alice, direct_bob, direct_charlie):
    from datetime import datetime, timezone, timedelta
    t_start = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    direct_vm.warp(t_start.isoformat())

    direct_vm.sender = direct_bob
    direct_vm.value = 10000

    sid = contract.create_vesting_schedule(
        beneficiary=direct_alice,
        kpi_metric_description="DeFiLlama TVL surpasses $5,000,000 USD",
        metrics_url="https://defillama.com/protocol/sample",
        duration_sec=86400 * 30
    )

    # 1. Non-funder attempts clawback
    direct_vm.sender = direct_alice
    with pytest.raises(Exception, match="Only funder can claw back unvested funds"):
        contract.clawback_unvested_funds(sid)

    # 2. Premature clawback before expiration
    direct_vm.sender = direct_bob
    with pytest.raises(Exception, match="Vesting schedule duration has not expired yet"):
        contract.clawback_unvested_funds(sid)

    # 3. Schedule already completed cannot be clawed back
    # Warp past expiration
    direct_vm.warp((t_start + timedelta(days=35)).isoformat())

    # Unlock first
    sim_installMocks({
        "web_mocks": {
            ".*defillama.com.*": {
                "status": 200,
                "body": "TVL is $7,000,000 USD"
            }
        },
        "llm_mocks": {
            ".*": {
                "verdict": "KPI_ACHIEVED",
                "confidence": 99,
                "reason": "Target surpassed"
            }
        }
    }, vm=direct_vm)
    contract.evaluate_and_unlock_kpi(sid)

    # Now clawback should fail because status is COMPLETED
    with pytest.raises(Exception, match="Schedule is not in ACTIVE state"):
        contract.clawback_unvested_funds(sid)


def test_non_existent_schedule_operations(contract, direct_vm):
    with pytest.raises(Exception, match="Vesting schedule not found"):
        contract.get_schedule("999")

    with pytest.raises(Exception, match="Vesting schedule not found"):
        contract.evaluate_and_unlock_kpi("999")

    with pytest.raises(Exception, match="Vesting schedule not found"):
        contract.clawback_unvested_funds("999")


def test_view_methods(contract):
    assert contract.get_schedule_count() == 0
    assert isinstance(contract.get_owner(), str)
    assert contract.get_owner().startswith("0x")
    assert isinstance(contract.get_current_time(), int)
