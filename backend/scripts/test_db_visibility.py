#!/usr/bin/env python3
"""
Тест: может ли SQLAlchemy сессия в одном процессе увидеть
изменения сделанные другой сессией (имитация frontend → worker).

Сценарий:
  - Основной поток создаёт flow со state=wait_code
  - Фоновый поток через 3 секунды обновляет state на code_submitted
    через ОТДЕЛЬНУЮ сессию (имитация frontend)
  - Основной поток пробует 4 варианта чтения и логирует, какой
    из них увидел изменение и через сколько секунд.

Запуск:
  cd /home/user/rovena/backend
  python -m scripts.test_db_visibility
"""

import sys
import os
import time
import threading
import uuid
from datetime import datetime, timezone

# Ensure app modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select, text
from app.core.database import SessionLocal, engine
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow


POLL_INTERVAL = 1  # seconds between polls
MAX_POLLS = 15     # stop after this many polls
UPDATE_DELAY = 3   # seconds before background thread updates state


def create_test_flow(db) -> str:
    """Create a minimal test flow with state=wait_code, return its id."""
    flow_id = str(uuid.uuid4())

    # We need a valid account_id — grab the first one that exists
    row = db.execute(text("SELECT id FROM telegram_accounts LIMIT 1")).first()
    if not row:
        print("ERROR: no telegram_accounts found in DB; cannot create test flow")
        sys.exit(1)
    account_id = row[0]

    flow = TelegramAuthFlow(
        id=flow_id,
        account_id=account_id,
        state=AuthFlowState.wait_code,
        phone_e164="+10000000000",
        meta_json={"test": True},
        created_at=datetime.now(timezone.utc),
    )
    db.add(flow)
    db.commit()
    print(f"[setup] Created test flow {flow_id} with state=wait_code (account_id={account_id})")
    return flow_id


def background_updater(flow_id: str, delay: float):
    """Simulate frontend: update state to code_submitted via a separate session."""
    time.sleep(delay)
    with SessionLocal() as db2:
        db2.execute(
            text(
                "UPDATE telegram_auth_flows "
                "SET state = :new_state, meta_json = JSON_SET(COALESCE(meta_json, '{}'), '$.submitted_code', '12345') "
                "WHERE id = :fid"
            ),
            {"new_state": AuthFlowState.code_submitted.value, "fid": flow_id},
        )
        db2.commit()
        # Verify the update was committed
        verify = db2.execute(
            text("SELECT state FROM telegram_auth_flows WHERE id = :fid"),
            {"fid": flow_id},
        ).first()
        print(f"[bg-thread] Updated flow {flow_id} → state={verify[0] if verify else '???'} (committed)")


def poll_variant_a(db, flow_id):
    """Variant A: db.execute(select(...)) — same session, no expire."""
    row = db.execute(
        select(TelegramAuthFlow.state, TelegramAuthFlow.meta_json)
        .where(TelegramAuthFlow.id == flow_id)
    ).first()
    return row.state if row else None


def poll_variant_b(db, flow_id):
    """Variant B: db.expire_all() + db.execute(select(...))."""
    db.expire_all()
    row = db.execute(
        select(TelegramAuthFlow.state, TelegramAuthFlow.meta_json)
        .where(TelegramAuthFlow.id == flow_id)
    ).first()
    return row.state if row else None


def poll_variant_c(db, flow_id):
    """Variant C: raw text SQL — bypass ORM completely."""
    row = db.execute(
        text("SELECT state FROM telegram_auth_flows WHERE id = :fid"),
        {"fid": flow_id},
    ).first()
    return row[0] if row else None


def poll_variant_d(flow_id):
    """Variant D: brand new session for each poll."""
    with SessionLocal() as fresh:
        row = fresh.execute(
            select(TelegramAuthFlow.state, TelegramAuthFlow.meta_json)
            .where(TelegramAuthFlow.id == flow_id)
        ).first()
        return row.state if row else None


