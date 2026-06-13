// SmartKCET Prep — Router Module Tests
// Unit tests covering the role-based access control and 404 routing
// logic added in task 14.2. Runs under both Node (CI) and the browser
// (load this file after router.js in a test page).
//
// The router.js module relies on a few browser globals (`window`,
// `document`, `Auth`). The tests below stub those globals out so the
// module's pure logic can be exercised without a DOM.

(async function () {
  'use strict';

  // ── Stub the browser globals required by router.js ─────────────────────
  //
  // The stubs only need to provide the surface area router.js touches:
  //   - window.location (read pathname, write href)
  //   - window.history.length
  //   - window.addEventListener / document.addEventListener (no-op)
  //   - Auth.currentRole() returning a role-bearing user object

  if (typeof globalThis.window === 'undefined') {
    var navigationLog = [];
    var fakeLocation = {
      pathname: '/',
      search: '',
      _href: '/',
      get href() { return this._href; },
      set href(v) {
        this._href = v;
        navigationLog.push(v);
      },
    };
    globalThis.window = {
      location: fakeLocation,
      history: { length: 1 },
      addEventListener: function () {},
      removeEventListener: function () {},
    };
    globalThis.document = {
      title: '',
      addEventListener: function () {},
      removeEventListener: function () {},
    };
    globalThis._navigationLog = navigationLog;
  }

  // Stub Auth — individual tests override Auth.currentRole.
  globalThis.Auth = {
    currentRole: async function () { return null; },
  };

  // Now load the router under test. In Node we read the source and
  // eval it in the global scope so the top-level `var Router`
  // binding ends up on globalThis (mirroring browser script-tag
  // semantics). In the browser the script tag will already have set
  // up the global Router object before this file runs.
  if (typeof globalThis.Router === 'undefined') {
    if (typeof require === 'function') {
      var fs = require('fs');
      var path = require('path');
      var src = fs.readFileSync(path.join(__dirname, 'router.js'), 'utf8');
      // eslint-disable-next-line no-eval
      (0, eval)(src);
    } else {
      throw new Error('Router global is missing — load router.js first.');
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

  function resetNavigation() {
    if (globalThis._navigationLog) globalThis._navigationLog.length = 0;
  }
  function lastNavigation() {
    var log = globalThis._navigationLog || [];
    return log[log.length - 1] || null;
  }

  // ── Tests ──────────────────────────────────────────────────────────────

  await group('Route table and titles', function () {
    var routes = Router._routes;
    assert(routes['/dashboard'] && routes['/dashboard'].requiresAuth === true,
      '/dashboard route exists and requires auth');
    assert(routes['/subscription'] && routes['/subscription'].allowedRoles[0] === 'student',
      '/subscription is restricted to students');
    assert(routes['/institution/dashboard'] && routes['/institution/dashboard'].allowedRoles[0] === 'institution_admin',
      '/institution/dashboard is restricted to institution_admin');
    assert(routes['/admin/upload'] && routes['/admin/upload'].allowedRoles[0] === 'platform_admin',
      '/admin/upload is restricted to platform_admin');
    assert(routes['/not-found'] && routes['/not-found'].requiresAuth === false,
      '/not-found is public (REQ-15.9)');
  });

  await group('Unknown routes redirect to /not-found (REQ-15.9)', async function () {
    resetNavigation();
    await Router.navigate('/this/does/not/exist');
    var dest = lastNavigation();
    assert(dest && dest.indexOf('/not-found') === 0,
      'Unknown route navigates to the 404 page (got ' + dest + ')');
    assert(dest && dest.indexOf('path=') !== -1,
      '404 redirect preserves the original path as a query parameter');
  });

  await group('Unauthenticated access redirects to /login (REQ-15.5)', async function () {
    globalThis.Auth.currentRole = async function () { return null; };
    resetNavigation();
    await Router.navigate('/dashboard');
    var dest = lastNavigation();
    assert(dest && dest.indexOf('/login') === 0,
      'Unauthenticated /dashboard navigation redirects to /login');
    assert(dest && dest.indexOf('return=') !== -1,
      '/login redirect includes a return parameter');
    assert(dest && dest.indexOf(encodeURIComponent('/dashboard')) !== -1,
      'Return parameter encodes the original path');
  });

  await group('Role mismatch redirects to role home (REQ-15.6, 15.7, 15.8)', async function () {
    // Student trying to reach an institution route → /dashboard
    globalThis.Auth.currentRole = async function () { return { role: 'student' }; };
    resetNavigation();
    await Router.navigate('/institution/dashboard');
    assert(lastNavigation() === '/dashboard',
      'Student visiting /institution/dashboard is sent to /dashboard (REQ-15.7)');

    // Student trying to reach an admin route → /dashboard
    resetNavigation();
    await Router.navigate('/admin/upload');
    assert(lastNavigation() === '/dashboard',
      'Student visiting /admin/upload is sent to /dashboard (REQ-15.7)');

    // Institution admin trying to reach a student route → institution dashboard
    globalThis.Auth.currentRole = async function () { return { role: 'institution_admin' }; };
    resetNavigation();
    await Router.navigate('/dashboard');
    assert(lastNavigation() === '/institution/dashboard',
      'Institution admin visiting /dashboard is sent to /institution/dashboard (REQ-15.6)');

    resetNavigation();
    await Router.navigate('/admin/upload');
    assert(lastNavigation() === '/institution/dashboard',
      'Institution admin visiting /admin/upload is sent to /institution/dashboard (REQ-15.6)');

    // Platform admin trying to reach a student route → admin home
    globalThis.Auth.currentRole = async function () { return { role: 'platform_admin' }; };
    resetNavigation();
    await Router.navigate('/dashboard');
    assert(lastNavigation() === '/admin/upload',
      'Platform admin visiting /dashboard is sent to /admin/upload (REQ-15.8)');

    resetNavigation();
    await Router.navigate('/institution/dashboard');
    assert(lastNavigation() === '/admin/upload',
      'Platform admin visiting /institution/dashboard is sent to /admin/upload (REQ-15.8)');
  });

  await group('Allowed-role navigation goes through unchanged', async function () {
    globalThis.Auth.currentRole = async function () { return { role: 'student' }; };
    resetNavigation();
    await Router.navigate('/subscription');
    assert(lastNavigation() === '/subscription',
      'Student can navigate to /subscription (allowed role)');

    globalThis.Auth.currentRole = async function () { return { role: 'institution_admin' }; };
    resetNavigation();
    await Router.navigate('/institution/students');
    assert(lastNavigation() === '/institution/students',
      'Institution admin can navigate to /institution/students');

    globalThis.Auth.currentRole = async function () { return { role: 'platform_admin' }; };
    resetNavigation();
    await Router.navigate('/admin/analytics');
    assert(lastNavigation() === '/admin/analytics',
      'Platform admin can navigate to /admin/analytics');
  });

  await group('Legacy "admin" role alias resolves to platform_admin home', async function () {
    globalThis.Auth.currentRole = async function () { return { role: 'admin' }; };
    resetNavigation();
    await Router.navigate('/dashboard');
    assert(lastNavigation() === '/admin/upload',
      'Legacy admin role role-mismatch redirect points to /admin/upload');

    resetNavigation();
    await Router.navigate('/admin/upload');
    assert(lastNavigation() === '/admin/upload',
      'Legacy admin role can still access /admin/upload');
  });

  await group('redirectByRole resolves correctly for every role', async function () {
    resetNavigation();
    await Router.redirectByRole('student');
    assert(lastNavigation() === '/dashboard', 'redirectByRole(student) → /dashboard');

    resetNavigation();
    await Router.redirectByRole('institution_admin');
    assert(lastNavigation() === '/institution/dashboard',
      'redirectByRole(institution_admin) → /institution/dashboard');

    resetNavigation();
    await Router.redirectByRole('platform_admin');
    assert(lastNavigation() === '/admin/upload',
      'redirectByRole(platform_admin) → /admin/upload');

    resetNavigation();
    await Router.redirectByRole('admin');
    assert(lastNavigation() === '/admin/upload',
      'redirectByRole(admin) (legacy alias) → /admin/upload');

    resetNavigation();
    globalThis.Auth.currentRole = async function () { return null; };
    await Router.redirectByRole(null);
    assert(lastNavigation() === '/login',
      'redirectByRole(null) → /login');
  });

  await group('showNotFound preserves the requested path (REQ-15.9)', function () {
    resetNavigation();
    Router.showNotFound('/some/missing/page');
    var dest = lastNavigation();
    assert(dest && dest.indexOf('/not-found') === 0,
      'showNotFound navigates to /not-found');
    assert(dest && dest.indexOf(encodeURIComponent('/some/missing/page')) !== -1,
      'showNotFound encodes the requested path');
  });

  // ── Summary ────────────────────────────────────────────────────────────

  console.log('\n──────────────────────────────');
  console.log('Router tests: ' + passed + ' passed, ' + failed + ' failed');
  if (failed > 0) {
    console.log('Failures:');
    failures.forEach(function (m) { console.log('  - ' + m); });
    if (typeof process !== 'undefined' && process.exit) {
      process.exit(1);
    }
  }
})();
