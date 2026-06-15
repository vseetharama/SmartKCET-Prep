#!/usr/bin/env node
/**
 * Node.js Test Runner for Bug Condition Exploration Tests
 * Loads the subscription modal module and runs bug condition tests
 */

const fs = require('fs');
const path = require('path');

console.log('\n🧪 Bug Condition Exploration Test Runner\n');
console.log('Testing: Frontend Plan Selection Array Index Bug');
console.log('Expected: Tests MUST FAIL on unfixed code (failure = bug confirmed)\n');
console.log('='.repeat(60) + '\n');

// Track payment calls for verification
global._testPaymentCalls = [];

// Mock fetch for Node.js environment
global.fetch = function(url, options) {
  if (url === '/api/payments/plans/student') {
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function() {
        return Promise.resolve({
          plans: [
            {
              id: 'plan-trial-uuid',
              name: '7-Day Premium Trial',
              price: 99.00,
              billing_period: 'weekly',
              max_test_attempts: 999,
            },
            {
              id: 'plan-monthly-uuid',
              name: 'Pro Monthly',
              price: 349.00,
              billing_period: 'monthly',
              max_test_attempts: 999,
            },
            {
              id: 'plan-yearly-uuid',
              name: 'Pro Yearly',
              price: 2999.00,
              billing_period: 'yearly',
              max_test_attempts: 999,
            },
          ],
          key_id: 'test-key-id',
        });
      },
    });
  }
  if (url === '/api/payments/create-order') {
    const payload = options && options.body ? JSON.parse(options.body) : {};
    global._testPaymentCalls.push({
      url: url,
      payload: payload,
      timestamp: Date.now(),
    });
  }
  return Promise.reject(new Error('Unexpected fetch: ' + url));
};

// Mock document/window for Node environment
global.document = {
  readyState: 'complete',
  addEventListener: function() {},
  querySelectorAll: function() { return []; },
  querySelector: function() { return null; },
  getElementById: function(id) {
    if (id === 'subscriptionModal') {
      return {
        querySelector: () => null,
        querySelectorAll: () => [],
        style: {},
        classList: { add: () => {}, remove: () => {} },
        setAttribute: () => {},
        getAttribute: () => null,
        addEventListener: () => {},
        removeEventListener: () => {},
        contains: () => true,
        focus: () => {},
      };
    }
    return null;
  },
  body: {
    classList: { add: () => {}, remove: () => {} },
  },
  activeElement: null,
};

global.window = {
  document: global.document,
  location: { reload: () => {} },
  ErrorHandler: { setFlashSuccess: () => {}, showSuccess: () => {} },
  FocusTrap: null,
  Razorpay: null,
  addEventListener: function() {},
  removeEventListener: function() {},
  getComputedStyle: () => ({}),
};

// Load subscription modal module
console.log('[loader] Loading subscription-modal.js...');
const subscriptionModalCode = fs.readFileSync(path.join(__dirname, 'js', 'subscription-modal.js'), 'utf8');
eval(subscriptionModalCode);

// Load test module
console.log('[loader] Loading subscription-modal.test.js...\n');
const testCode = fs.readFileSync(path.join(__dirname, 'js', 'subscription-modal.test.js'), 'utf8');
eval(testCode);

// Run the tests
console.log('[runner] Executing bug condition exploration tests...\n');

