# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
import json


try:
    gl.UserError = gl.vm.UserError
except Exception:
    pass


def _addr_str(addr: Address) -> str:
    """Safely format an Address instance into a lowercase hex string."""
    try:
        return addr.as_hex.lower()
    except Exception:
        return str(addr).lower()


def _get_sender() -> Address:
    """Safely obtain transaction sender across GenVM runtime versions with static schema fallback."""
    try:
        if hasattr(gl, "message"):
            if hasattr(gl.message, "sender"):
                return gl.message.sender
            if hasattr(gl.message, "sender_address"):
                return gl.message.sender_address
    except Exception:
        pass
    try:
        if hasattr(gl, "message_raw") and isinstance(gl.message_raw, dict):
            sender_raw = gl.message_raw.get("from") or gl.message_raw.get("sender")
            if sender_raw:
                return Address(str(sender_raw))
    except Exception:
        pass
    return Address("0x0000000000000000000000000000000000000000")


def _safe_transfer(recipient: Address, amount: bigint) -> None:
    """Safely disburse native GEN to an address using official GenLayer SDK pattern."""
    if amount <= bigint(0):
        return
    gl.get_contract_at(recipient).emit_transfer(value=u256(int(amount)))


DEFAULT_ANALYTICS_DOMAINS = (
    "defillama.com",
    "www.defillama.com",
    "api.llama.fi",
    "dune.com",
    "www.dune.com",
    "api.dune.com",
    "github.com",
    "www.github.com",
    "api.github.com",
    "etherscan.io",
    "www.etherscan.io",
    "api.etherscan.io",
    "mock-analytics.genlayer.com",
)


def _parse_url_host(raw_url: str) -> str:
    """Extract and validate normalized hostname from URL."""
    clean = raw_url.strip()
    if "?" in clean:
        clean = clean.split("?")[0]
    if "#" in clean:
        clean = clean.split("#")[0]
    clean = clean.strip()

    if clean.startswith("https://"):
        rest = clean[8:]
    elif clean.startswith("http://"):
        rest = clean[7:]
    else:
        raise gl.UserError("URL must begin with http:// or https://")

    host = rest.split("/", 1)[0].strip().lower()
    if ":" in host:
        host = host.split(":")[0].strip()
    if not host:
        raise gl.UserError("Invalid URL: missing host")
    return host


@allow_storage
@dataclass
class VestingSchedule:
    schedule_id: str
    funder: Address
    beneficiary: Address
    kpi_metric_description: str    # Detailed KPI condition to unlock funds
    metrics_url: str               # Canonical analytics endpoint
    allocated_amount: bigint       # Total funds allocated to this schedule
    released_amount: bigint        # Total funds successfully unlocked to beneficiary
    status: str                    # "ACTIVE", "COMPLETED", "TERMINATED"
    last_verdict: str              # "PENDING", "KPI_ACHIEVED", "KPI_MISSED", "INSUFFICIENT_DATA"
    last_reason: str               # Consensus reasoning
    expiration_timestamp: bigint  # Final schedule maturity timestamp
    created_at: bigint
    resolved_at: bigint


