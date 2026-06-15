# Payment → Subscription Activation Bug: Testing Instructions

## CRITICAL: Do NOT claim the bug is fixed without following these steps and capturing evidence

The user remains on the FREE plan after successful payment. The bug is STILL PRESENT.

## Setup for Testing

### 1. Start the backend with console output visible
```bash
cd backend
python -m uvicorn smartkcet.main:app --reload
```

Watch the console - you will see detailed logs starting with `[PAYMENT]` and `[VERIFY]`.

### 2. Have SQLite browser ready
```bash
sqlite3 backend/smartkcet.db
```

### 3. Open browser developer console
- Press F12 → Console tab
- This will show any errors from the frontend

## Testing Procedure

### Step 1: Choose Test User
- Username: Any email that has already registered
- Or register a new test user first

### Step 2: Start Payment for Paid Plan
1. Log in to the application
2. Navigate to Subscription page
3. Click any PAID plan button (₹99 Trial, ₹349 Monthly, or ₹2999 Yearly)
   - **NOT** the Free plan (that works correctly)

### Step 3: Complete Razorpay Payment
- Razorpay payment dialog should appear
- Use test card: `4111111111111111`
- Expiry: Any future date (e.g., 12/25)
- CVV: Any 3 digits (e.g., 123)
- Name: Any name
- Click Pay

### Step 4: Capture Console Logs
After payment completes, you should see in the **backend console**:

```
[VERIFY] /verify endpoint HIT
[VERIFY] razorpay_order_id = order_XXXXX
[VERIFY] razorpay_payment_id = pay_XXXXX
[VERIFY] Verifying payment signature...
[VERIFY] ✅ SIGNATURE VERIFICATION SUCCESS
[VERIFY] Razorpay key starts with: rzp_test_
[VERIFY] TEST MODE DETECTED - calling _activate_on_payment directly
[VERIFY] Calling _activate_on_payment(order_XXXXX, ...)

[PAYMENT] _activate_on_payment START - order_id=order_XXXXX
[PAYMENT] Looking for BillingRecord with razorpay_order_id=order_XXXXX
[PAYMENT] ✓ BillingRecord found: id=XXXX, subscription_id=XXXX
[PAYMENT] billing.plan_id = 8bb438a6-a521-4729-bdca-0cb47096e045
[PAYMENT] billing.payment_status = created
[PAYMENT] ✓ Subscription found: id=XXXX, user_id=XXXX, status=expired
[PAYMENT] subscription.plan_id = 842b321d-1de0-4bb0-892f-b2ddf2080a7f
[PAYMENT] Looking for Plan with id=8bb438a6-a521-4729-bdca-0cb47096e045
[PAYMENT] ✓ Plan found: name=7-Day Premium Trial, price=₹99.00, period=weekly
[PAYMENT] ⚙️  Activating subscription...
[PAYMENT]   prev_status = expired
[PAYMENT]   new_status = active
[PAYMENT]   setting plan_id = 8bb438a6-a521-4729-bdca-0cb47096e045
[PAYMENT]   duration = 7 days 00:00:00
[PAYMENT] ✓ Subscription object updated in memory
[PAYMENT]   sub.status NOW = active
[PAYMENT]   sub.plan_id NOW = 8bb438a6-a521-4729-bdca-0cb47096e045
[PAYMENT] Creating SubscriptionEvent for audit trail...
[PAYMENT] ✓ SubscriptionEvent added to session
[PAYMENT] 💾 COMMITTING TO DATABASE...
[PAYMENT] ✅ DB COMMIT SUCCESS
[PAYMENT] ✅ _activate_on_payment COMPLETED SUCCESSFULLY
```

### Critical Questions to Answer

**Q1: Does `[VERIFY] /verify endpoint HIT` appear?**
- If NO → Frontend is not calling /verify endpoint at all (broken callback)
- If YES → Endpoint is being hit

**Q2: Does `[VERIFY] ✅ SIGNATURE VERIFICATION SUCCESS` appear?**
- If NO → Payment signature invalid (should see error)
- If YES → Signature verified correctly

