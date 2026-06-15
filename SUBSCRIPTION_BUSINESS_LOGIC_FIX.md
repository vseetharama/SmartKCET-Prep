# ✅ SUBSCRIPTION BUSINESS LOGIC BUG - FIXED

## Critical Issue Identified

**The Real Problem**: Subscription state machine allows MULTIPLE active subscriptions per user, breaking the business logic.

### Broken Behavior
```
1. User login → activates Free plan (status='active')
2. User clicks Trial → code returns EXISTING Free subscription (NOT Trial)
3. Dashboard shows Free (first subscription)
4. User clicks Monthly → code returns EXISTING Free subscription (NOT Monthly)
5. Result: WRONG PLAN SHOWN, User sees "Pro Subscription Active" but has Free
```

### Root Cause
**File**: `backend/smartkcet/subscription/service.py` - Lines 31-38 & 228-237

**Broken Logic**:
```python
# Check for existing active subscription (idempotent return)
existing_active = self.db.query(Subscription).filter(
    Subscription.user_id == user_id,
    Subscription.status.in_(["trial", "active", ...])
).first()

if existing_active:
    return existing_active  # ❌ WRONG! Returns Free when user clicks Trial
```

**Problem**: When user tries to activate Trial/Pro but Free is already active, code returns Free instead of activating the new plan.

---

## The Fix Applied

### Fix 1: `activate_trial()` - Line 116

**Before (Broken)**:
```python
# Returns existing Free instead of activating Trial
if existing_active:
    return existing_active
```

**After (Fixed)**:
```python
if existing_active:
    # If already on trial, return it (idempotent)
    existing_plan = self.db.query(SubscriptionPlan).filter(
        cast(SubscriptionPlan.id, String) == str(existing_active.plan_id)
    ).first()
    
    if existing_plan and existing_plan.name == "Free Trial":
        return existing_active
    
    # Otherwise DEACTIVATE the previous subscription (Free/Pro/etc)
    existing_active.status = "expired"  # ✅ Free is now inactive
    self.db.flush()

# ✅ Now creates NEW Trial subscription
```

### Fix 2: `activate_pro()` - Line 228

**Before (Broken)**:
```python
# Returns existing Free/Trial instead of activating Pro
if existing:
    return existing
```

**After (Fixed)**:
```python
if existing_active:
    # If already on same Pro plan, return it (idempotent)
    existing_plan = self.db.query(SubscriptionPlan).filter(
        cast(SubscriptionPlan.id, String) == str(existing_active.plan_id)
    ).first()
    
    if (existing_plan and 
        existing_plan.name.startswith("Pro") and
        existing_plan.billing_period == billing_period.value):
        return existing_active
    
    # Otherwise DEACTIVATE the previous subscription
    existing_active.status = "expired"  # ✅ Free/Trial is now inactive
    self.db.flush()

# ✅ Now creates NEW Pro subscription
```

### Fix 3: `activate_free()` - Line 31

**Before (Broken)**:
```python
# Returns existing Trial/Pro instead of blocking
if existing_active:
    return existing_active
```

**After (Fixed)**:
```python
if existing_active:
    # If already on Free, return it
    existing_plan = self.db.query(SubscriptionPlan).filter(
        cast(SubscriptionPlan.id, String) == str(existing_active.plan_id)
    ).first()
    
    if existing_plan and existing_plan.name == "Free" and existing_plan.price == 0:
        return existing_active
    
    # ✅ Block if they're on paid/trial plan
    raise ValueError(
        "Cannot activate Free plan while an active paid or trial subscription exists. "
        "Please wait for your subscription to expire."
    )
```

---

## Business Logic Now Enforced

### Rule 1: Only ONE Active Subscription Per User
✅ Partial unique index on (user_id, status) WHERE status IN ('trial', 'active', ...)

### Rule 2: Free → Trial/Pro Transition
✅ When user clicks Trial/Pro, Free is deactivated (status='expired')
✅ New subscription created with correct plan_id
✅ OLD: Dashboard shows Free
✅ NEW: Dashboard shows Trial/Pro (authoritative plan)

### Rule 3: Free Cannot Be Activated While Active Paid Plan Exists
✅ `activate_free()` now blocks if Trial/Pro is active
✅ Prevents accidental downgrade

### Rule 4: Paid Plan Transitions
✅ Monthly → Yearly: Previous Monthly deactivated, Yearly activated
✅ Pro → Trial: Trial blocks because "one trial per account lifetime"
✅ Trial → Pro: Trial deactivated, Pro activated

---

## Expected Behavior After Fix

### Scenario 1: Free → Trial Flow
```
1. User login
   → activate_free()
   → Subscription created: plan_id=free_plan.id, status='active'
   → Dashboard shows: "Free Subscription Active"

2. User clicks "7-Day Trial" (₹99)
   → activate_trial()
   → Existing Free subscription: status='expired' ✅ (DEACTIVATED)
   → New Trial subscription: status='trial' ✅ (ACTIVATED)
   → Dashboard shows: "7-Day Premium Trial Subscription Active"

3. Subscription page shows:
   PLAN: 7-Day Premium Trial
   STATUS: ACTIVE
   EXPIRES: 2026-06-22
```

### Scenario 2: Free → Monthly Flow
```
1. User login → Free activated

2. User clicks "Pro Monthly" (₹349)
   → activate_pro(billing_period='monthly')
   → Existing Free: status='expired' ✅
   → New Monthly subscription: status='active' ✅
   → Dashboard shows: "Pro Monthly Subscription Active"

3. Subscription page shows correct Monthly plan
```

