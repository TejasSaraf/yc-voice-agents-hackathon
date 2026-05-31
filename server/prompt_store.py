"""Improvable system-prompt store for the carrier check-in agent.

The carrier system prompt is the one thing the self-improvement loop is allowed
to change. We keep it as a ``str.format`` TEMPLATE with named placeholders for
the load-specific facts (shipper, driver, dock, …) and treat everything else —
the procedure and the speaking style — as improvable text.

  * ``CARRIER_TEMPLATE_DEFAULT`` — the shipped, known-good template.
  * an optional override at ``.prompt_overrides/carrier_system.txt`` — written
    ONLY by ``auto_improve.py`` after a candidate beats the current prompt on the
    regression eval. ``load_template()`` falls back to the default if the
    override is missing or fails validation, so a bad file can never reach a
    live call.

A valid template must (a) ``.format`` cleanly with the standard fields,
(b) reference no unknown placeholders, and (c) still name every tool in the
call procedure — so an improved prompt can't silently drop a step.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

_OVERRIDE_DIR = Path(__file__).parent / ".prompt_overrides"
_OVERRIDE = _OVERRIDE_DIR / "carrier_system.txt"

# Fields the template is rendered with (see freight_scenarios._carrier_fields).
PLACEHOLDERS = {
    "shipper",
    "driver_name",
    "carrier",
    "load_id",
    "commodity",
    "origin",
    "dock",
    "appointment",
    "production_line",
    "cargo_line",
}

# Tools the procedure must keep mentioning — a candidate that drops one of these
# is rejected, since the agent would stop performing that step.
REQUIRED_TOOLS = {
    "confirm_eta",
    "verify_cargo_condition",
    "assign_dock",
    "assess_risk",
    "alert_logistics_team",
    "end_call",
}

CARRIER_TEMPLATE_DEFAULT = """You are FreightVoice, an inbound-logistics coordinator calling on behalf of {shipper}. You are making an OUTBOUND call to {driver_name}, the driver for {carrier}, about load {load_id}: {commodity} from {origin}, scheduled to deliver to {dock} at {appointment}. This part feeds {production_line} — if it's late, the line is at risk.

YOUR JOB on this call, in order:
1. Confirm the driver's current location and ETA. Call confirm_eta with:
   - driver_sentiment: your honest read of the driver's tone — exactly one of
     "confident" (clear, specific, no hedging),
     "calm" (relaxed, on track),
     "uncertain" (hedging, vague, mentions problems),
     "frustrated" (stressed, complaining, evasive).
     This is the highest-weighted signal in the risk model. Be precise.
   - eta_minutes_from_now: convert what the driver said to a minute count
     ("about 20 out" → 20, "seven thirty" and it's 6:45 now → 45).
     Use None only if they gave genuinely no usable number.
2. Verify the load is {cargo_line}. Call verify_cargo_condition.
3. Proactively prep receiving: call assign_dock, then tell the driver the dock and which gate to check in at.
4. Call assess_risk — it runs the predictive model and scores the risk to the production line. If it returns must_alert=true (WARNING or CRITICAL), call alert_logistics_team with the recommended action. Do NOT alarm the driver — the alert goes to the shipper's team, not to them.
5. Give a short, warm sign-off confirming the team has been notified, then call end_call in the same turn.

HOW TO TALK — you're a real dispatcher on the phone, not a chatbot:
- Keep it to 1–2 short sentences per turn. Ask ONE thing at a time.
- Lead the call; the driver is busy. Skip filler like "Absolutely!" or "I'd be happy to." Go straight to the point.
- Use contractions. Fragments are fine. Read times in words ("seven thirty", not "7:30").
- Responses are spoken aloud. No bullet points, no emojis, no reading out tool names, JSON, or risk scores. Never read internal scores or alert text to the driver.

Open the call by identifying yourself and the shipper, stating the scheduled delivery, and asking the driver to confirm their ETA and current location — like: "Hi, this is FreightVoice calling on behalf of {shipper}. You're scheduled to deliver {commodity} to {dock} at {appointment}. Can you confirm your ETA and current location?\""""

# A complete dummy field set used to dry-run .format during validation.
_DUMMY_FIELDS = {k: f"<{k}>" for k in PLACEHOLDERS}


def validate(template: str) -> tuple[bool, str]:
    """Return (ok, reason). A template is valid if it renders cleanly with the
    standard fields, uses no unknown placeholders, and keeps every tool name."""
    if not template or not template.strip():
        return False, "empty template"
    try:
        rendered = template.format(**_DUMMY_FIELDS)
    except KeyError as exc:
        return False, f"unknown placeholder {exc}"
    except (IndexError, ValueError) as exc:
        return False, f"bad format syntax: {exc}"
    missing = [t for t in REQUIRED_TOOLS if t not in rendered]
    if missing:
        return False, f"dropped required tool(s): {', '.join(sorted(missing))}"
    return True, "ok"


def load_template() -> str:
    """Return the active template — the override if present and valid, else the
    shipped default. Never raises; a bad override is logged and ignored."""
    if _OVERRIDE.exists():
        try:
            text = _OVERRIDE.read_text()
        except Exception as exc:
            logger.warning(f"prompt_store: cannot read override ({exc}); using default")
            return CARRIER_TEMPLATE_DEFAULT
        ok, reason = validate(text)
        if ok:
            return text
        logger.warning(f"prompt_store: override invalid ({reason}); using default")
    return CARRIER_TEMPLATE_DEFAULT


def is_override_active() -> bool:
    return _OVERRIDE.exists() and validate(_OVERRIDE.read_text()).__getitem__(0)


def render(template: str, fields: dict) -> str:
    """Render a template with load fields. Falls back to the default template if
    the given one fails (defensive — load_template already validates)."""
    try:
        return template.format(**fields)
    except Exception as exc:
        logger.warning(f"prompt_store: render failed ({exc}); using default template")
        return CARRIER_TEMPLATE_DEFAULT.format(**fields)


def render_carrier(fields: dict) -> str:
    """Render the ACTIVE carrier template with the given load fields."""
    return render(load_template(), fields)


def save_template(template: str) -> tuple[bool, str]:
    """Validate and persist a new override (backing up any previous one).
    Returns (ok, reason). Refuses to write an invalid template."""
    ok, reason = validate(template)
    if not ok:
        return False, reason
    _OVERRIDE_DIR.mkdir(exist_ok=True)
    if _OVERRIDE.exists():
        (_OVERRIDE_DIR / "carrier_system.bak.txt").write_text(_OVERRIDE.read_text())
    _OVERRIDE.write_text(template)
    return True, "saved"


def revert() -> bool:
    """Delete the override so the default template is used again."""
    if _OVERRIDE.exists():
        _OVERRIDE.unlink()
        return True
    return False
