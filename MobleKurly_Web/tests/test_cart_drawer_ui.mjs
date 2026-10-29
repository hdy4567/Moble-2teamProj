import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../static/js/cart-drawer.js', import.meta.url), 'utf8');
function setup({missingForm = false} = {}) {
  const nodes = new Map();
  const documentHandlers = new Map();
  const requests = [];
  const dispatched = [];
  let document;
  function node(id) {
    const handlers = new Map();
    const item = {id, handlers, dataset:{}, attributes:{}, hidden:false, disabled:false,
      isConnected:true, textContent:'', insideDrawer:true,
      addEventListener(type, callback) { handlers.set(type, callback); },
      setAttribute(key, value) { this.attributes[key] = value; },
      focus() { document.activeElement = this; },
      closest() { return null; },
      getClientRects() { return [{}]; },
      click(event = {}) { handlers.get('click')?.({target:this, preventDefault(){}, ...event}); },
    };
    nodes.set('#' + id, item);
    return item;
  }
  for (const id of ['cart-drawer', 'order-form', 'cart-checkout', 'cart-drawer-message',
    'cart-drawer-status', 'cart-drawer-retry', 'cart-drawer-count', 'cart-drawer-total',
    'cart-drawer-empty', 'cart-clear', 'cart-continue', 'order-button',
    'floating-cart', 'floating-cart-count', 'floating-cart-total']) node(id);
  const trigger = node('trigger'); trigger.insideDrawer = false;
  const close = node('close');
  const keep = node('keep');
  const label = node('checkout-label');
  const drawer = nodes.get('#cart-drawer');
  drawer.open = false;
  drawer.hidden = true;
  drawer.contains = item => Boolean(item?.insideDrawer);
  drawer.querySelectorAll = selector => selector === '[data-cart-close]'
    ? [close, nodes.get('#cart-continue'), keep] : [close, nodes.get('#cart-checkout'), keep];
  drawer.getBoundingClientRect = () => ({left:600, top:0, right:1000, bottom:800});
  nodes.get('#cart-checkout').querySelector = () => label;
  nodes.get('#order-form').requestSubmit = button => requests.push(button);
  document = {
    activeElement: trigger,
    querySelector(selector) {
      if (selector === 'dialog[open]') return drawer.open ? drawer : null;
      if (missingForm && selector === '#order-form') return null;
      return nodes.get(selector) || null;
    },
    querySelectorAll: () => [trigger],
    addEventListener(type, callback) { documentHandlers.set(type, callback); },
    dispatchEvent(event) { dispatched.push(event.type); documentHandlers.get(event.type)?.(event); },
  };
  const window = {};
  vm.runInNewContext(source, {document, window, Intl, CustomEvent:class {constructor(type){this.type=type;}}});
  return {api:window.MobleCartDrawer, nodes, drawer, trigger, close, document, documentHandlers, requests, dispatched, label};
}

