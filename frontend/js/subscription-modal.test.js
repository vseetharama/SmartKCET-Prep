// SmartKCET Prep — Subscription Modal Bug Condition Exploration Tests
// Tests to verify the bug condition exists: plan selection sends array index instead of plan object
// These tests MUST FAIL on unfixed code to confirm the bug exists
//
// **Validates: Requirements 1.1, 1.2**
// Bug Condition: Frontend sends selectedPlan[0] (array index) instead of plan object
// Expected Behavior: Payment handler receives complete plan object with {id, name, price}

/**
 * Test helper: Mock the payment handler to capture what gets passed to it
 */
function createMockPaymentCapture() {
  var captured = {
    calls: [],
    lastCall: null,
  };

  return {
    install: function () {
      // Override fetch to capture payment order creation requests
      var originalFetch = window.fetch;
      window.fetch = function(url, options) {
        if (url === '/api/payments/create-order') {
          var payload = options && options.body ? JSON.parse(options.body) : {};
          
          // Extract plan details from the request
          captured.lastCall = {
            plan_id: payload.plan_id,
            timestamp: Date.now(),
            originalFetch: originalFetch,
          };
          captured.calls.push(captured.lastCall);
          console.log('[test-capture] Payment order creation intercepted:', payload);
          
          // Reject with known error to prevent further processing
          return Promise.reject(new Error('Test: Payment capture - not actually creating order'));
        }
        return originalFetch(url, options);
      };
    },

    restore: function () {
      // Restored via window.fetch reassignment in test
    },

    getCalls: function () {
      return captured.calls;
    },

    getLastCall: function () {
      return captured.lastCall;
    },

    getPlans: function () {
      // Return the plans that were used in the modal
      if (typeof SubscriptionModal !== 'undefined' && SubscriptionModal._plans) {
        return SubscriptionModal._plans;
      }
      return [];
    },

    clear: function () {
      captured.calls = [];
      captured.lastCall = null;
    },
  };
}

/**
 * Test Suite: Bug Condition Exploration
 * 
 * Goal: Surface counterexamples showing the bug condition exists
 * These tests MUST FAIL on unfixed code (failure = bug confirmed)
 * 
 * Bug: When plan selection buttons are clicked, _initiatePayment() receives selectedPlan[0]
 * (array index) instead of the plan object, causing payment API to receive undefined properties.
 * 
 * This test verifies:
 * 1. That _initiatePayment() is called with a plan object (not an array index)
 * 2. That the plan object has valid id, name, and price properties
 * 3. That these properties are NOT undefined or numeric array indices
 */
