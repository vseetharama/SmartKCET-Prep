// SmartKCET Prep — Error Handler Module Tests
// Unit tests covering the session-expiry handling and global fetch
// 401 interceptor introduced in task 15.2.
//
// Validates: Requirements 12.7, 14.8
//
// Runs under both Node (CI) and the browser. The tests stub the
// browser globals error-handler.js relies on (window, document,
// sessionStorage) so the module can be exercised in isolation.

(async function () {
  'use strict';

  // ── Minimal browser-like environment for Node ──────────────────────────

  if (typeof globalThis.window === 'undefined') {
    var navigationLog = [];
    var fakeLocation = {
      pathname: '/dashboard',
      search: '?ref=test',
      origin: 'http://localhost',
      _href: 'http://localhost/dashboard?ref=test',
      get href() { return this._href; },
      set href(v) {
        this._href = v;
        navigationLog.push(v);
      },
    };

    var fakeStorage = (function () {
      var store = {};
      return {
        getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
        setItem: function (k, v) { store[k] = String(v); },
        removeItem: function (k) { delete store[k]; },
        clear: function () { store = {}; },
        _store: function () { return store; },
      };
    })();

    var fakeBody = {
      _children: [],
      appendChild: function (el) { this._children.push(el); el.parentNode = this; },
      removeChild: function (el) {
        var i = this._children.indexOf(el);
        if (i >= 0) { this._children.splice(i, 1); el.parentNode = null; }
      },
    };

    var fakeDocument = {
      body: fakeBody,
      readyState: 'complete',
      addEventListener: function () {},
      removeEventListener: function () {},
      createElement: function (tag) {
        return {
          tagName: tag.toUpperCase(),
          className: '',
          textContent: '',
          style: {},
          parentNode: null,
          offsetHeight: 40,
          setAttribute: function (k, v) { this[k] = v; },
          appendChild: function () {},
        };
      },
      querySelectorAll: function () { return fakeBody._children.slice(); },
    };

    globalThis.window = {
      location: fakeLocation,
      addEventListener: function () {},
      removeEventListener: function () {},
      // window.fetch is set per-test below.
      fetch: undefined,
    };
    globalThis.document = fakeDocument;
    globalThis.sessionStorage = fakeStorage;
    globalThis._navigationLog = navigationLog;
    globalThis._fakeStorage = fakeStorage;
    globalThis._fakeLocation = fakeLocation;

    // URL polyfill check — Node 14+ has it built in.
    if (typeof globalThis.URL === 'undefined') {
      globalThis.URL = require('url').URL;
    }
  }

  // ── Load error-handler under test ──────────────────────────────────────

  if (typeof globalThis.ErrorHandler === 'undefined') {
    if (typeof require === 'function') {
      var fs = require('fs');
      var path = require('path');
      var src = fs.readFileSync(path.join(__dirname, 'error-handler.js'), 'utf8');
      // eslint-disable-next-line no-eval
      (0, eval)(src);
    } else {
      throw new Error('ErrorHandler global is missing — load error-handler.js first.');
    }
  }

  // ── Tiny test harness ──────────────────────────────────────────────────

  var passed = 0;
  var failed = 0;
  var failures = [];

  function assert(cond, msg) {
    if (cond) {
      passed++;
    } else {
      failed++;
      failures.push(msg);
      console.error('  FAIL:', msg);
    }
  }

  async function group(name, fn) {
    console.log('\n— ' + name + ' —');
    await fn();
  }

  function resetAll() {
    if (globalThis._navigationLog) globalThis._navigationLog.length = 0;
    if (globalThis._fakeStorage) globalThis._fakeStorage.clear();
    if (globalThis._fakeLocation) {
      globalThis._fakeLocation.pathname = '/dashboard';
      globalThis._fakeLocation.search = '';
      globalThis._fakeLocation._href = 'http://localhost/dashboard';
    }
    ErrorHandler._resetForTests();
  }

  function lastNavigation() {
    var log = globalThis._navigationLog || [];
    return log[log.length - 1] || null;
  }

  // Helper: make a Response-like object the interceptor can inspect.
  function makeResponse(status) {
    return { status: status, ok: status >= 200 && status < 300 };
  }

  // Helper: install a stub fetch returning a fixed Response.
  function stubFetch(status) {
    var calls = [];
    globalThis.window.fetch = function (input, init) {
      calls.push({ input: input, init: init });
      return Promise.resolve(makeResponse(status));
    };
    globalThis.fetch = globalThis.window.fetch;
    return calls;
  }

  // ── Tests ──────────────────────────────────────────────────────────────

  await group('handleSessionExpiry clears sessionStorage and redirects (REQ 12.7, 14.8)', async function () {
    resetAll();
    sessionStorage.setItem('smartkcet_subscription', JSON.stringify({ data: { status: 'trial' } }));
    sessionStorage.setItem('other_key', 'value');

    ErrorHandler.handleSessionExpiry();

    assert(sessionStorage.getItem('smartkcet_subscription') === null,
      'sessionStorage subscription cache is cleared on session expiry');
    assert(sessionStorage.getItem('other_key') === null,
      'all sessionStorage keys are cleared on session expiry');

    var dest = lastNavigation();
    assert(dest && dest.indexOf('/login') === 0,
      'session expiry redirects to /login (got ' + dest + ')');
    assert(dest && dest.indexOf('return=') !== -1,
      'login redirect includes a return parameter');
    assert(dest && dest.indexOf('expired=1') !== -1,
      'login redirect includes expired=1 marker');
    assert(dest && dest.indexOf(encodeURIComponent('/dashboard')) !== -1,
      'return parameter encodes the original path');
  });

  await group('handleSessionExpiry is idempotent across parallel 401s', async function () {
    resetAll();
    ErrorHandler.handleSessionExpiry();
    var firstNav = lastNavigation();

    // Subsequent calls (e.g. from parallel API failures) must not stack
    // additional redirects on top of the first one.
    ErrorHandler.handleSessionExpiry();
    ErrorHandler.handleSessionExpiry();

    var navCount = (globalThis._navigationLog || []).length;
    assert(navCount === 1,
      'parallel handleSessionExpiry calls trigger exactly one redirect (got ' + navCount + ')');
    assert(lastNavigation() === firstNav,
      'subsequent calls do not change the redirect destination');
  });

  await group('handleSessionExpiry skips redirect when already on /login', async function () {
    resetAll();
    globalThis._fakeLocation.pathname = '/login';
    sessionStorage.setItem('smartkcet_subscription', '{}');

    ErrorHandler.handleSessionExpiry();

    assert(sessionStorage.getItem('smartkcet_subscription') === null,
      'sessionStorage is still cleared even when on /login');
    assert(lastNavigation() === null,
      'no redirect is issued when the user is already on /login');
  });

  await group('Global fetch interceptor handles 401 on API calls (REQ 14.8)', async function () {
    resetAll();
    stubFetch(401);
    ErrorHandler.installFetchInterceptor();

    var response = await window.fetch('/api/subscription/status', { credentials: 'include' });

    assert(response && response.status === 401,
      'interceptor preserves the original 401 response for the caller');
    var dest = lastNavigation();
    assert(dest && dest.indexOf('/login') === 0,
      'interceptor redirects to /login after a 401 on /api/subscription/status');
    assert(dest && dest.indexOf('expired=1') !== -1,
      'interceptor adds expired=1 to the redirect URL');
  });

  await group('Interceptor handles 401 from any API endpoint (universal coverage)', async function () {
    var endpoints = [
      '/api/subscription/status',
      '/api/institution/dashboard',
      '/api/institution/students',
      '/api/exam/check-access',
    ];
    for (var i = 0; i < endpoints.length; i++) {
      resetAll();
      stubFetch(401);
      ErrorHandler.installFetchInterceptor();
      await window.fetch(endpoints[i], { credentials: 'include' });
      var dest = lastNavigation();
      assert(dest && dest.indexOf('/login') === 0,
        '401 on ' + endpoints[i] + ' triggers session-expiry redirect');
    }
  });

  await group('Interceptor preserves successful responses (no false positives)', async function () {
    resetAll();
    stubFetch(200);
    ErrorHandler.installFetchInterceptor();

    var response = await window.fetch('/api/subscription/status', { credentials: 'include' });

    assert(response && response.status === 200,
      'interceptor returns the successful response unchanged');
    assert(lastNavigation() === null,
      'no redirect on successful API responses');
  });

  await group('Interceptor ignores 401 from auth endpoints (login failures)', async function () {
    var authEndpoints = [
      '/api/auth/login',
      '/api/auth/admin/login',
      '/api/auth/register',
    ];
    for (var i = 0; i < authEndpoints.length; i++) {
      resetAll();
      stubFetch(401);
      ErrorHandler.installFetchInterceptor();
      var response = await window.fetch(authEndpoints[i], { method: 'POST' });
      assert(response && response.status === 401,
        '401 from ' + authEndpoints[i] + ' is preserved for the caller');
      assert(lastNavigation() === null,
        '401 from ' + authEndpoints[i] + ' does NOT trigger a session-expiry redirect');
    }
  });

  await group('Interceptor passes other error statuses through unchanged', async function () {
    var statuses = [400, 403, 404, 409, 500, 503];
    for (var i = 0; i < statuses.length; i++) {
      resetAll();
      stubFetch(statuses[i]);
      ErrorHandler.installFetchInterceptor();
      await window.fetch('/api/subscription/status', { credentials: 'include' });
      assert(lastNavigation() === null,
        'HTTP ' + statuses[i] + ' does NOT trigger a session-expiry redirect');
    }
  });

  await group('installFetchInterceptor is idempotent', async function () {
    resetAll();
    var calls = stubFetch(401);
    ErrorHandler.installFetchInterceptor();
    ErrorHandler.installFetchInterceptor();
    ErrorHandler.installFetchInterceptor();

    await window.fetch('/api/subscription/status');

    assert(calls.length === 1,
      'fetch is only wrapped once, even after multiple install calls');
  });

  await group('handleApiError 401 path delegates to handleSessionExpiry', async function () {
    resetAll();
    await ErrorHandler.handleApiError({ status: 401, message: 'HTTP 401' }, 'test');
    var dest = lastNavigation();
    assert(dest && dest.indexOf('/login') === 0,
      'handleApiError({status:401}) redirects to /login');
    assert(dest && dest.indexOf('expired=1') !== -1,
      'handleApiError 401 path includes expired=1 marker');
  });

  await group('Status message for 401 matches design (REQ 14.2)', function () {
    var msg = ErrorHandler.statusMessages[401];
    assert(typeof msg === 'string' && msg.toLowerCase().indexOf('session has expired') !== -1,
      '401 message says "session has expired" (got: ' + msg + ')');
  });

  // ── Summary ────────────────────────────────────────────────────────────

  console.log('\n──────────────────────────────');
  console.log('ErrorHandler tests: ' + passed + ' passed, ' + failed + ' failed');
  if (failed > 0) {
    console.log('Failures:');
    for (var i = 0; i < failures.length; i++) console.log('  - ' + failures[i]);
    if (typeof process !== 'undefined') process.exitCode = 1;
  }
})();
