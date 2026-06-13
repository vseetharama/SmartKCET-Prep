// SmartKCET Prep — Subscription Module Tests
// Unit tests for subscription state management and caching

// Test helper to simulate sessionStorage
function createMockSessionStorage() {
  var store = {};
  return {
    getItem: function(key) {
      return store[key] || null;
    },
    setItem: function(key, value) {
      store[key] = value;
    },
    removeItem: function(key) {
      delete store[key];
    },
    clear: function() {
      store = {};
    },
    _getStore: function() {
      return store;
    }
  };
}

// Test Suite
function runTests() {
  console.log('🧪 Running Subscription Module Tests...\n');

  var testsPassed = 0;
  var testsFailed = 0;

  function assert(condition, message) {
    if (condition) {
      console.log('✅ PASS:', message);
      testsPassed++;
    } else {
      console.error('❌ FAIL:', message);
      testsFailed++;
    }
  }

  // Test 1: SubscriptionState.set() stores data with timestamp and TTL
  console.log('\n--- Test 1: Cache Storage ---');
  sessionStorage.clear();
  var testData = { plan_name: 'Free Trial', status: 'trial' };
  SubscriptionState.set(testData);
  var cached = JSON.parse(sessionStorage.getItem(SubscriptionState.CACHE_KEY));
  assert(cached !== null, 'Cache should be stored');
  assert(cached.data.plan_name === 'Free Trial', 'Cache should contain correct data');
  assert(cached.timestamp > 0, 'Cache should have timestamp');
  assert(cached.ttl === 60000, 'Cache should have 60-second TTL');

  // Test 2: SubscriptionState.get() returns cached data if valid
  console.log('\n--- Test 2: Cache Retrieval ---');
  var retrieved = SubscriptionState.get();
  assert(retrieved !== null, 'Should retrieve cached data');
  assert(retrieved.plan_name === 'Free Trial', 'Retrieved data should match stored data');

  // Test 3: SubscriptionState.isValid() returns true for valid cache
  console.log('\n--- Test 3: Cache Validation ---');
  assert(SubscriptionState.isValid() === true, 'Cache should be valid');

  // Test 4: SubscriptionState.get() returns null for expired cache
  console.log('\n--- Test 4: Cache Expiration ---');
  // Manually set an expired cache
  var expiredCache = {
    data: testData,
    timestamp: Date.now() - 70000, // 70 seconds ago (expired)
    ttl: 60000
  };
  sessionStorage.setItem(SubscriptionState.CACHE_KEY, JSON.stringify(expiredCache));
  var expiredRetrieved = SubscriptionState.get();
  assert(expiredRetrieved === null, 'Expired cache should return null');
  assert(SubscriptionState.isValid() === false, 'Expired cache should be invalid');

  // Test 5: SubscriptionState.clear() removes cached data
  console.log('\n--- Test 5: Cache Clearing ---');
  SubscriptionState.set(testData);
  assert(SubscriptionState.isValid() === true, 'Cache should be valid before clear');
  SubscriptionState.clear();
  assert(SubscriptionState.isValid() === false, 'Cache should be invalid after clear');
  assert(sessionStorage.getItem(SubscriptionState.CACHE_KEY) === null, 'Cache should be removed from sessionStorage');

  // Test 6: Cache TTL is exactly 60 seconds
  console.log('\n--- Test 6: TTL Value ---');
  assert(SubscriptionState.TTL === 60000, 'TTL should be 60000ms (60 seconds)');

  // Test 7: Cache key is consistent
  console.log('\n--- Test 7: Cache Key ---');
  assert(SubscriptionState.CACHE_KEY === 'smartkcet_subscription', 'Cache key should be smartkcet_subscription');

  // Test 8: Subscription module exposes correct methods
  console.log('\n--- Test 8: Subscription Module API ---');
  assert(typeof Subscription.getStatus === 'function', 'Subscription.getStatus should be a function');
  assert(typeof Subscription.activateTrial === 'function', 'Subscription.activateTrial should be a function');
  assert(typeof Subscription.activatePro === 'function', 'Subscription.activatePro should be a function');
  assert(typeof Subscription.upgrade === 'function', 'Subscription.upgrade should be a function');
  assert(typeof Subscription.cancel === 'function', 'Subscription.cancel should be a function');
  assert(typeof Subscription.getBillingHistory === 'function', 'Subscription.getBillingHistory should be a function');
  assert(typeof Subscription.checkExamAccess === 'function', 'Subscription.checkExamAccess should be a function');
  assert(typeof Subscription.clearCache === 'function', 'Subscription.clearCache should be a function');
  assert(typeof Subscription.startPolling === 'function', 'Subscription.startPolling should be a function');
  assert(typeof Subscription.stopPolling === 'function', 'Subscription.stopPolling should be a function');

  // Test 9: Subscription.clearCache() delegates to SubscriptionState.clear()
  console.log('\n--- Test 9: Subscription.clearCache() ---');
  SubscriptionState.set(testData);
  assert(SubscriptionState.isValid() === true, 'Cache should be valid before clearCache');
  Subscription.clearCache();
  assert(SubscriptionState.isValid() === false, 'Cache should be invalid after clearCache');

  // Test 10: Action methods dispatch `subscriptionStatusChanged` after a
  // successful refresh so banner/page/upgrade-prompt update within 5s.
  // Validates: Requirements 12.3, 12.6, 4.9
  console.log('\n--- Test 10: Action dispatches subscriptionStatusChanged ---');
  var actions = [
    { name: 'activateTrial', invoke: function () { return Subscription.activateTrial(); }, apiMethod: 'activateTrial' },
    { name: 'activatePro', invoke: function () { return Subscription.activatePro('weekly'); }, apiMethod: 'activatePro' },
    { name: 'upgrade', invoke: function () { return Subscription.upgrade('monthly'); }, apiMethod: 'upgrade' },
    { name: 'cancel', invoke: function () { return Subscription.cancel(); }, apiMethod: 'cancel' },
  ];

  // Stub SubscriptionAPI so the action methods don't hit the network.
  var originalApi = {};
  actions.forEach(function (a) { originalApi[a.apiMethod] = SubscriptionAPI[a.apiMethod]; });
  var originalGetStatus = SubscriptionAPI.getStatus;

  // Run each action, capture the event, and assert.
  (async function () {
    for (var i = 0; i < actions.length; i++) {
      var action = actions[i];
      var freshPayload = { plan_name: action.name + '-fresh', status: 'active', remaining_attempts: 3 };

      // Stub the action endpoint to return success and the GET endpoint to
      // return the fresh payload Subscription.getStatus(true) will fetch.
      SubscriptionAPI[action.apiMethod] = function () {
        return Promise.resolve({ ok: true, status: 200, data: { id: 'stub' } });
      };
      SubscriptionAPI.getStatus = (function (payload) {
        return function () {
          return Promise.resolve({ ok: true, status: 200, data: payload });
        };
      })(freshPayload);

      sessionStorage.clear();

      var captured = null;
      var listener = function (evt) { captured = evt && evt.detail ? evt.detail.subscription : null; };
      window.addEventListener('subscriptionStatusChanged', listener);

      try {
        await action.invoke();
        assert(captured !== null, action.name + ' should dispatch subscriptionStatusChanged');
        assert(
          captured && captured.plan_name === freshPayload.plan_name,
          action.name + ' event should carry fresh subscription data'
        );
        // Cache should be repopulated by the post-action getStatus(true).
        assert(
          SubscriptionState.isValid() === true,
          action.name + ' should leave fresh data in the cache'
        );
      } finally {
        window.removeEventListener('subscriptionStatusChanged', listener);
      }
    }

    // Restore originals.
    actions.forEach(function (a) { SubscriptionAPI[a.apiMethod] = originalApi[a.apiMethod]; });
    SubscriptionAPI.getStatus = originalGetStatus;
    sessionStorage.clear();

    // Final summary (printed once async tests finish).
    console.log('\n' + '='.repeat(50));
    console.log('Test Results:');
    console.log('✅ Passed:', testsPassed);
    console.log('❌ Failed:', testsFailed);
    console.log('='.repeat(50));
    if (testsFailed === 0) {
      console.log('\n🎉 All tests passed!');
    } else {
      console.log('\n⚠️ Some tests failed. Please review the implementation.');
    }
  })();

  // Synchronous-portion summary — async results print above when ready.
  return testsFailed === 0;
}

// Run tests if this file is loaded in a browser
if (typeof window !== 'undefined' && typeof SubscriptionState !== 'undefined') {
  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runTests);
  } else {
    runTests();
  }
}