function runBugConditionExplorationTests() {
  console.log('\n🧪 Bug Condition Exploration: Frontend Plan Selection Array Index\n');
  console.log('Required 1.1: When student clicks plan button, frontend should send');
  console.log('              selectedPlan (not selectedPlan[0])');
  console.log('Required 1.2: Payment API should receive correct plan object with');
  console.log('              id, name, price properties\n');

  var testsPassed = 0;
  var testsFailed = 0;
  var failingExamples = [];

  function assert(condition, message, details) {
    if (condition) {
      console.log('✅ PASS:', message);
      testsPassed++;
    } else {
      console.error('❌ FAIL:', message);
      if (details) {
        console.error('   Details:', JSON.stringify(details, null, 2));
        failingExamples.push({
          test: message,
          details: details,
        });
      }
      testsFailed++;
    }
  }

  // Mock setup
  var paymentCapture = createMockPaymentCapture();

  // Set up a minimal mock environment
  var originalFetch = window.fetch;
  window.fetch = function (url) {
    if (url === '/api/payments/plans/student') {
      return Promise.resolve({
        ok: true,
        json: function () {
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
    return Promise.reject(new Error('Unexpected fetch: ' + url));
  };

  console.log('--- Test 1: Trial Button Click ---');
  (async function runTest1() {
    try {
      // Set up modal and install capture
      await SubscriptionModal.init();
      paymentCapture.install(SubscriptionModal);

      // Simulate trial button click
      console.log('[test] Simulating trial button click...');
      await SubscriptionModal.selectTrial();

      var lastCall = paymentCapture.getLastCall();

      // ASSERTION 1: Payment handler was called
      assert(lastCall !== null, 'Trial button click should trigger _initiatePayment()');

      if (lastCall) {
        var plan = lastCall.plan;

        // ASSERTION 2a: Plan is NOT an array (bug would be array[0])
        assert(
          !Array.isArray(plan),
          'Plan should NOT be an array (buggy code would pass array[0])',
          { plan: plan, isArray: Array.isArray(plan) }
        );

        // ASSERTION 2b: Plan is an object with properties
        assert(
          plan && typeof plan === 'object',
          'Plan should be an object',
          { plan: plan, type: typeof plan }
        );

        // ASSERTION 3: Plan id is a valid UUID string (not a number/index)
        assert(
          plan && typeof plan.id === 'string' && plan.id.length > 0 && !/^\d+$/.test(plan.id),
          'Plan.id should be a UUID string, not a numeric array index',
          { planId: plan ? plan.id : undefined, idType: plan ? typeof plan.id : undefined }
        );

        // ASSERTION 4: Plan has correct UUID value
        assert(
          plan && plan.id === 'plan-trial-uuid',
          'Plan id should be trial plan UUID',
          { planId: plan ? plan.id : undefined }
        );

        // ASSERTION 5: Plan name is a valid string (not undefined)
        assert(
          plan && typeof plan.name === 'string' && plan.name.length > 0,
          'Plan.name should be a non-empty string, not undefined',
          { planName: plan ? plan.name : undefined, nameType: plan ? typeof plan.name : undefined }
        );

        // ASSERTION 6: Plan name is correct
        assert(
          plan && plan.name === '7-Day Premium Trial',
          'Plan name should be "7-Day Premium Trial"',
          { planName: plan ? plan.name : undefined }
        );

        // ASSERTION 7: Plan price is a valid number (not undefined)
        assert(
          plan && typeof plan.price === 'number' && plan.price > 0,
          'Plan.price should be a positive number, not undefined',
          { planPrice: plan ? plan.price : undefined, priceType: plan ? typeof plan.price : undefined }
        );

        // ASSERTION 8: Plan price is correct value
        assert(
          plan && plan.price === 99.00,
          'Plan price should be 99.00',
          { planPrice: plan ? plan.price : undefined }
        );
      }

      paymentCapture.clear();
    } catch (err) {
      console.error('[test] Test 1 error:', err);
      failingExamples.push({
        test: 'Trial Button Click',
        error: err.message,
      });
      testsFailed++;
    }

    // After a short delay, run Test 2
    setTimeout(runTest2, 100);
  })();

  function runTest2() {
    console.log('\n--- Test 2: Monthly Button Click ---');
    (async function () {
      try {
        paymentCapture.clear();

        // Simulate monthly button click
        console.log('[test] Simulating monthly button click...');
        await SubscriptionModal.selectMonthly();

        var lastCall = paymentCapture.getLastCall();

        // ASSERTION 1: Payment handler was called
        assert(lastCall !== null, 'Monthly button click should trigger _initiatePayment()');

        if (lastCall) {
          var plan = lastCall.plan;

          // ASSERTION 2a: Plan is NOT an array
          assert(
            !Array.isArray(plan),
            'Plan should NOT be an array (buggy code would pass array[0])',
            { plan: plan, isArray: Array.isArray(plan) }
          );

          // ASSERTION 3: Plan is proper object
          assert(
            plan && typeof plan === 'object',
            'Plan should be an object',
            { plan: plan, type: typeof plan }
          );

          // ASSERTION 4: Plan id is UUID string, not index
          assert(
            plan && typeof plan.id === 'string' && plan.id.length > 0 && !/^\d+$/.test(plan.id),
            'Plan.id should be a UUID string, not a numeric array index',
            { planId: plan ? plan.id : undefined, idType: plan ? typeof plan.id : undefined }
          );

          // ASSERTION 5: Plan id has correct value
          assert(
            plan && plan.id === 'plan-monthly-uuid',
            'Plan id should be monthly plan UUID',
            { planId: plan ? plan.id : undefined }
          );

          // ASSERTION 6: Plan name is valid string
          assert(
            plan && typeof plan.name === 'string' && plan.name.length > 0,
            'Plan.name should be a non-empty string, not undefined',
            { planName: plan ? plan.name : undefined, nameType: plan ? typeof plan.name : undefined }
          );

          // ASSERTION 7: Plan name correct
          assert(
            plan && plan.name === 'Pro Monthly',
            'Plan name should be "Pro Monthly"',
            { planName: plan ? plan.name : undefined }
          );

          // ASSERTION 8: Plan price is valid number
          assert(
            plan && typeof plan.price === 'number' && plan.price > 0,
            'Plan.price should be a positive number, not undefined',
            { planPrice: plan ? plan.price : undefined, priceType: plan ? typeof plan.price : undefined }
          );

          // ASSERTION 9: Plan price correct
          assert(
            plan && plan.price === 349.00,
            'Plan price should be 349.00',
            { planPrice: plan ? plan.price : undefined }
          );
        }

        paymentCapture.clear();
      } catch (err) {
        console.error('[test] Test 2 error:', err);
        failingExamples.push({
          test: 'Monthly Button Click',
          error: err.message,
        });
        testsFailed++;
      }

      // After a short delay, run Test 3
      setTimeout(runTest3, 100);
    })();
  }

  function runTest3() {
    console.log('\n--- Test 3: Yearly Button Click ---');
    (async function () {
      try {
        paymentCapture.clear();

        // Simulate yearly button click
        console.log('[test] Simulating yearly button click...');
        await SubscriptionModal.selectYearly();

        var lastCall = paymentCapture.getLastCall();

        // ASSERTION 1: Payment handler was called
        assert(lastCall !== null, 'Yearly button click should trigger _initiatePayment()');

        if (lastCall) {
          var plan = lastCall.plan;

          // ASSERTION 2a: Plan is NOT an array
          assert(
            !Array.isArray(plan),
            'Plan should NOT be an array (buggy code would pass array[0])',
            { plan: plan, isArray: Array.isArray(plan) }
          );

          // ASSERTION 3: Plan is proper object
          assert(
            plan && typeof plan === 'object',
            'Plan should be an object',
            { plan: plan, type: typeof plan }
          );

          // ASSERTION 4: Plan id is UUID string, not index
          assert(
            plan && typeof plan.id === 'string' && plan.id.length > 0 && !/^\d+$/.test(plan.id),
            'Plan.id should be a UUID string, not a numeric array index',
            { planId: plan ? plan.id : undefined, idType: plan ? typeof plan.id : undefined }
          );

          // ASSERTION 5: Plan id correct
          assert(
            plan && plan.id === 'plan-yearly-uuid',
            'Plan id should be yearly plan UUID',
            { planId: plan ? plan.id : undefined }
          );

          // ASSERTION 6: Plan name is valid string
          assert(
            plan && typeof plan.name === 'string' && plan.name.length > 0,
            'Plan.name should be a non-empty string, not undefined',
            { planName: plan ? plan.name : undefined, nameType: plan ? typeof plan.name : undefined }
          );

          // ASSERTION 7: Plan name correct
          assert(
            plan && plan.name === 'Pro Yearly',
            'Plan name should be "Pro Yearly"',
            { planName: plan ? plan.name : undefined }
          );

          // ASSERTION 8: Plan price is valid number
          assert(
            plan && typeof plan.price === 'number' && plan.price > 0,
            'Plan.price should be a positive number, not undefined',
            { planPrice: plan ? plan.price : undefined, priceType: plan ? typeof plan.price : undefined }
          );

          // ASSERTION 9: Plan price correct
          assert(
            plan && plan.price === 2999.00,
            'Plan price should be 2999.00',
            { planPrice: plan ? plan.price : undefined }
          );
        }

        paymentCapture.clear();
      } catch (err) {
        console.error('[test] Test 3 error:', err);
        failingExamples.push({
          test: 'Yearly Button Click',
          error: err.message,
        });
        testsFailed++;
      }

      // After a short delay, finalize
      setTimeout(finalizeTests, 100);
    })();
  }

  function finalizeTests() {
    console.log('\n' + '='.repeat(60));
    console.log('Bug Condition Exploration Test Results:');
    console.log('✅ Passed:', testsPassed);
    console.log('❌ Failed:', testsFailed);
    console.log('='.repeat(60));

    if (failingExamples.length > 0) {
      console.log('\n⚠️ FAILING COUNTEREXAMPLES (Bug Evidence):');
      console.log(JSON.stringify(failingExamples, null, 2));
    }

    if (testsFailed === 0) {
      console.log('\n🎉 All tests passed! Bug does NOT exist in this code.');
    } else {
      console.log('\n❌ Tests failed. Bug condition detected:');
      console.log('   - Frontend sends array index instead of plan object');
      console.log('   - Plan object properties (id, name, price) are undefined/incorrect');
      console.log('   - This prevents payment API from receiving correct plan details');
    }

    // Cleanup
    paymentCapture.restore();
    window.fetch = originalFetch;

    // Report final status
    window._bugConditionTestResults = {
      passed: testsPassed,
      failed: testsFailed,
      failingExamples: failingExamples,
      bugDetected: testsFailed > 0,
    };
  }
}

// Auto-run tests when document is ready
if (typeof window !== 'undefined' && typeof SubscriptionModal !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runBugConditionExplorationTests);
  } else {
    runBugConditionExplorationTests();
  }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    runBugConditionExplorationTests: runBugConditionExplorationTests,
    createMockPaymentCapture: createMockPaymentCapture,
  };
}