**Q3: Does `[PAYMENT] _activate_on_payment START` appear?**
- If NO → _activate_on_payment not being called (callback flow broken)
- If YES → Function is being called

**Q4: Does function run to completion?**
- Look for: `[PAYMENT] ✅ _activate_on_payment COMPLETED SUCCESSFULLY`
- If appears → Function completed without error
- If doesn't appear → Function failed at some point

**Q5: If it fails, what's the error?**
- Look for: `[PAYMENT] ❌ EXCEPTION IN _activate_on_payment:`
- Capture the full traceback

## Step 5: Check Database Immediately After Payment

Open SQLite while backend is still running, BEFORE reloading the page:

```bash
sqlite3 backend/smartkcet.db
```

### Query 1: Check billing record
```sql
SELECT id, subscription_id, plan_id, payment_status, razorpay_order_id, razorpay_payment_id 
FROM billing_records 
ORDER BY created_at DESC 
LIMIT 3;
```

**Expected output after payment:**
```
billing_record_id | sub_id | plan_id (7-Day Premium) | payment_status=paid | razorpay_order_id | razorpay_payment_id
```

### Query 2: Check subscription status
```sql
SELECT id, user_id, status, plan_id, start_date, next_renewal_date 
FROM subscriptions 
ORDER BY created_at DESC 
LIMIT 3;
```

**Expected output after payment:**
```
sub_id | user_id | status=active | plan_id (7-Day Premium) | start_date (NOW) | next_renewal_date (NOW + 7 days)
```

### Query 3: Verify plan exists
```sql
SELECT id, name, price FROM subscription_plans WHERE name LIKE '%Premium%' OR name LIKE '%Trial%';
```

**Expected output:**
```
8bb438a6-a521-4729-bdca-0cb47096e045 | 7-Day Premium Trial | 99.00
ba352fa1-4b12-4ea4-a019-8b50bde55eb9 | Pro Monthly | 349.00
e04a7178-13e7-4853-a6f4-c84050f0f0ce | Pro Yearly | 2999.00
```

## Step 6: Check Browser After Payment

Refresh the page or navigate to Subscription page.

**Expected behavior after successful payment:**
- Dashboard shows: "7-Day Premium Trial Active" (NOT "Free Active")
- Subscription page shows:
  - PLAN: "7-Day Premium Trial"
  - STATUS: "Active"
  - STARTS: Today's date
  - EXPIRES: Date 7 days from today

**Actual behavior if bug still present:**
- Dashboard shows: "Free Active"
- Subscription page shows:
  - PLAN: "—" (blank)
  - STATUS: "Active"

## Step 7: Document Evidence

Save/screenshot:
1. **Backend console output** - All the `[VERIFY]` and `[PAYMENT]` logs
2. **Database query results** - The three SELECT statements above
3. **Browser screenshot** - Subscription page after payment

## Likely Failure Points

Based on the structure, the bug is most likely at one of these points:

1. **Frontend not calling /verify**
   - Check if `[VERIFY] /verify endpoint HIT` appears
   - If not: Browser console (F12) will show network error

2. **Subscription not created for order**
   - Check: Does BillingRecord exist? (Query 1)
   - If not: Order creation failed

3. **Plan not found in database**
   - Look for: `[PAYMENT] ❌ PLAN NOT FOUND`
   - Check: Query 3 - does 7-Day Premium Trial exist?

4. **Database commit fails silently**
   - Look for: Does `[PAYMENT] ✅ DB COMMIT SUCCESS` appear?
   - If NO: Exception being caught silently, or no error but no commit

5. **Session rolled back after commit**
   - Check: Database Query 2 - is subscription.status still "expired"?
   - If yes: Commit succeeded but then something rolled it back

## Next Steps After Gathering Evidence

Once you have the logs and database output, the evidence will show:
- Exact point where the flow breaks
- Error message (if any)
- Whether activation code runs but doesn't persist
- Whether activation code doesn't run at all

This will definitively prove what the real bug is.

**REMEMBER: No "fixed" claims without this evidence.**
