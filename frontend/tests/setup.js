/**
 * Test Setup for Subscription Modal Tests
 * 
 * This file prepares the test environment by:
 * 1. Setting up jsdom for DOM operations
 * 2. Loading the subscription-modal.js module
 * 3. Making it available to test specs
 */

const { JSDOM } = require('jsdom');
const path = require('path');
const fs = require('fs');

// Create a jsdom instance
const html = `
  <!DOCTYPE html>
  <html>
    <head>
      <title>Subscription Modal Tests</title>
    </head>
    <body>
    </body>
  </html>
`;

const dom = new JSDOM(html, {
  url: 'http://localhost',
  pretendToBeVisual: true,
  resources: 'usable'
});

// Set up globals from jsdom
global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;
global.localStorage = dom.window.localStorage;
global.sessionStorage = dom.window.sessionStorage;

// Load subscription-modal.js into jsdom context
try {
  const subscriptionModalPath = path.join(__dirname, '../js/subscription-modal.js');
  let code = fs.readFileSync(subscriptionModalPath, 'utf8');
  
  // Execute code in jsdom window context using a Function constructor
  // This ensures the code runs in the window scope
  const func = new dom.window.Function(code);
  func.call(dom.window);
  
  // Check if SubscriptionModal is now available
  if (dom.window.SubscriptionModal) {
    global.SubscriptionModal = dom.window.SubscriptionModal;
    global.window.SubscriptionModal = dom.window.SubscriptionModal;
    console.log('[Setup] ✓ SubscriptionModal loaded successfully');
    console.log('[Setup] ✓ Module has methods:', Object.keys(dom.window.SubscriptionModal).join(', '));
  } else {
    console.warn('[Setup] ⚠ SubscriptionModal not found after code execution');
    console.warn('[Setup] Available globals:', Object.keys(dom.window).filter(k => k[0] !== k[0].toLowerCase()).slice(0, 5));
  }
  
  console.log('[Setup] ✓ jsdom environment ready');
} catch (err) {
  console.error('[Setup] ✗ Error during setup:', err.message);
}
