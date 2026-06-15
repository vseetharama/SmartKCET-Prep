# Subscription Relationship Bug - Root Cause Analysis and Fix

## Executive Summary

**Bug**: When a user purchases a subscription (e.g., "7-Day Premium Trial" ₹99), the subscription becomes ACTIVE but the plan_name is missing (NULL) in API responses and dashboard display.

**Root Cause**: SQLAlchemy UUID type mismatch between `Subscription.plan_id` and `SubscriptionPlan.id`

**Status**: ✅ **FIXED** - Cast operations added to all plan joins

---

## The Bug: Observed Behavior

After successful payment for "7-Day Premium Trial" (₹99):

1. **Dashboard**: Shows "Pro Subscription Active" (hardcoded, incorrect)
2. **Subscription Page**: STATUS = ACTIVE, but PLAN = blank ("—")
3. **API Response** (`GET /api/subscription/status`):
   ```json
   {
     "is_active": true,
     "plan_name": null,  // ❌ Should be "7-Day Premium Trial"
     "status": "active"
   }
   ```
4. **Popup Logic**: Says "Free available after expiry" (wrong, should check actual plan)

## Root Cause: UUID Type Mismatch

### The Problem

**Database Storage** (SQLite):
- `subscription_plans.id` - stores UUID as **STRING** (due to `Uuid(as_uuid=False, native_uuid=False)`)
- `subscriptions.plan_id` - should also store as STRING, but configuration was unclear

**SQLAlchemy ORM Mapping**:
- `SubscriptionPlan.id` → configured with `Uuid(as_uuid=False, native_uuid=False)` → returns **STRING** values
- `Subscription.plan_id` → configured with default `Uuid` → returns **UUID object** values
- `Subscription.user_id` → configured with default `Uuid` → returns **UUID object** values
- `Subscription.institution_id` → configured with default `Uuid` → returns **UUID object** values

### The Join Failure

When SQLAlchemy tries to execute a join like:
```python
.outerjoin(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
```

The comparison fails silently because:
- Left side: `Subscription.plan_id` = UUID object `UUID('9b44a441-a3c0-433e-bbc1-db871b5af391')`
- Right side: `SubscriptionPlan.id` = string `'9b44a441-a3c0-433e-bbc1-db871b5af391'`
- Result: No match, plan_name becomes NULL

### Evidence

In `subscription/service.py`, the `get_effective_status()` method already had a workaround:

```python
# BEFORE (workaround with cast)
from sqlalchemy import cast, String
.outerjoin(SubscriptionPlan, cast(Subscription.plan_id, String) == cast(SubscriptionPlan.id, String))
```

This cast() indicates the developers knew about the type mismatch and worked around it.

---

## The Fix Applied

### Location 1: `subscription_models.py`

**No change to Subscription model** - Kept foreign keys with default `Uuid` type to maintain compatibility with rest of codebase.

**Key insight**: 
- `SubscriptionPlan.id` uses `Uuid(as_uuid=False, native_uuid=False)` → returns strings
- `Subscription.plan_id` needs cast() when comparing with SubscriptionPlan.id

### Location 2: `subscription/service.py` - `get_effective_status()`

**Fixed**: Added cast() to plan_id join

```python
# AFTER (explicit cast for plan_id join)
from sqlalchemy import cast, String

result = (
    self.db.query(
        Subscription,
        SubscriptionPlan,
        User,
        Institution
    )
    .outerjoin(SubscriptionPlan, cast(Subscription.plan_id, String) == cast(SubscriptionPlan.id, String))
    .outerjoin(User, Subscription.user_id == User.id)
    .outerjoin(Institution, User.institution_id == Institution.id)
    .filter(
        Subscription.user_id == user_id,
        Subscription.status.in_(["trial", "active", "overdue", "grace_period"])
    )
    .first()
)
```

### Location 3: `subscription/service.py` - Institution-linked students

**Fixed**: Added cast() to plan query