test('Non-shopping pages keep the ordinary navigation fallback', () => {
  assert.equal(setup({missingForm:true}).api, undefined);
});
test('Open is non-modal, retains page focus and refreshes without submitting', () => {
  const ui = setup();
  ui.trigger.click();
  assert.equal(ui.drawer.open, true);
  assert.equal(ui.drawer.hidden, false);
  assert.equal(ui.document.activeElement, ui.trigger);
  assert.equal(ui.trigger.attributes['aria-expanded'], 'true');
  assert.deepEqual(ui.dispatched, ['moble:cart-refresh']);
  assert.equal(ui.api.open(ui.trigger), false);
  assert.equal(ui.requests.length, 0);
});
test('Empty state and totals use the existing exact formatted cart value', () => {
  const ui = setup();
  ui.api.sync({count:0, total:'0원'});
  assert.equal(ui.nodes.get('#cart-drawer-empty').hidden, false);
  assert.equal(ui.nodes.get('#cart-checkout').disabled, true);
  ui.api.sync({count:2, total:'2,469.12원'});
  assert.equal(ui.nodes.get('#cart-drawer-count').textContent, '2');
  assert.equal(ui.nodes.get('#cart-drawer-total').textContent, '2,469.12원');
  assert.equal(ui.nodes.get('#floating-cart-total').textContent, '2,469.12원');
  assert.equal(ui.nodes.get('#floating-cart-count').textContent, 2);
  assert.equal(ui.nodes.get('#cart-drawer-empty').hidden, true);
  assert.equal(ui.nodes.get('#cart-checkout').disabled, false);
});
test('Checkout closes the drawer and requests only the existing validated form', () => {
  const ui = setup();
  ui.api.sync({count:1, total:'1,000원'}); ui.api.open(ui.trigger);
  ui.nodes.get('#cart-checkout').click();
  assert.equal(ui.drawer.open, false);
  assert.deepEqual(ui.requests, [ui.nodes.get('#order-button')]);
  ui.nodes.get('#cart-checkout').click();
  assert.equal(ui.requests.length, 1);
});
test('An empty or busy cart cannot enter checkout or open while checkout is checking', () => {
  const ui = setup(); ui.api.open(ui.trigger);
  ui.nodes.get('#cart-checkout').click(); assert.equal(ui.requests.length, 0);
  ui.api.sync({count:1, total:'1,000원', busy:true});
  ui.nodes.get('#cart-checkout').click(); assert.equal(ui.requests.length, 0);
  assert.equal(ui.nodes.get('#cart-checkout').disabled, true);
  ui.api.close(); assert.equal(ui.api.open(ui.trigger), false);
});
test('Closing returns keyboard focus to the opener and collapses ARIA', () => {
  const ui = setup(); ui.api.open(ui.trigger); ui.document.activeElement = ui.close; ui.close.click();
  assert.equal(ui.document.activeElement, ui.trigger);
  assert.equal(ui.trigger.attributes['aria-expanded'], 'false');
});
test('Floating launcher toggles its panel without a backdrop', () => {
  const ui = setup(); ui.api.open(ui.trigger);
  ui.trigger.click(); assert.equal(ui.drawer.open, false);
  assert.equal(ui.drawer.hidden, true);
});
test('Refresh failures stay visible and the retry asks only for catalog refresh', () => {
  const ui = setup(); ui.api.setStatus('연결 오류', true);
  assert.equal(ui.nodes.get('#cart-drawer-status').hidden, false);
  assert.equal(ui.nodes.get('#cart-drawer-retry').hidden, false);
  ui.nodes.get('#cart-drawer-retry').click();
  assert.deepEqual(ui.dispatched, ['moble:cart-refresh']);
  assert.equal(ui.requests.length, 0);
});
test('Removing the last row does not leave focus in a hidden cart section', () => {
  const ui = setup(); ui.api.open(ui.trigger);
  const hiddenButton = {insideDrawer:true, closest:() => ({id:'cart-edit-panel'})};
  ui.document.activeElement = hiddenButton;
  ui.api.sync({count:0,total:'0원'});
  assert.equal(ui.document.activeElement, ui.nodes.get('#cart-continue'));
});
test('Escape closes but the floating panel never traps Tab or steals background focus', () => {
  const ui = setup(); ui.api.open(ui.trigger);
  assert.equal(ui.drawer.handlers.has('keydown'), false);
  ui.document.querySelector = selector => selector === 'dialog[open]' ? null : ui.nodes.get(selector);
  ui.document.activeElement = ui.trigger;
  ui.api.sync({count:0,total:'0원'});
  assert.equal(ui.document.activeElement, ui.trigger);
  ui.api.added();
  assert.equal(ui.document.activeElement, ui.trigger);
  ui.documentHandlers.get('keydown')({key:'Escape'});
  assert.equal(ui.drawer.hidden, true);
  assert.equal(ui.document.activeElement, ui.trigger);
});
