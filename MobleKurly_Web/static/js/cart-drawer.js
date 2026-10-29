(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const drawer = $('#cart-drawer');
  const form = $('#order-form');
  if (!drawer || !form) return;
  const triggers = [...document.querySelectorAll('[data-open-cart]')];
  const checkout = $('#cart-checkout');
  const floating = $('#floating-cart');
  drawer.open = false;
  let lastTrigger = null;
  let state = {count: 0, busy: false};

  function setStatus(message, failed = false) {
    $('#cart-drawer-message').textContent = message;
    $('#cart-drawer-status').hidden = !message;
    $('#cart-drawer-status').dataset.failed = String(failed);
    $('#cart-drawer-retry').hidden = !failed;
  }
  function sync({count, total, busy = false}) {
    state = {count, busy};
    $('#cart-drawer-count').textContent = new Intl.NumberFormat('ko-KR').format(count);
    $('#cart-drawer-total').textContent = total;
    $('#floating-cart-count').textContent = count;
    $('#floating-cart-total').textContent = total;
    $('#cart-drawer-empty').hidden = count > 0;
    $('#cart-clear').disabled = count === 0 || busy;
    checkout.disabled = count === 0 || busy;
    checkout.querySelector('span').textContent = busy ? '최신 상품 정보를 확인하고 있어요…' : '주문서로 이동';
    if (drawer.open && count === 0 && drawer.contains(document.activeElement) && document.activeElement?.closest('#cart-edit-panel')) {
      $('#cart-continue').focus({preventScroll:true});
    }
  }
  function open(trigger) {
    if (state.busy || drawer.open || document.querySelector('dialog[open]')) return false;
    lastTrigger = trigger || triggers[0];
    setStatus('최신 상품 정보를 확인하고 있어요…');
    drawer.hidden = false;
    drawer.open = true;
    triggers.forEach(item => item.setAttribute('aria-expanded', 'true'));
    document.dispatchEvent(new CustomEvent('moble:cart-refresh'));
    return true;
  }
  triggers.forEach(trigger => trigger.addEventListener('click', event => {
    event.preventDefault();
    if (drawer.open) close(); else open(trigger);
  }));
  function close() {
    const hadFocus = drawer.contains(document.activeElement);
    drawer.hidden = true;
    drawer.open = false;
    triggers.forEach(item => item.setAttribute('aria-expanded', 'false'));
    if (hadFocus && lastTrigger?.isConnected) lastTrigger.focus({preventScroll:true});
  }
  drawer.querySelectorAll('[data-cart-close]').forEach(button => button.addEventListener('click', close));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && drawer.open && !document.querySelector('dialog[open]')) close();
  });
  $('#cart-drawer-retry').addEventListener('click', () => {
    setStatus('최신 상품 정보를 확인하고 있어요…');
    document.dispatchEvent(new CustomEvent('moble:cart-refresh'));
  });
  checkout.addEventListener('click', () => {
    if (!drawer.open || !state.count || state.busy) return;
    // Hand off to the existing validated checkout; never submit a second order.
    close();
    form.requestSubmit($('#order-button'));
  });
  function added() {
    // Feedback only: never open a panel, move focus, scroll, or submit an order.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    floating?.animate?.([{transform:'scale(1)'}, {transform:'scale(1.045)'}, {transform:'scale(1)'}],
      {duration:260, easing:'ease-out'});
  }
  window.MobleCartDrawer = Object.freeze({open, close, sync, setStatus, added});
})();