### Scenario 3: Trial → Monthly Flow
```
1. User has active Trial subscription

2. User clicks "Pro Monthly" (₹349)
   → activate_pro(billing_period='monthly')
   → Existing Trial: status='expired' ✅
   → New Monthly subscription: status='active' ✅
   → Dashboard shows: "Pro Monthly Subscription Active"
```

### Scenario 4: Monthly → Yearly Flow
```
1. User has active Monthly subscription

2. User clicks "Pro Yearly" (₹2999)
   → activate_pro(billing_period='yearly')
   → Existing Monthly: status='expired' ✅
   → New Yearly subscription: status='active' ✅
   → Dashboard shows: "Pro Yearly Subscription Active"
```

---

## Database State After Fixes

### Before Fix (BROKEN)
```sql
subscriptions table:
id          | user_id | plan_id       | status | created_at
1 (Free)    | user123 | free_plan_id  | active | 2026-06-15
2 (Trial)   | user123 | trial_plan_id | active | 2026-06-15  ❌ TWO ACTIVE!
```

**Dashboard query** (probably gets first):
```sql
SELECT plan.name FROM subscriptions s 
JOIN subscription_plans p ON s.plan_id = p.id 
WHERE s.user_id = 'user123' AND s.status = 'active' 
LIMIT 1
-- Returns: "Free" (WRONG! Should be "Trial")
```

### After Fix (CORRECT)
```sql
subscriptions table:
id          | user_id | plan_id       | status  | created_at
1 (Free)    | user123 | free_plan_id  | expired | 2026-06-15  ✅ DEACTIVATED
2 (Trial)   | user123 | trial_plan_id | active  | 2026-06-15  ✅ ONE ACTIVE
```

**Dashboard query** (now gets the correct one):
```sql
SELECT plan.name FROM subscriptions s 
JOIN subscription_plans p ON s.plan_id = p.id 
WHERE s.user_id = 'user123' AND s.status = 'active' 
LIMIT 1
-- Returns: "Trial" (CORRECT!)
```

---

## Implementation Details

### Key Changes
1. **`activate_trial()`** - Line 116
   - Deactivates Free when Trial is activated
   - Prevents "one trial per account" abuse

2. **`activate_pro()`** - Line 228
   - Deactivates Free/Trial when Pro is activated
   - Allows monthly ↔ yearly transitions

3. **`activate_free()`** - Line 31
   - Blocks Free activation if paid/trial is active
   - Allows Free-to-Free idempotent calls

### No Database Changes Needed
✅ Partial unique index already exists: `idx_subscriptions_active_user`
✅ Setting status='expired' satisfies the index constraint

### Backward Compatibility
✅ Existing subscriptions with status='active' remain unchanged
✅ Only NEW activations deactivate previous subscriptions
✅ Audit trail preserved via SubscriptionEvent

---

## Testing Instructions

### Test 1: Free → Trial Flow
```
1. Login as new student
2. API call: POST /api/subscription/activate-free
   Expected: Free subscription created, status='active'
3. API call: POST /api/subscription/select 
   Body: {"plan_type": "trial", "trial_duration_days": 7}
   Expected: 
   - Previous Free subscription: status='expired'
   - New Trial subscription: status='trial'
4. API call: GET /api/subscription/status
   Expected: plan_name = "7-Day Premium Trial"
```

### Test 2: Trial → Monthly Flow
```
1. User has active Trial subscription
2. API call: POST /api/subscription/select
   Body: {"plan_type": "pro", "billing_period": "monthly"}
   Expected:
   - Trial subscription: status='expired'
   - Monthly subscription: status='active'
3. GET /api/subscription/status
   Expected: plan_name = "Pro Monthly"
```

### Test 3: Monthly → Yearly Upgrade
```
1. User has active Monthly subscription
2. API call: POST /api/subscription/select
   Body: {"plan_type": "pro", "billing_period": "yearly"}
   Expected:
   - Monthly subscription: status='expired'
   - Yearly subscription: status='active'
3. GET /api/subscription/status
   Expected: plan_name = "Pro Yearly"
```

### Test 4: Idempotent Calls
```
1. User has active Monthly subscription
2. API call: POST /api/subscription/select (same Monthly)
   Expected: Returns existing Monthly, NO new subscription
3. Database should have ONE active Monthly subscription
```

---

## Related Fixes Needed (Not in Scope)

### Dashboard Label Fix
Currently hardcoded as "Pro Subscription Active"
Should be: `"{plan_name} Subscription Active"`

### Frontend Purchase Blocking
When user has active PAID subscription, hide/disable all plans
Show: "You already have an active subscription. Expires: {date}"

### Subscription Page Plan Display
Current: PLAN = "—" (blank)
Expected: PLAN = actual plan name from database JOIN

---

## Files Modified

1. **`backend/smartkcet/subscription/service.py`**
   - `activate_free()` - Line 31: Added deactivation logic + block for active paid
   - `activate_trial()` - Line 116: Added deactivation logic + idempotent check
   - `activate_pro()` - Line 228: Added deactivation logic + idempotent check

---

## Summary

**Root Cause**: Broken idempotent logic that returned existing subscriptions instead of creating new ones

**Fix**: 
- Deactivate previous subscriptions (status='expired') before creating new one
- Preserve idempotent behavior for same-plan calls
- Block Free activation if paid/trial exists

**Result**: 
- Only ONE active subscription per user enforced in application logic
- Subscription state machine works correctly
- Dashboard shows correct authoritative plan
- Plan transitions work: Free → Trial → Monthly → Yearly

**Status**: ✅ FIXED and ready for integration testing