def run_test():
    print("=" * 70)
    print("DB Visibility Test — polling loop simulation")
    print(f"  engine: {engine.url}")
    print(f"  isolation level: {engine.dialect.get_default_isolation_level(None) if hasattr(engine.dialect, 'get_default_isolation_level') else 'unknown'}")
    print("=" * 70)

    # Try to read actual transaction isolation from the server
    with SessionLocal() as db_check:
        try:
            iso = db_check.execute(text("SELECT @@transaction_isolation")).scalar()
            print(f"  server transaction_isolation: {iso}")
        except Exception:
            try:
                iso = db_check.execute(text("SELECT @@tx_isolation")).scalar()
                print(f"  server tx_isolation: {iso}")
            except Exception:
                print("  (could not read server isolation level)")
    print()

    db = SessionLocal()
    try:
        flow_id = create_test_flow(db)

        # Load flow into identity map (as the task does with db.get)
        flow_obj = db.get(TelegramAuthFlow, flow_id)
        print(f"[main] Loaded flow into identity map: state={flow_obj.state}")
        print(f"[main] identity_map size: {len(db.identity_map)}")
        print()

        # Start background updater
        t = threading.Thread(target=background_updater, args=(flow_id, UPDATE_DELAY))
        t.start()

        results = {"A": None, "B": None, "C": None, "D": None}
        t_start = time.monotonic()

        for poll in range(1, MAX_POLLS + 1):
            elapsed = time.monotonic() - t_start

            state_a = poll_variant_a(db, flow_id)
            state_b = poll_variant_b(db, flow_id)
            state_c = poll_variant_c(db, flow_id)
            state_d = poll_variant_d(flow_id)

            changed_a = state_a == AuthFlowState.code_submitted or state_a == "code_submitted"
            changed_b = state_b == AuthFlowState.code_submitted or state_b == "code_submitted"
            changed_c = (state_c == "code_submitted") if isinstance(state_c, str) else (state_c == AuthFlowState.code_submitted)
            changed_d = state_d == AuthFlowState.code_submitted or state_d == "code_submitted"

            print(
                f"  poll={poll:2d}  elapsed={elapsed:5.1f}s  "
                f"A={str(state_a):20s} ({'YES' if changed_a else 'no ':>3})  "
                f"B={str(state_b):20s} ({'YES' if changed_b else 'no ':>3})  "
                f"C={str(state_c):20s} ({'YES' if changed_c else 'no ':>3})  "
                f"D={str(state_d):20s} ({'YES' if changed_d else 'no ':>3})"
            )

            if results["A"] is None and changed_a:
                results["A"] = elapsed
            if results["B"] is None and changed_b:
                results["B"] = elapsed
            if results["C"] is None and changed_c:
                results["C"] = elapsed
            if results["D"] is None and changed_d:
                results["D"] = elapsed

            # Stop early if all variants detected the change
            if all(v is not None for v in results.values()):
                print("\n  All variants detected the change — stopping early.")
                break

            time.sleep(POLL_INTERVAL)

        t.join(timeout=10)

        # ── Summary ──
        print()
        print("=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        for variant, elapsed_at in sorted(results.items()):
            if elapsed_at is not None:
                print(f"  Variant {variant}: SAW CHANGE at {elapsed_at:.1f}s")
            else:
                print(f"  Variant {variant}: NEVER SAW CHANGE within {MAX_POLLS}s")
        print()

        # ── Analysis ──
        print("ANALYSIS:")
        if results["A"] is None:
            print("  ** Variant A (plain select on same session) FAILED to see the change.")
            print("     This is the pattern used in the polling loop right now!")
            if results["B"] is not None:
                print("  -> expire_all() before select fixes it (Variant B).")
            if results["D"] is not None:
                print("  -> Fresh session per poll also fixes it (Variant D).")
            if results["C"] is not None and results["A"] is None:
                print("  -> Raw text SQL sees it but ORM select does not — identity map issue.")
        else:
            print("  Variant A works. The issue might be elsewhere (isolation level, async, etc.).")
        print()

    finally:
        # Cleanup
        try:
            db.execute(
                text("DELETE FROM telegram_auth_flows WHERE id = :fid"),
                {"fid": flow_id},
            )
            db.commit()
            print(f"[cleanup] Deleted test flow {flow_id}")
        except Exception as e:
            print(f"[cleanup] Failed to delete test flow: {e}")
        db.close()


if __name__ == "__main__":
    run_test()