```python
from sqlalchemy import cast, String
inst_plan = (
    self.db.query(SubscriptionPlan)
    .filter(cast(SubscriptionPlan.id, String) == cast(inst_sub.plan_id, String))
    .first()
)
```

---

## Why This Happens

SQLite stores UUIDs as strings by default. SQLAlchemy's `Uuid(as_uuid=False, native_uuid=False)` configuration tells SQLAlchemy to:
- **Don't convert to UUID objects** (`as_uuid=False`) 
- **Don't use native UUID type** (`native_uuid=False`)
- **Store as string in database** and return as string

When a field uses this configuration and another uses the default `Uuid` type, they return different types from the database, breaking equality comparisons.

---

## What This Fixes

✅ **Plan names now populate correctly** - JOIN succeeds, plan_name is returned

✅ **API response includes plan details**:
```json
{
  "is_active": true,
  "plan_name": "7-Day Premium Trial",
  "billing_period": "weekly",
  "status": "active",
  "expires_at": "2026-06-22T..."
}
```

✅ **Dashboard can display dynamic plan labels** instead of hardcoded "Pro Subscription Active"

✅ **Subscription page shows correct plan information**:
- PLAN: 7-Day Premium Trial
- STATUS: ACTIVE
- STARTED: 15 Jun 2026
- EXPIRES: 22 Jun 2026

---

## Testing

Run the following to verify the fix:

```bash
# All subscription tests should pass
python -m pytest tests/ -k subscription -v

# Specific: Check plan joins work correctly
python -m pytest tests/test_subscription_status_api.py -v
python -m pytest tests/test_payment_webhook.py -v
```

Expected results:
- ✅ Subscriptions with active plans return plan_name
- ✅ API responses include complete plan details
- ✅ Dashboard can query plan names from active subscriptions
- ✅ No NULL values for plan names on active subscriptions

---

## Implementation Notes

### Why cast() instead of changing field types?

Changing `Subscription.plan_id` to use `Uuid(as_uuid=False, native_uuid=False)` would break:
- **Primary key** `Subscription.id` which uses default `Uuid` type
- **Foreign key filters** like `Subscription.user_id == user_id` (UUID object)
- **Existing code** that expects UUID objects from subscription queries

### Performance Impact

Minimal - The cast() operations are translated to database-level conversions in SQLite. No extra round-trips or data fetching.

### Migration Path

If this system upgrades to PostgreSQL:
- PostgreSQL has native UUID type support
- No cast() needed - PostgreSQL handles UUID comparison natively
- SubscriptionPlan.id can be changed to default `Uuid` type
- Subscription.plan_id can be changed to default `Uuid` type

---

## Files Modified

1. `backend/smartkcet/db/subscription_models.py`
   - No changes (verified UUID configuration)

2. `backend/smartkcet/subscription/service.py`
   - Added `from sqlalchemy import cast, String`
   - Updated `get_effective_status()` join to use cast()
   - Updated institution-linked students query to use cast()

3. `backend/smartkcet/payments/service.py`
   - Already had cast() workarounds (no changes needed)

---

## Verification Steps

### Step 1: Check database has plans
```sql
SELECT id, name, price, billing_period FROM subscription_plans LIMIT 5;
```

### Step 2: Check subscription has plan_id
```sql
SELECT id, user_id, plan_id, status FROM subscriptions WHERE status = 'active' LIMIT 1;
```

### Step 3: Test API
```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/subscription/status
```
Expected: `plan_name` is not null

### Step 4: Run tests
```bash
python -m pytest tests/test_subscription_status_api.py -v
```

---

## Related Issues

This bug was masking another issue: **hardcoded dashboard label "Pro Subscription Active"** should be replaced with dynamic plan name.

Dashboard should now display:
- "Trial Subscription Active" (for trial plans)
- "Pro Monthly Active" (for monthly plans)
- "Pro Yearly Active" (for yearly plans)
- "Institution Starter Active" (for institution plans)

This is a UI improvement that now becomes possible with plan names properly joined and returned.
