// SmartKCET Prep — Subscription Selection Modal Component (4-Plan Version)
// Handles plan selection (Free, 7-Day Trial, Pro Monthly, Pro Yearly),
// Razorpay payment integration, activation API calls, error display,
// loading states, and keyboard focus trap for accessibility.
//
// Pairs with:
//   - frontend/html/subscription_modal.html (DOM structure, id="subscriptionModal")
//   - frontend/css/subscription-modal-premium.css (styling)
//   - frontend/js/subscription.js (Subscription module + SubscriptionAPI)
//
// Public API:
//   SubscriptionModal.init()
//   SubscriptionModal.show()
//   SubscriptionModal.hide()
//   SubscriptionModal.selectFree()
//   SubscriptionModal.selectTrial()
//   SubscriptionModal.selectMonthly()
//   SubscriptionModal.selectYearly()
//   SubscriptionModal.shouldShow(subscriptionData)

var SubscriptionModal = (function () {
  'use strict';

  // ── Constants ───────────────────────────────────────────────────────────

  var MODAL_ID = 'subscriptionModal';
  var ERROR_ID = 'modalError';
  var ERROR_MESSAGE_ID = 'errorMessage';
  var LOADING_ID = 'modalLoading';

  // Statuses where the user effectively has no usable subscription and the
  // modal SHOULD be shown when they try to start an exam.
  var INACTIVE_STATUSES = {
    expired: true,
    cancelled: true,
  };

  // ── Internal state ──────────────────────────────────────────────────────

  var _modalEl = null;             // root #subscriptionModal element
  var _initialized = false;        // guards against double-binding listeners
  var _isOpen = false;             // whether the modal is currently visible
  var _isBusy = false;             // an activation request is in flight
  var _previouslyFocused = null;   // element to restore focus to on close
  var _lastAction = null;          // { type, planId }
  var _plans = [];                 // Available plans from API
  var _razorpayKeyId = '';         // Razorpay key ID

  // Bound event handler references (so we can remove them on hide / destroy)
  var _onKeyDown = null;
  var _onOverlayClick = null;

  // ── Helpers ─────────────────────────────────────────────────────────────

  function _qs(selector, root) {
    return (root || _modalEl || document).querySelector(selector);
  }

  function _qsa(selector, root) {
    return Array.prototype.slice.call(
      (root || _modalEl || document).querySelectorAll(selector)
    );
  }

  /**
   * Locate the modal element in the DOM. Returns null if the modal HTML
   * has not been included on the current page.
   */
  function _findModal() {
    if (_modalEl && document.body.contains(_modalEl)) return _modalEl;
    _modalEl = document.getElementById(MODAL_ID);
    return _modalEl;
  }

  /**
   * Map an HTTP status code / API error result onto a friendly user-facing message.
   */
  function _formatActivationError(result) {
    if (!result) return 'Something went wrong. Please try again.';
    // Prefer the server-provided error string when available.
    if (result.data && (result.data.error || result.data.message)) {
      return result.data.error || result.data.message;
    }
    switch (result.status) {
      case 400:
        return 'Invalid request. Please check your selection and try again.';
      case 401:
        return 'Your session has expired. Please log in again.';
      case 402:
      case 'payment_failed':
        return 'Payment failed. Please try a different payment method.';
      case 403:
        return 'You are not allowed to activate this plan.';
      case 409:
        return 'You already have an active subscription.';
      case 500:
      case 502:
      case 503:
        return 'Service temporarily unavailable. Please try again in a moment.';
      case 0:
        return 'Network error. Please check your connection and try again.';
      default:
        return result.error || 'Activation failed. Please try again.';
    }
  }

  // ── Loading / error / success display ───────────────────────────────────

  /**
   * Toggle loading state on plan-selection buttons.
   */
  function _setLoading(isLoading) {
    if (!_modalEl) return;

    var buttons = _qsa('[data-action^="select-"]');
    var closeBtn = _qs('.modal-close');
    var loadingEl = _qs('#' + LOADING_ID);

    buttons.forEach(function (btn) {
      if (!btn) return;
      btn.disabled = !!isLoading;
      btn.classList.toggle('is-loading', !!isLoading);
      btn.setAttribute('aria-busy', isLoading ? 'true' : 'false');
      
      // Visual feedback - add opacity
      btn.style.opacity = isLoading ? '0.5' : '1';
      btn.style.cursor = isLoading ? 'not-allowed' : 'pointer';
    });

    if (closeBtn) {
      closeBtn.disabled = !!isLoading;
      closeBtn.style.opacity = isLoading ? '0.5' : '1';
    }
    
    if (loadingEl) loadingEl.style.display = isLoading ? '' : 'none';
    
    console.log('[modal] Loading state:', isLoading ? 'ENABLED' : 'DISABLED');
  }

  /**
   * Show an error message inside the modal.
   */
  function _showError(message) {
    if (!_modalEl) return;
    var errorEl = _qs('#' + ERROR_ID);
    var messageEl = _qs('#' + ERROR_MESSAGE_ID);
    var retryBtn = _qs('.btn-retry', errorEl || _modalEl);

    if (messageEl) messageEl.textContent = message || '';
    if (errorEl) {
      errorEl.style.display = '';
      errorEl.classList.add('active');
    }
    if (retryBtn) {
      retryBtn.style.display = _lastAction ? '' : 'none';
    }
  }

  function _clearError() {
    if (!_modalEl) return;
    var errorEl = _qs('#' + ERROR_ID);
    var messageEl = _qs('#' + ERROR_MESSAGE_ID);
    if (messageEl) messageEl.textContent = '';
    if (errorEl) {
      errorEl.style.display = 'none';
      errorEl.classList.remove('active');
    }
  }

  /**
   * Close the modal and redirect to dashboard after successful subscription activation.
   * Check if we're on the login page with a pending login response.
   */
  function _onActivationSuccess(successMessage) {
    _lastAction = null;
    _clearError();

    if (successMessage && typeof window !== 'undefined' && window.ErrorHandler) {
      try {
        if (typeof window.ErrorHandler.setFlashSuccess === 'function') {
          window.ErrorHandler.setFlashSuccess(successMessage);
        }
        window.ErrorHandler.showSuccess(successMessage);
      } catch (e) { /* best-effort */ }
    }

    hide();
    
    // After successful subscription activation, redirect to dashboard
    setTimeout(function () {
      try {
        // Check if we have a pending login response from the login page
        var loginResponse = sessionStorage.getItem('_loginResponse');
        if (loginResponse) {
          var data = JSON.parse(loginResponse);
          sessionStorage.removeItem('_loginResponse');
          
          // Determine correct redirect URL
          var redirectUrl = data.redirect || '/dashboard';
          if (data.student_subtype === 'institution_linked') {
            redirectUrl = '/student/institution/dashboard';
          }
          
          console.log('[modal] Redirecting to:', redirectUrl);
          window.location.href = redirectUrl;
        } else {
          // Not on login page, just reload
          window.location.reload();
        }
      } catch (e) {
        console.error('[modal] Redirect error:', e);
        window.location.href = '/dashboard';
      }
    }, 50);
  }

  // ── Focus trap ──────────────────────────────────────────────────────────

  /**
   * Return all currently-focusable elements within the modal in document order.
   */
  function _getFocusableElements() {
    if (!_modalEl) return [];
    if (typeof window !== 'undefined' && window.FocusTrap &&
        typeof window.FocusTrap._getFocusable === 'function') {
      return window.FocusTrap._getFocusable(_modalEl);
    }
    var selector = [
      'a[href]',
      'area[href]',
      'button:not([disabled])',
      'input:not([disabled]):not([type="hidden"])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    return _qsa(selector).filter(function (el) {
      if (el.hasAttribute('disabled')) return false;
      if (el.getAttribute('aria-hidden') === 'true') return false;
      if (el.offsetParent === null && el !== document.activeElement) {
        var style = window.getComputedStyle ? window.getComputedStyle(el) : null;
        if (!style || style.visibility === 'hidden' || style.display === 'none') {
          return false;
        }
      }
      return true;
    });
  }

  /**
   * Trap Tab / Shift+Tab cycling within the modal and close on Escape.
   */
  function _handleKeyDown(evt) {
    if (!_isOpen || !_modalEl) return;

    if (evt.key === 'Escape' || evt.keyCode === 27) {
      evt.preventDefault();
      if (!_isBusy) hide();
      return;
    }

    if (evt.key !== 'Tab' && evt.keyCode !== 9) return;

    var focusable = _getFocusableElements();
    if (focusable.length === 0) {
      evt.preventDefault();
      _modalEl.focus();
      return;
    }

    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    var active = document.activeElement;

    if (evt.shiftKey) {
      if (active === first || !_modalEl.contains(active)) {
        evt.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !_modalEl.contains(active)) {
        evt.preventDefault();
        first.focus();
      }
    }
  }

  /**
   * Close on overlay click (clicks outside the dialog).
   */
  function _handleOverlayClick(evt) {
    if (!_modalEl) return;
    if (evt.target === _modalEl) {
      if (!_isBusy) hide();
    }
  }

  // ── Razorpay payment flow ───────────────────────────────────────────────

  /**
   * Initiate Razorpay payment for a paid plan.
   */
  async function _initiatePayment(plan) {
    // Guard: prevent duplicate calls
    if (_isBusy) {
      console.log('[payment] Already processing payment, ignoring duplicate request');
      return;
    }
    
    console.log('[payment] create-order called for plan:', plan.name, plan.id);
    
    _isBusy = true;
    _lastAction = { type: 'payment', planId: plan.id };
    _clearError();
    _setLoading(true);

    try {
      // Create Razorpay order
      var payload = { plan_id: plan.id };
      console.log('[payment] ========== CREATE ORDER REQUEST ==========');
      console.log('[payment] Request URL: /api/payments/create-order');
      console.log('[payment] Request Method: POST');
      console.log('[payment] Request Payload:', JSON.stringify(payload, null, 2));
      console.log('[payment] Plan details:', JSON.stringify({
        id: plan.id,
        name: plan.name,
        price: plan.price,
        billing_period: plan.billing_period
      }, null, 2));
      
      var createRes = await fetch('/api/payments/create-order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      console.log('[payment] Response Status:', createRes.status, createRes.statusText);
      
      var createData = await createRes.json();
      
      console.log('[payment] ========== CREATE ORDER RESPONSE ==========');
      console.log('[payment] Response Body:', JSON.stringify(createData, null, 2));

      if (!createRes.ok) {
        console.error('[payment] ========== CREATE ORDER FAILED ==========');
        console.error('[payment] Status Code:', createRes.status);
        console.error('[payment] FULL ERROR RESPONSE:', JSON.stringify(createData, null, 2));
        console.error('[payment] Error detail:', createData.detail);
        console.error('[payment] Error message:', createData.message);
        console.error('[payment] ==============================================');
        
        _showError(createData.message || createData.detail?.message || 'Failed to create payment order.');
        _setLoading(false);
        _isBusy = false;  // Reset busy flag on error
        return;
      }
      
      console.log('[payment] create-order success, order_id:', createData.order_id);

      // Handle mock payment (dev mode)
      if (createData._mock) {
        console.log('[payment] Mock payment mode detected');
        _showError('⚙️ Dev mode — simulating payment success…');
        await fetch('/api/payments/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            razorpay_order_id: createData.order_id,
            razorpay_payment_id: 'pay_mock_' + Date.now(),
            razorpay_signature: 'mock_sig',
            plan_id: plan.id,
          }),
        });
        setTimeout(function () {
          _onActivationSuccess('✅ Payment successful! Your plan is now active.');
        }, 1500);
        return;
      }

      // Launch Razorpay checkout
      _setLoading(false);
      _isBusy = false;  // Allow Razorpay popup interaction
      
      console.log('[payment] Opening Razorpay checkout...');
      var razorpayOptions = {
        key: createData.key_id || _razorpayKeyId,
        amount: createData.amount,
        currency: createData.currency || 'INR',
        order_id: createData.order_id,
        name: 'SmartKCET Prep',
        description: createData.description || plan.name,
        prefill: createData.prefill || {},
        theme: { color: '#a78bfa' },
        handler: async function (response) {
          _isBusy = true;  // Re-enable busy flag during verification
          _setLoading(true);
          console.log('[payment] Payment successful, verifying...');
          try {
            var verifyRes = await fetch('/api/payments/verify', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              credentials: 'include',
              body: JSON.stringify({
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
                plan_id: plan.id,
              }),
            });

            var verifyData = await verifyRes.json();

            if (verifyRes.ok && verifyData.verified) {
              _onActivationSuccess('✅ Payment successful! Your plan is now active.');
            } else {
              _showError('⚠️ Verification failed. Contact support. Order: ' + response.razorpay_order_id);
              _setLoading(false);
            }
          } catch (err) {
            _showError('Network error during verification. Please contact support.');
            _setLoading(false);
          }
        },
        modal: {
          ondismiss: function () {
            console.log('[payment] Razorpay popup dismissed');
            _setLoading(false);
            _isBusy = false;  // Reset busy flag when user cancels
          },
        },
      };

      if (typeof window.Razorpay === 'undefined') {
        var script = document.createElement('script');
        script.src = 'https://checkout.razorpay.com/v1/checkout.js';
        script.onload = function () {
          new window.Razorpay(razorpayOptions).open();
        };
        script.onerror = function () {
          _showError('Failed to load payment gateway.');
          _setLoading(false);
          _isBusy = false;  // Reset busy flag on script load error
        };
        document.head.appendChild(script);
      } else {
        new window.Razorpay(razorpayOptions).open();
      }
    } catch (err) {
      console.error('[payment] Error during payment initiation:', err);
      _showError('Network error. Please try again.');
      _setLoading(false);
      _isBusy = false;  // Reset busy flag on error
    }
  }

  // ── Plan selection handlers ─────────────────────────────────────────────

  /**
   * Activate Free plan (instant activation, no payment).
   * Allowed only when user has no active subscription (new user or
   * expired/cancelled). Blocked with a friendly message otherwise.
   */
  async function selectFree() {
    if (_isBusy) return;
    _isBusy = true;
    _lastAction = { type: 'free' };
    _clearError();
    _setLoading(true);

    console.log('[free-plan] activating free plan');

    // Log current subscription state for debugging
    if (typeof Subscription !== 'undefined' && Subscription.getStatus) {
      try {
        var currentSub = await Subscription.getStatus();
        console.log('[free-plan] current subscription:', currentSub);
      } catch (e) { /* non-fatal */ }
    }

    try {
      var res = await fetch('/api/subscription/activate-free', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });

      var data = await res.json();
      console.log('[free-plan] response:', data);

      if (res.ok) {
        // SubscriptionResponse has a top-level `status` field ('active', etc.)
        _isBusy = false;
        _setLoading(false);
        _onActivationSuccess('✅ Free plan activated! Redirecting to dashboard...');
        return;
      }

      // 400 with subscription_active → user already has an active plan
      if (res.status === 400) {
        var msg = (data && data.detail && data.detail.message)
          || (data && data.message)
          || 'Current subscription active. Free plan available after expiry.';
        _setLoading(false);
        _isBusy = false;
        _showError(msg);
        return;
      }

      _setLoading(false);
      _isBusy = false;
      _showError(
        (data && data.detail && data.detail.message)
        || (data && data.message)
        || 'Failed to activate free plan. Please try again.'
      );
    } catch (err) {
      _setLoading(false);
      _isBusy = false;
      _showError('Network error. Please check your connection and try again.');
      console.error('[free-plan] Free plan activation error:', err);
    }
  }

  /**
   * Activate 7-Day Premium Trial (₹99 via Razorpay).
   */
  async function selectTrial() {
    var plan = _plans.find(function (p) { return p.name === '7-Day Premium Trial'; });
    if (!plan) {
      _showError('7-Day Trial plan not found. Please refresh and try again.');
      return;
    }
    await _initiatePayment(plan);
  }

  /**
   * Activate Pro Monthly (₹349/month via Razorpay).
   */
  async function selectMonthly() {
    var plan = _plans.find(function (p) { return p.name === 'Pro Monthly'; });
    if (!plan) {
      _showError('Pro Monthly plan not found. Please refresh and try again.');
      return;
    }
    await _initiatePayment(plan);
  }

  /**
   * Activate Pro Yearly (₹2999/year via Razorpay).
   */
  async function selectYearly() {
    var plan = _plans.find(function (p) { return p.name === 'Pro Yearly'; });
    if (!plan) {
      _showError('Pro Yearly plan not found. Please refresh and try again.');
      return;
    }
    await _initiatePayment(plan);
  }

  // ── Event wiring ────────────────────────────────────────────────────────

  // Store handler references to prevent duplicate listeners
  var _handlers = {
    close: null,
    free: null,
    trial: null,
    monthly: null,
    yearly: null,
    retry: null
  };

  function _bindListeners() {
    if (!_modalEl) return;
    
    // If already initialized, remove old listeners first to prevent duplicates
    if (_initialized) {
      // Remove old handlers if they exist
      Object.keys(_handlers).forEach(function(key) {
        if (_handlers[key]) {
          console.log('[modal] Cleanup: Removing old ' + key + ' handler');
          // This will be handled when we re-attach
        }
      });
      // Don't return early - rebind the listeners
    }

    // Close button
    var closeBtn = _qs('.modal-close');
    if (closeBtn && closeBtn !== _handlers._oldCloseBtn) {
      if (_handlers.close && _handlers._oldCloseBtn) {
        _handlers._oldCloseBtn.removeEventListener('click', _handlers.close);
      }
      _handlers.close = function (evt) {
        evt.preventDefault();
        if (!_isBusy) hide();
      };
      closeBtn.addEventListener('click', _handlers.close);
      _handlers._oldCloseBtn = closeBtn;
    }

    // Free plan button
    var freeBtn = _qs('[data-action="select-free"]');
    if (freeBtn && freeBtn !== _handlers._oldFreeBtn) {
      if (_handlers.free && _handlers._oldFreeBtn) {
        _handlers._oldFreeBtn.removeEventListener('click', _handlers.free);
      }
      _handlers.free = function (evt) {
        evt.preventDefault();
        if (_isBusy) {
          console.log('[modal] Button click ignored - already processing');
          return;
        }
        console.log('[modal] Free plan button clicked');
        selectFree();
      };
      freeBtn.addEventListener('click', _handlers.free);
      _handlers._oldFreeBtn = freeBtn;
    }

    // 7-Day Trial button
    var trialBtn = _qs('[data-action="select-trial"]');
    if (trialBtn && trialBtn !== _handlers._oldTrialBtn) {
      if (_handlers.trial && _handlers._oldTrialBtn) {
        _handlers._oldTrialBtn.removeEventListener('click', _handlers.trial);
      }
      _handlers.trial = function (evt) {
        evt.preventDefault();
        if (_isBusy) {
          console.log('[modal] Button click ignored - already processing');
          return;
        }
        console.log('[modal] Trial button clicked');
        selectTrial();
      };
      trialBtn.addEventListener('click', _handlers.trial);
      _handlers._oldTrialBtn = trialBtn;
    }

    // Pro Monthly button
    var monthlyBtn = _qs('[data-action="select-monthly"]');
    if (monthlyBtn && monthlyBtn !== _handlers._oldMonthlyBtn) {
      if (_handlers.monthly && _handlers._oldMonthlyBtn) {
        _handlers._oldMonthlyBtn.removeEventListener('click', _handlers.monthly);
      }
      _handlers.monthly = function (evt) {
        evt.preventDefault();
        if (_isBusy) {
          console.log('[modal] Button click ignored - already processing');
          return;
        }
        console.log('[modal] Monthly button clicked');
        selectMonthly();
      };
      monthlyBtn.addEventListener('click', _handlers.monthly);
      _handlers._oldMonthlyBtn = monthlyBtn;
    }

    // Pro Yearly button
    var yearlyBtn = _qs('[data-action="select-yearly"]');
    if (yearlyBtn && yearlyBtn !== _handlers._oldYearlyBtn) {
      if (_handlers.yearly && _handlers._oldYearlyBtn) {
        _handlers._oldYearlyBtn.removeEventListener('click', _handlers.yearly);
      }
      _handlers.yearly = function (evt) {
        evt.preventDefault();
        if (_isBusy) {
          console.log('[modal] Button click ignored - already processing');
          return;
        }
        console.log('[modal] Yearly button clicked');
        selectYearly();
      };
      yearlyBtn.addEventListener('click', _handlers.yearly);
      _handlers._oldYearlyBtn = yearlyBtn;
    }

    // Retry button inside the error block
    var retryBtn = _qs('.btn-retry');
    if (retryBtn && retryBtn !== _handlers._oldRetryBtn) {
      if (_handlers.retry && _handlers._oldRetryBtn) {
        _handlers._oldRetryBtn.removeEventListener('click', _handlers.retry);
      }
      _handlers.retry = function (evt) {
        evt.preventDefault();
        if (_isBusy) {
          console.log('[modal] Retry ignored - already processing');
          return;
        }
        if (!_lastAction) return;
        
        console.log('[modal] Retry button clicked, lastAction:', _lastAction.type);
        
        switch (_lastAction.type) {
          case 'free':
            selectFree();
            break;
          case 'payment':
            var plan = _plans.find(function (p) { return p.id === _lastAction.planId; });
            if (plan) _initiatePayment(plan);
            break;
        }
      };
      retryBtn.addEventListener('click', _handlers.retry);
      _handlers._oldRetryBtn = retryBtn;
    }

    if (!_initialized) {
      _initialized = true;
      console.log('[modal] Event listeners bound successfully (first time)');
    } else {
      console.log('[modal] Event listeners re-bound for updated DOM');
    }
  }

  // ── Initialize (load plans from API) ───────────────────────────────────

  /**
   * Load available plans from the backend API.
   * Call this once when the page loads, before showing the modal.
   */
  async function init() {
    try {
      // Fetch subscription plans
      var res = await fetch('/api/payments/plans/student', {
        method: 'GET',
        credentials: 'include',
      });

      var data = await res.json();

      if (res.ok && data.plans) {
        _plans = data.plans;
        _razorpayKeyId = data.key_id || '';

        // Update plan buttons with plan IDs
        var trialBtn = _qs('[data-action="select-trial"]');
        var monthlyBtn = _qs('[data-action="select-monthly"]');
        var yearlyBtn = _qs('[data-action="select-yearly"]');

        var trialPlan = _plans.find(function (p) { return p.name === '7-Day Premium Trial'; });
        var monthlyPlan = _plans.find(function (p) { return p.name === 'Pro Monthly'; });
        var yearlyPlan = _plans.find(function (p) { return p.name === 'Pro Yearly'; });

        if (trialBtn && trialPlan) trialBtn.setAttribute('data-plan-id', trialPlan.id);
        if (monthlyBtn && monthlyPlan) monthlyBtn.setAttribute('data-plan-id', monthlyPlan.id);
        if (yearlyBtn && yearlyPlan) yearlyBtn.setAttribute('data-plan-id', yearlyPlan.id);
      }

      // Check user's current subscription status
      try {
        var statusRes = await fetch('/api/subscription/user/subscription-status', {
          method: 'GET',
          credentials: 'include',
        });

        console.log('[subscription-modal] Subscription status response status:', statusRes.status);
        
        if (statusRes.ok) {
          var statusData = await statusRes.json();
          console.log('[subscription-modal] Subscription status data:', statusData);
          
          // CHANGE 1: Split Conditional Logic - has_active_subscription is the source of truth
          // Plan name can be null even when subscription is active
          if (statusData.has_active_subscription) {
            // CHANGE 2 & 3: Add null-safety for plan name display and tooltip generation
            var daysRemaining = statusData.days_remaining || 'unknown';
            var currentPlan = statusData.current_plan_name || 'your current plan';
            
            // Handle null plan_name case for tooltip
            var tooltipText;
            if (statusData.current_plan_name) {
              tooltipText = 'Can be upgraded after ' + currentPlan + ' expires in ' + daysRemaining + ' days';
            } else {
              tooltipText = 'Plan information unavailable. Please upgrade after plan expires.';
            }
            
            console.log('[subscription-modal] Has active subscription:', statusData.current_plan_name || '(plan name missing)');
            
            var freeBtn = _qs('[data-action="select-free"]');
            var trialBtn = _qs('[data-action="select-trial"]');
            var monthlyBtn = _qs('[data-action="select-monthly"]');
            var yearlyBtn = _qs('[data-action="select-yearly"]');
            
            console.log('[subscription-modal] Button elements found:', {
              free: !!freeBtn,
              trial: !!trialBtn,
              monthly: !!monthlyBtn,
              yearly: !!yearlyBtn
            });
            
            // CHANGE 4: Update Button Disabling Logic - handle null plan_name case
            var buttonsToDisable = [];
            
            if (statusData.current_plan_name === null || statusData.current_plan_name === '') {
              // Null plan name: disable all paid plans (user has active subscription but name missing)
              buttonsToDisable = [trialBtn, monthlyBtn, yearlyBtn];
              console.log('[subscription-modal] Active subscription with missing plan name - disabling paid plans');
              // CHANGE 6 part A: Add debug logging for null plan case
              console.log('[subscription-modal] Plan name missing but subscription active - using fallback display');
            } else if (currentPlan === 'Free') {
              // If on Free: enable all 3 paid buttons
              buttonsToDisable = [];
              console.log('[subscription-modal] Current plan: Free - all paid buttons enabled');
            } else if (currentPlan.includes('7-Day')) {
              // If on Trial: disable Free, Monthly, Yearly
              buttonsToDisable = [freeBtn, monthlyBtn, yearlyBtn];
              console.log('[subscription-modal] Current plan: 7-Day Trial - disabling Free, Monthly, Yearly');
            } else if (currentPlan.includes('Monthly')) {
              // If on Pro Monthly: disable Free, Trial, Yearly
              buttonsToDisable = [freeBtn, trialBtn, yearlyBtn];
              console.log('[subscription-modal] Current plan: Pro Monthly - disabling Free, Trial, Yearly');
            } else if (currentPlan.includes('Yearly')) {
              // If on Pro Yearly: disable Free, Trial, Monthly
              buttonsToDisable = [freeBtn, trialBtn, monthlyBtn];
              console.log('[subscription-modal] Current plan: Pro Yearly - disabling Free, Trial, Monthly');
            }
            
            console.log('[subscription-modal] Buttons to disable count:', buttonsToDisable.length);
            
            // Apply disabled state to all buttons in buttonsToDisable list
            buttonsToDisable.forEach(function (btn, idx) {
              if (!btn) {
                console.warn('[subscription-modal] Button at index ' + idx + ' is null/undefined');
                return;
              }
              console.log('[subscription-modal] Disabling button:', btn.getAttribute('data-action'));
              btn.disabled = true;
              btn.classList.add('disabled');
              btn.setAttribute('title', tooltipText);
              btn.setAttribute('aria-disabled', 'true');
              
              // Add visual disabled state
              btn.style.opacity = '0.5';
              btn.style.cursor = 'not-allowed';
              btn.style.pointerEvents = 'none';
            });
            
            console.log('[subscription-modal] Applied subscription-based button restrictions');
          } else {
            // CHANGE 5: Update console logging - change message to be more precise
            console.log('[subscription-modal] No active subscription detected');
            console.log('[subscription-modal] has_active_subscription:', statusData.has_active_subscription);
            console.log('[subscription-modal] current_plan_name:', statusData.current_plan_name);
          }
        } else {
          console.warn('[subscription-modal] Subscription status request failed with status:', statusRes.status);
        }
      } catch (err) {
        console.warn('[subscription-modal] Could not check subscription status:', err);
        // Non-fatal - continue anyway
      }
    } catch (err) {
      console.error('Failed to load plans:', err);
    }
  }

  // ── Public API ──────────────────────────────────────────────────────────

  /**
   * Reveal the modal and set up focus trap.
   */
  function show() {
    var modal = _findModal();
    if (!modal) {
      console.warn('SubscriptionModal: #' + MODAL_ID + ' not found in DOM.');
      return;
    }
    if (_isOpen) return;

    // Initialize modal data (fetch plans and subscription status) if not already initialized
    if (!_initialized) {
      console.log('[subscription-modal] First time showing modal - initializing...');
      init();  // This is async but we don't wait for it - data will populate as it arrives
    }

    // Always rebind listeners when showing modal (ensures buttons are clickable)
    _bindListeners();
    _clearError();
    _setLoading(false);

    _previouslyFocused = document.activeElement;

    modal.style.display = 'flex';
    modal.classList.add('open');
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');

    document.body.classList.add('modal-open');

    _isOpen = true;

    var usedSharedTrap = false;
    if (typeof window !== 'undefined' && window.FocusTrap) {
      try {
        window.FocusTrap.activate(modal, {
          onEscape: function () { if (!_isBusy) hide(); },
        });
        usedSharedTrap = true;
      } catch (e) {
        usedSharedTrap = false;
      }
    }

    if (!usedSharedTrap && !_onKeyDown) {
      _onKeyDown = _handleKeyDown;
      document.addEventListener('keydown', _onKeyDown);
    }
    if (!_onOverlayClick) {
      _onOverlayClick = _handleOverlayClick;
      modal.addEventListener('click', _onOverlayClick);
    }

    if (!usedSharedTrap) {
      setTimeout(function () {
        var focusable = _getFocusableElements();
        var target = focusable[0] || modal;
        try {
          target.focus({ preventScroll: true });
        } catch (e) {
          target.focus();
        }
      }, 0);
    }
  }

  /**
   * Hide the modal and restore focus.
   */
  function hide() {
    var modal = _findModal();
    if (!modal || !_isOpen) {
      if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
      }
      return;
    }

    modal.classList.remove('open');
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');

    document.body.classList.remove('modal-open');

    if (typeof window !== 'undefined' && window.FocusTrap) {
      try { window.FocusTrap.deactivate(modal); } catch (e) { /* noop */ }
    }

    if (_onKeyDown) {
      document.removeEventListener('keydown', _onKeyDown);
      _onKeyDown = null;
    }
    if (_onOverlayClick) {
      modal.removeEventListener('click', _onOverlayClick);
      _onOverlayClick = null;
    }

    _isOpen = false;
    _setLoading(false);

    if (_previouslyFocused && typeof _previouslyFocused.focus === 'function') {
      try {
        _previouslyFocused.focus({ preventScroll: true });
      } catch (e) {
        try { _previouslyFocused.focus(); } catch (_) { /* noop */ }
      }
    }
    _previouslyFocused = null;
  }

  /**
   * Determine whether the modal should be shown for a given subscription payload.
   * Returns true when user has no usable access (should prompt for plan).
   * Returns false when user has access (trial/active/grace/institution).
   */
  function shouldShow(subscriptionData) {
    if (!subscriptionData) return true;

    if (typeof subscriptionData.is_active === 'boolean') {
      return !subscriptionData.is_active;
    }

    var status = subscriptionData.status;
    if (!status) return true;
    if (INACTIVE_STATUSES[status]) return true;
    return false;
  }

  // ── Auto-init ──────────────────────────────────────────────────────────

  function _autoInit() {
    if (_findModal()) {
      _bindListeners();
      init(); // Load plans from API
    }
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', _autoInit);
    } else {
      _autoInit();
    }
  }

  // ── Expose public interface ─────────────────────────────────────────────

  return {
    init: init,
    show: show,
    hide: hide,
    selectFree: selectFree,
    selectTrial: selectTrial,
    selectMonthly: selectMonthly,
    selectYearly: selectYearly,
    shouldShow: shouldShow,
  };
})();

// CommonJS export for unit tests (no-op in browsers).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = SubscriptionModal;
}