// Run tests and wait for completion
setTimeout(async function() {
  try {
    // Give the async tests time to complete
    await new Promise(resolve => setTimeout(resolve, 3000));

    const results = global.window._bugConditionTestResults;
    const paymentCalls = global._testPaymentCalls;

    console.log('\n' + '='.repeat(60));
    console.log('PAYMENT CALL VERIFICATION:');
    console.log('='.repeat(60));
    console.log('Total payment calls captured:', paymentCalls.length);
    
    let paymentVerificationPassed = true;
    let verificationDetails = [];

    // Verify trial payment
    if (paymentCalls.length >= 1) {
      const trialCall = paymentCalls[0];
      const trialPassed = 
        trialCall.payload.plan_id === 'plan-trial-uuid' &&
        trialCall.payload.plan_id.length > 0 &&
        !/^\d+$/.test(trialCall.payload.plan_id);
      
      console.log('\n✓ Trial Payment:');
      console.log('  plan_id:', trialCall.payload.plan_id);
      console.log('  Is UUID (not index):', !(/^\d+$/.test(trialCall.payload.plan_id)));
      console.log('  Status:', trialPassed ? '✅ PASS' : '❌ FAIL');
      
      verificationDetails.push({
        test: 'Trial Plan Payment',
        planId: trialCall.payload.plan_id,
        passed: trialPassed,
      });
      
      if (!trialPassed) paymentVerificationPassed = false;
    }

    // Verify monthly payment
    if (paymentCalls.length >= 2) {
      const monthlyCall = paymentCalls[1];
      const monthlyPassed = 
        monthlyCall.payload.plan_id === 'plan-monthly-uuid' &&
        monthlyCall.payload.plan_id.length > 0 &&
        !/^\d+$/.test(monthlyCall.payload.plan_id);
      
      console.log('\n✓ Monthly Payment:');
      console.log('  plan_id:', monthlyCall.payload.plan_id);
      console.log('  Is UUID (not index):', !(/^\d+$/.test(monthlyCall.payload.plan_id)));
      console.log('  Status:', monthlyPassed ? '✅ PASS' : '❌ FAIL');
      
      verificationDetails.push({
        test: 'Monthly Plan Payment',
        planId: monthlyCall.payload.plan_id,
        passed: monthlyPassed,
      });
      
      if (!monthlyPassed) paymentVerificationPassed = false;
    }

    // Verify yearly payment
    if (paymentCalls.length >= 3) {
      const yearlyCall = paymentCalls[2];
      const yearlyPassed = 
        yearlyCall.payload.plan_id === 'plan-yearly-uuid' &&
        yearlyCall.payload.plan_id.length > 0 &&
        !/^\d+$/.test(yearlyCall.payload.plan_id);
      
      console.log('\n✓ Yearly Payment:');
      console.log('  plan_id:', yearlyCall.payload.plan_id);
      console.log('  Is UUID (not index):', !(/^\d+$/.test(yearlyCall.payload.plan_id)));
      console.log('  Status:', yearlyPassed ? '✅ PASS' : '❌ FAIL');
      
      verificationDetails.push({
        test: 'Yearly Plan Payment',
        planId: yearlyCall.payload.plan_id,
        passed: yearlyPassed,
      });
      
      if (!yearlyPassed) paymentVerificationPassed = false;
    }

    console.log('\n' + '='.repeat(60));
    console.log('BUG 1 FIX VERIFICATION:');
    console.log('='.repeat(60));
    
    if (paymentVerificationPassed && paymentCalls.length === 3) {
      console.log('✅ PASS: All plan payments sent correct UUIDs (not array indices)');
      console.log('✅ PASS: Bug 1 has been FIXED - plan objects sent correctly');
    } else {
      console.log('❌ FAIL: Payment calls do not match expected format');
      console.log('Payment calls details:', JSON.stringify(paymentCalls, null, 2));
    }

    console.log('\n' + '='.repeat(60));
    console.log('FINAL TEST RESULTS:');
    console.log('='.repeat(60));

    if (results) {
      console.log('✅ Passed:', results.passed);
      console.log('❌ Failed:', results.failed);
      console.log('Bug Detected:', results.bugDetected ? 'YES' : 'NO');
    }

    console.log('\n' + '='.repeat(60));
    if (paymentVerificationPassed && paymentCalls.length === 3) {
      console.log('🎉 SUCCESS: Bug 1 Exploration Test PASSES on FIXED code');
      console.log('\nBug Fix Confirmed:');
      console.log('  ✅ All plan buttons send correct plan UUID');
      console.log('  ✅ No array indices in payment requests');
      console.log('  ✅ Payment API receives proper plan_id values');
    } else {
      console.log('⚠️ WARNING: Test verification incomplete');
      console.log('Details:', JSON.stringify(verificationDetails, null, 2));
    }
    console.log('='.repeat(60) + '\n');

    process.exit(paymentVerificationPassed && paymentCalls.length === 3 ? 0 : 1);
  } catch (err) {
    console.error('\n❌ ERROR:', err.message);
    console.error(err.stack);
    process.exit(1);
  }
}, 3500);