class Contract(gl.Contract):
    """
    VestingKPIUnlockX: Autonomous Milestone & Metric-Gated Fund Vesting Protocol
    Track: Autonomous Protocols / Future of Work
    """
    owner: Address
    schedule_count: bigint
    schedules: TreeMap[str, VestingSchedule]
    custom_allowed_domains: TreeMap[str, bool]

    def __init__(self):
        # GenVM automatically initializes TreeMap storage fields to empty.
        self.owner = _get_sender()
        self.schedule_count = bigint(0)

    def _get_current_timestamp(self) -> bigint:
        """Derive trusted deterministic execution timestamp from GenLayer transaction context."""
        try:
            from datetime import datetime
            dt_raw = getattr(gl.message, "datetime", None)
            if dt_raw is None and hasattr(gl, "message_raw") and isinstance(gl.message_raw, dict):
                dt_raw = gl.message_raw.get("datetime")
            if dt_raw:
                dt_str = str(dt_raw).strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(dt_str)
                ts = int(dt.timestamp())
                if ts > 0:
                    return bigint(ts)
        except Exception:
            pass

        try:
            if hasattr(gl, "block") and hasattr(gl.block, "timestamp"):
                ts = int(gl.block.timestamp)
                if ts > 0:
                    return bigint(ts)
        except Exception:
            pass

        return bigint(0)

    def _parse_llm_json(self, text: str) -> dict:
        """Safely parse LLM responses, stripping markdown wrappers if present."""
        try:
            cleaned = str(text).strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception as e:
            return {
                "verdict": "INSUFFICIENT_DATA",
                "confidence": 0,
                "reason": f"Failed to parse LLM JSON: {str(e)[:100]}"
            }

    @gl.public.write
    def add_allowed_analytics_domain(self, domain: str) -> None:
        """Owner can add new trusted metrics verification domains."""
        if _addr_str(_get_sender()) != _addr_str(self.owner):
            raise gl.UserError("Only contract owner can add allowed domains.")
        clean = domain.strip().lower()
        if len(clean) < 3:
            raise gl.UserError("Invalid domain name.")
        self.custom_allowed_domains[clean] = True

    @gl.public.write
    def remove_allowed_analytics_domain(self, domain: str) -> None:
        """Owner can revoke custom or default allowed metrics verification domains."""
        if _addr_str(_get_sender()) != _addr_str(self.owner):
            raise gl.UserError("Only contract owner can remove allowed domains.")
        clean = domain.strip().lower()
        self.custom_allowed_domains[clean] = False

    @gl.public.view
    def is_analytics_domain_allowed(self, domain: str) -> bool:
        """Check if metrics domain is whitelisted."""
        clean = domain.strip().lower()
        if clean in DEFAULT_ANALYTICS_DOMAINS:
            try:
                if clean in self.custom_allowed_domains and not self.custom_allowed_domains[clean]:
                    return False
            except Exception:
                pass
            return True
        try:
            return bool(self.custom_allowed_domains[clean])
        except Exception:
            return False

    @gl.public.write.payable
    def create_vesting_schedule(
        self,
        beneficiary: Address,
        kpi_metric_description: str,
        metrics_url: str,
        duration_sec: int
    ) -> str:
        """
        Funder creates a KPI-gated vesting schedule and locks GEN in escrow.
        """
        deposit = bigint(gl.message.value)
        if deposit <= bigint(0):
            raise gl.UserError("Vesting allocation must be greater than 0 GEN.")

        clean_desc = kpi_metric_description.strip()
        clean_url = metrics_url.strip()

        if len(clean_desc) < 10:
            raise gl.UserError("kpi_metric_description must be detailed (min 10 characters).")

        if _addr_str(_get_sender()) == _addr_str(beneficiary):
            raise gl.UserError("Funder cannot set self as beneficiary.")

        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise gl.UserError("metrics_url must start with http:// or https://")

        # Canonical Domain Whitelist Check
        host = _parse_url_host(clean_url)
        if not self.is_analytics_domain_allowed(host):
            raise gl.UserError(f"Metrics host '{host}' is not in the allowed domain whitelist.")

        now_ts = self._get_current_timestamp()
        dur = bigint(duration_sec if duration_sec >= 86400 else 86400)
        exp_ts = now_ts + dur if now_ts > bigint(0) else bigint(86400 * 30)

        self.schedule_count += bigint(1)
        sid = str(self.schedule_count)

        self.schedules[sid] = VestingSchedule(
            schedule_id=sid,
            funder=_get_sender(),
            beneficiary=beneficiary,
            kpi_metric_description=clean_desc,
            metrics_url=clean_url,
            allocated_amount=deposit,
            released_amount=bigint(0),
            status="ACTIVE",
            last_verdict="PENDING",
            last_reason="Vesting funded. Awaiting autonomous metric evaluation.",
            expiration_timestamp=exp_ts,
            created_at=self.schedule_count,
            resolved_at=bigint(0)
        )

        return sid

    @gl.public.write
    def evaluate_and_unlock_kpi(self, schedule_id: str) -> None:
        """
        Validators scrape official metrics URL, audit observed data against KPI targets,
        and deterministically disburse funds upon consensus.
        """
        if schedule_id not in self.schedules:
            raise gl.UserError("Vesting schedule not found.")

        schedule = self.schedules[schedule_id]
        if schedule.status != "ACTIVE":
            raise gl.UserError("Schedule is not in ACTIVE state.")

        unlocked_remaining = schedule.allocated_amount - schedule.released_amount
        if unlocked_remaining <= bigint(0):
            raise gl.UserError("All allocated funds have already been vested and released.")

        kpi_desc_local = str(schedule.kpi_metric_description)
        url_local = str(schedule.metrics_url)

        def leader_fn():
            web_content = ""
            try:
                res = gl.nondet.web.render(url_local, mode="text")
                if hasattr(res, "content"):
                    web_content = res.content
                elif isinstance(res, dict) and "body" in res:
                    web_content = res["body"]
                else:
                    web_content = str(res)
            except Exception:
                web_content = ""

            lower_web = web_content[:500].lower() if web_content else ""
            if len(web_content.strip()) < 15 or "404 not found" in lower_web or "error" in lower_web:
                return {
                    "verdict": "INSUFFICIENT_DATA",
                    "confidence": 100,
                    "reason": "Metrics endpoint is offline, blank, or returned 404/Error."
                }

            snippet = web_content[:4000]

            prompt = f"""You are the Autonomous Protocol KPI & Token Vesting Arbiter on GenLayer.
Evaluate whether the live observed metric data confirms that the target KPI has been SUCCESSFULLY MET.

AGREED KPI MILESTONE CRITERIA:
\"\"\"
{kpi_desc_local}
\"\"\"

OBSERVED LIVE METRIC DATA (from {url_local}):
\"\"\"
{snippet}
\"\"\"

DISCRETE CLASSIFICATION RULES:
- "KPI_ACHIEVED": The observed metrics explicitly verify that the required numerical/milestone threshold has been achieved or surpassed.
- "KPI_MISSED": The observed metric data is valid but clearly falls short of the target KPI threshold.
- "INSUFFICIENT_DATA": The page is broken, unrelated, ambiguous, or lacks verifiable timestamped data.

OUTPUT FORMAT:
Respond ONLY with a VALID JSON object (no markdown, no backticks):
{{
  "verdict": "KPI_ACHIEVED" | "KPI_MISSED" | "INSUFFICIENT_DATA",
  "confidence": <integer from 0 to 100>,
  "reason": "<concise explanation max 220 characters>"
}}"""

            try:
                raw_res = gl.nondet.exec_prompt(prompt, response_format="json")
                parsed = None
                if isinstance(raw_res, dict):
                    parsed = raw_res
                elif hasattr(raw_res, "content") and isinstance(raw_res.content, dict):
                    parsed = raw_res.content
                else:
                    text = raw_res.content if hasattr(raw_res, "content") else str(raw_res)
                    cleaned = str(text).strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned[7:]
                    elif cleaned.startswith("```"):
                        cleaned = cleaned[3:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    parsed = json.loads(cleaned.strip())

                verdict_candidate = str(parsed.get("verdict", "INSUFFICIENT_DATA")).strip().upper()
                valid_verdicts = ("KPI_ACHIEVED", "KPI_MISSED", "INSUFFICIENT_DATA")
                if verdict_candidate not in valid_verdicts:
                    verdict_candidate = "INSUFFICIENT_DATA"

                try:
                    conf = int(parsed.get("confidence", 0))
                    conf = max(0, min(100, conf))
                except Exception:
                    conf = 50

                reason_str = str(parsed.get("reason", "Audited by autonomous vesting jury."))[:220]

                return {
                    "verdict": verdict_candidate,
                    "confidence": conf,
                    "reason": reason_str
                }
            except Exception as e:
                return {
                    "verdict": "INSUFFICIENT_DATA",
                    "confidence": 0,
                    "reason": f"Evaluation error: {str(e)[:100]}"
                }

        def validator_fn(leader_res) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False
            leader = leader_res.calldata
            if not isinstance(leader, dict) or "verdict" not in leader:
                return False

            valid_verdicts = ("KPI_ACHIEVED", "KPI_MISSED", "INSUFFICIENT_DATA")
            l_verdict = str(leader.get("verdict", "")).strip().upper()
            if l_verdict not in valid_verdicts:
                return False

            mine = leader_fn()
            m_verdict = str(mine.get("verdict", "")).strip().upper()

            # DISCRETE EQUIVALENCE: 100% agreement on exact KPI outcome
            return l_verdict == m_verdict

        adjudication_res = gl.vm.run_nondet(leader_fn, validator_fn)
        if isinstance(adjudication_res, dict):
            final_res = adjudication_res
        else:
            final_res = self._parse_llm_json(str(adjudication_res))

        verdict = str(final_res.get("verdict", "INSUFFICIENT_DATA")).strip().upper()
        valid_verdicts = ("KPI_ACHIEVED", "KPI_MISSED", "INSUFFICIENT_DATA")
        if verdict not in valid_verdicts:
            verdict = "INSUFFICIENT_DATA"

        reason = str(final_res.get("reason", "Consensus concluded."))

        schedule.last_verdict = verdict
        schedule.last_reason = reason
        schedule.resolved_at = self.schedule_count

        if verdict == "KPI_ACHIEVED":
            # Unlock and disburse 100% of remaining funds to beneficiary
            release_amt = schedule.allocated_amount - schedule.released_amount
            schedule.released_amount += release_amt
            schedule.status = "COMPLETED"
            self.schedules[schedule_id] = schedule

            _safe_transfer(schedule.beneficiary, release_amt)

        else:
            # KPI_MISSED or INSUFFICIENT_DATA: keep remaining funds locked in escrow
            self.schedules[schedule_id] = schedule

    @gl.public.write
    def clawback_unvested_funds(self, schedule_id: str) -> None:
        """
        Safe Funder Recovery Path:
        If schedule has passed expiration timestamp and KPI was not met, funder can reclaim remaining unvested funds.
        """
        if schedule_id not in self.schedules:
            raise gl.UserError("Vesting schedule not found.")

        schedule = self.schedules[schedule_id]
        if _addr_str(_get_sender()) != _addr_str(schedule.funder):
            raise gl.UserError("Only funder can claw back unvested funds.")

        if schedule.status != "ACTIVE":
            raise gl.UserError("Schedule is not in ACTIVE state.")

        now_ts = self._get_current_timestamp()
        if now_ts > bigint(0) and now_ts <= schedule.expiration_timestamp:
            raise gl.UserError("Vesting schedule duration has not expired yet.")

        unvested_amount = schedule.allocated_amount - schedule.released_amount
        if unvested_amount <= bigint(0):
            raise gl.UserError("No unvested funds remaining to reclaim.")

        schedule.status = "TERMINATED"
        schedule.last_reason = "Schedule expired without KPI achievement. Unvested funds clawed back by funder."
        schedule.resolved_at = self.schedule_count
        self.schedules[schedule_id] = schedule

        _safe_transfer(schedule.funder, unvested_amount)

    @gl.public.view
    def get_schedule(self, schedule_id: str) -> str:
        """Retrieve details of a vesting schedule as a JSON string."""
        if schedule_id not in self.schedules:
            raise gl.UserError("Vesting schedule not found.")
        s = self.schedules[schedule_id]
        return json.dumps({
            "schedule_id": s.schedule_id,
            "funder": _addr_str(s.funder),
            "beneficiary": _addr_str(s.beneficiary),
            "kpi_metric_description": s.kpi_metric_description,
            "metrics_url": s.metrics_url,
            "allocated_amount": str(s.allocated_amount),
            "released_amount": str(s.released_amount),
            "status": s.status,
            "last_verdict": s.last_verdict,
            "last_reason": s.last_reason,
            "expiration_timestamp": str(s.expiration_timestamp),
            "created_at": str(s.created_at),
            "resolved_at": str(s.resolved_at)
        })

    @gl.public.view
    def get_current_time(self) -> int:
        """Retrieve current contract execution timestamp."""
        return int(str(self._get_current_timestamp()))

    @gl.public.view
    def get_schedule_count(self) -> int:
        return int(self.schedule_count)

    @gl.public.view
    def get_owner(self) -> str:
        return _addr_str(self.owner)
