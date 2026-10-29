(() => {
  'use strict';
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const form = $('#order-form');
  const grid = $('#product-grid');
  const cards = () => $$('.product-card', grid || document);
  const inputs = () => $$('.quantity input', form || document);
  const storageKey = 'moble-kurly-cart-v2';
  const numberFormat = new Intl.NumberFormat('ko-KR');
  let toastTimer;
  let cartRenderSignature = '';
  let inlineCartSignature = '';
  let submitting = false;
  let checkingOrder = false;
  let selectedDetailId = null;
  let detailView = null;
  let refreshInFlight = null;
  let catalogHtml = grid?.innerHTML.trim() || '';
  let confirmationNeedsAcknowledgement = false;
  let logisticsState = {status:'idle', products:new Map(), checkedAt:''};
  let logisticsInFlight = null;
  let logisticsController = null;
  let logisticsRequestSerial = 0;

  // Keep DB DECIMAL prices in integer hundredths, including every cart total.
  function priceCents(value) {
    const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(String(value));
    if (!match) throw new Error('Invalid product price');
    const absolute = BigInt(match[2]) * 100n + BigInt((match[3] || '').padEnd(2, '0'));
    return match[1] ? -absolute : absolute;
  }
  function money(cents) {
    const absolute = cents < 0n ? -cents : cents;
    const fraction = String(absolute % 100n).padStart(2, '0').replace(/0+$/, '');
    return (cents < 0n ? '-' : '') + numberFormat.format(absolute / 100n) + (fraction ? '.' + fraction : '') + '원';
  }
  function quantityFor(input) {
    const stock = Math.max(0, Number(input.max) || 0);
    return Math.max(0, Math.min(stock, Math.trunc(Number(input.value)) || 0));
  }
  function toast(message) {
    const target = $('#toast');
    if (!target) return;
    clearTimeout(toastTimer);
    target.textContent = message;
    target.hidden = false;
    toastTimer = setTimeout(() => { target.hidden = true; }, 3200);
  }
  function selectedItems() {
    return cards().map(card => ({
      card,
      id: card.dataset.id,
      name: card.dataset.name,
      color: card.dataset.color,
      price: priceCents(card.dataset.price),
      quantity: quantityFor($('.quantity input', card))
    })).filter(item => item.quantity > 0);
  }
  function selectionSignature() {
    return JSON.stringify(selectedItems().map(item => ({
      id: item.id, name: item.name, color: item.color,
      price: item.price.toString(), quantity: item.quantity
    })).sort((a, b) => Number(a.id) - Number(b.id)));
  }
  // Match the server: round each discounted product unit to the nearest won.
  const memberDiscount = Number(window.MOBLE_MEMBER_DISCOUNT || 0);
  function discountedUnit(price) {
    if (!memberDiscount) return price;
    const won = (price * BigInt(100 - memberDiscount) + 5000n) / 10000n;
    return won * 100n;
  }
  function discountedTotal(items) {
    return items.reduce((sum, item) => sum + discountedUnit(item.price) * BigInt(item.quantity), 0n);
  }
  function updateDiscountLabels(original, discounted) {
    const saving = original - discounted;
    const label = `${memberDiscount}% 할인 · −${money(saving)}`;
    const originalLabel = money(original);
    const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
    set('#cart-original', originalLabel);
    set('#cart-savings', label);
    set('#drawer-original', originalLabel);
    set('#drawer-savings', label);
  }
  function updateSummary() {
    if (!form) {
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
        const count = Object.values(saved).reduce((sum, value) => sum + Math.max(0, Math.trunc(Number(value)) || 0), 0);
        $$('[data-cart-count]').forEach(badge => { badge.textContent = count; badge.hidden = count === 0; });
      } catch {}
      return;
    }
    const saved = {};
    inputs().forEach(input => {
      const quantity = quantityFor(input);
      input.value = quantity;
      const card = input.closest('.product-card');
      saved[card.dataset.id] = quantity;
      $('.minus', card).disabled = quantity === 0;
      $('.plus', card).disabled = quantity >= Math.max(0, Number(input.max));
      $('[data-add-product]', card).disabled = quantity >= Math.max(0, Number(input.max));
    });
    const items = selectedItems();
    const count = items.reduce((sum, item) => sum + item.quantity, 0);
    const total = items.reduce((sum, item) => sum + BigInt(item.quantity) * item.price, 0n);
    $('#total-count').textContent = count;
    const memberTotal = discountedTotal(items);
    $('#total-price').textContent = money(memberTotal);
    updateDiscountLabels(total, memberTotal);
    $('#cart-description').textContent = count
      ? items.map(item => item.name + ' ' + item.quantity + '개').join(' · ')
      : '마음에 드는 상품을 담아보세요';
    const cartPanel = $('#cart-edit-panel');
    const cartItems = $('#cart-edit-items');
    if (cartPanel && cartItems) {
      cartPanel.hidden = count === 0;
      const cartSignature = JSON.stringify(items.map(item => [item.id, item.name, item.quantity,
        item.price.toString(), $('.quantity input', item.card).max, item.card.dataset.photo || '']));
      // An unchanged DB refresh must not replace the control being operated.
      if (cartSignature !== cartRenderSignature) {
      const focused = cartItems.contains(document.activeElement) ? document.activeElement : null;
      const focusedId = focused?.dataset.productId || focused?.dataset.removeProduct;
      const focusedChange = focused?.dataset.cartChange;
      const previousIndex = focused ? [...cartItems.children].indexOf(focused.closest('.cart-edit-item')) : -1;
      cartItems.replaceChildren();
      items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'cart-edit-item';
        const info = document.createElement('div');
        info.className = 'cart-edit-info';
        const name = document.createElement('strong');
        name.textContent = item.name;
        const detail = document.createElement('span');
        detail.textContent = `${item.quantity}개 · ${money(item.price * BigInt(item.quantity))}`;
        info.append(name, detail);
        const thumbnail = document.createElement('img');
        thumbnail.className = 'cart-product-thumbnail';
        thumbnail.alt = item.name + ' 사진';
        thumbnail.loading = 'lazy';
        const sourceCard = cards().find(card => card.dataset.id === item.id);
        const photo = sourceCard?.dataset.photo || sourceCard?.querySelector('.product-photo-img')?.src || ({'1':'strawberry','2':'blueberry','3':'yellow_pepper','4':'broccoli','5':'tomato','6':'apple','7':'grapes','8':'eggplant','9':'carrot','10':'corn','11':'cucumber','12':'cabbage'}[item.id] ? `/static/images/products/${({'1':'strawberry','2':'blueberry','3':'yellow_pepper','4':'broccoli','5':'tomato','6':'apple','7':'grapes','8':'eggplant','9':'carrot','10':'corn','11':'cucumber','12':'cabbage'}[item.id])}.webp` : '');
        if (photo) {
          thumbnail.src = photo;
        } else {
          thumbnail.hidden = true;
        }
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'cart-remove-button';
        remove.dataset.removeProduct = item.id;
        remove.textContent = '삭제';
        remove.setAttribute('aria-label', `${item.name} 장바구니에서 삭제`);
        const controls = document.createElement('div');
        controls.className = 'cart-edit-controls';
        const minus = document.createElement('button');
        minus.type = 'button';
        minus.className = 'cart-qty-button';
        minus.dataset.cartChange = '-1';
        minus.dataset.productId = item.id;
        minus.textContent = '−';
        minus.setAttribute('aria-label', `${item.name} 수량 감소`);
        const quantity = document.createElement('span');
        quantity.className = 'cart-qty-value';
        quantity.textContent = String(item.quantity);
        const plus = document.createElement('button');
        plus.type = 'button';
        plus.className = 'cart-qty-button';
        plus.dataset.cartChange = '1';
        plus.dataset.productId = item.id;
        plus.textContent = '+';
        plus.setAttribute('aria-label', `${item.name} 수량 증가`);
        const card = cards().find(card => card.dataset.id === item.id);
        const max = Number(card?.querySelector('.quantity input')?.max ?? 0);
        plus.disabled = item.quantity >= max;
        controls.append(minus, quantity, plus, remove);
        row.append(thumbnail, info, controls);
        cartItems.append(row);
      });
      cartRenderSignature = cartSignature;
      if (focused) {
        const candidates = $$('button', cartItems);
        const sameControl = candidates.find(button => !button.disabled &&
          (focusedChange !== undefined
            ? button.dataset.productId === focusedId && button.dataset.cartChange === focusedChange
            : button.dataset.removeProduct === focusedId));
        const sameProduct = candidates.find(button => !button.disabled && button.dataset.productId === focusedId);
        const nearby = cartItems.children[Math.min(Math.max(previousIndex, 0), cartItems.children.length - 1)]?.querySelector('button:not(:disabled)');
        (sameControl || sameProduct || nearby || ($('#cart-drawer')?.open ? $('#cart-continue') : $('#product-search')))?.focus({preventScroll:true});
      }
      }
    }
    // The horizontal order summary has its own editable rows. Clone the same
    // product thumbnails and controls used by the existing drawer, keeping
    // both views synchronized with the original product quantity inputs.
    const inlineCart = $('#inline-cart');
    const inlineItems = $('#inline-cart-items');
    if (inlineCart && inlineItems && cartItems) {
      inlineCart.hidden = count === 0;
      const inlineSignature = cartRenderSignature;
      if (inlineSignature !== inlineCartSignature) {
        const focused = inlineItems.contains(document.activeElement) ? document.activeElement : null;
        const productId = focused?.dataset.productId || focused?.dataset.removeProduct;
        const change = focused?.dataset.cartChange;
        inlineItems.replaceChildren(...[...cartItems.children].map(row => row.cloneNode(true)));
        inlineCartSignature = inlineSignature;
        if (focused) {
          const buttons = [...inlineItems.querySelectorAll('button:not(:disabled)')];
          (buttons.find(b => (b.dataset.productId || b.dataset.removeProduct) === productId && b.dataset.cartChange === change)
            || buttons.find(b => (b.dataset.productId || b.dataset.removeProduct) === productId)
            || buttons[0] || $('#order-button'))?.focus({preventScroll:true});
        }
      }
    }
    $('#order-button').disabled = !count || submitting || checkingOrder;
    window.MobleCartDrawer?.sync({count, total:money(memberTotal), busy:submitting || checkingOrder});
    $('#order-summary').hidden = cards().length === 0;
    $$('[data-cart-count]').forEach(badge => { badge.textContent = count; badge.hidden = count === 0; });
    try { sessionStorage.setItem(storageKey, JSON.stringify(saved)); } catch {}
  }
  function addOne(card) {
    const input = $('.quantity input', card);
    if (!input || input.disabled || Number(input.value) >= Number(input.max)) {
      toast('현재 주문 가능한 수량을 모두 담았어요.');
      return false;
    }
    input.value = quantityFor(input) + 1;
    updateSummary();
    toast(card.dataset.name + ' 한 개를 담았어요.');
    // Finish detail selection without opening or focusing the floating basket.
    const detail = $('#product-dialog');
    if (detail?.open) detail.close();
    window.MobleCartDrawer?.added();
    return true;
  }

  let activeColor = new URLSearchParams(location.search).get('color') || 'all';
  if (!$$('.filter-tab').some(tab => tab.dataset.color === activeColor)) activeColor = 'all';
  const search = $('#product-search');
  const aliases = {red:'레드 빨강 빨간',blue:'블루 파랑 파란',yellow:'옐로 옐로우 노랑 노란',green:'그린 초록 녹색'};
  function filterProducts() {
    if (!form) return;
    const query = (search?.value || '').trim().toLowerCase();
    let visible = 0;
    cards().forEach(card => {
      const text = (card.dataset.name + ' ' + card.dataset.color + ' ' + (aliases[card.dataset.color] || '')).toLowerCase();
      card.hidden = !(activeColor === 'all' || card.dataset.color === activeColor) || !text.includes(query);
      if (!card.hidden) visible++;
    });
    $$('.filter-tab, [data-color-jump]').forEach(tab => {
      const active = (tab.dataset.color || tab.dataset.colorJump) === activeColor;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-pressed', String(active));
    });
    const feedback = $('#search-feedback');
    feedback.hidden = !query;
    feedback.textContent = '“' + query + '” 검색 결과 · ' + visible + '개 상품';
    $('#catalog-empty').hidden = cards().length !== 0;
    $('#no-results').hidden = cards().length === 0 || visible > 0;
  }
  function sortProducts() {
    if (!grid) return;
    const sorted = cards();
    const sort = $('#product-sort').value;
    if (sort === 'price-low' || sort === 'price-high') {
      sorted.sort((a, b) => {
        const difference = priceCents(a.dataset.price) - priceCents(b.dataset.price);
        const comparison = difference < 0n ? -1 : difference > 0n ? 1 : 0;
        return sort === 'price-low' ? comparison : -comparison;
      });
    } else if (sort === 'name') {
      sorted.sort((a, b) => a.dataset.name.localeCompare(b.dataset.name, 'ko'));
    } else {
      sorted.sort((a, b) => Number(a.dataset.id) - Number(b.dataset.id));
    }
    sorted.forEach(card => grid.append(card));
  }
  function renderProductGuide(target, template) {
    if (!target) return;
    const signature = template?.innerHTML || '';
    if (target.dataset.guideSignature === signature) return;
    target.replaceChildren(...(template ? [template.content.cloneNode(true)] : []));
    target.dataset.guideSignature = signature;
  }
  function updateDetail() {
    if (!selectedDetailId) return;
    const card = cards().find(item => item.dataset.id === selectedDetailId);
    if (!card) {
      $('#product-dialog').close();
      selectedDetailId = null;
      return;
    }
    const safeColor = ['red','blue','yellow','green'].includes(card.dataset.color) ? card.dataset.color : 'neutral';
    $('#detail-photo').className = 'product-photo color-' + safeColor;
    $('#detail-photo').style.backgroundImage = card.dataset.photo ? `url("${card.dataset.photo}")` : '';
    $('#detail-photo').style.backgroundSize = card.dataset.photo ? 'cover' : '';
    $('#detail-photo').style.backgroundPosition = card.dataset.photo ? 'center' : '';
    $('#detail-photo').setAttribute('aria-label', card.dataset.name + ' 상품 연출 이미지');
    $('#product-dialog-title').textContent = card.dataset.name;
    $('#detail-description').textContent = $('.product-description', card).textContent;
    $('#detail-price').textContent = money(priceCents(card.dataset.price));
    $('#detail-selling-unit').textContent = card.dataset.name;
    renderProductGuide($('#detail-guide'), $('.product-guide-template', card));
    const input = $('.quantity input', card);
    $('#detail-add').disabled = input.disabled || quantityFor(input) >= Number(input.max);
  }
  function setConfirmStatus(message) {
    $('#confirm-status').textContent = message;
    $('#confirm-status').hidden = !message;
    delete $('#confirm-status').dataset.logisticsWarning;
  }
  function updateConfirmButton() {
    const button = $('#confirm-order');
    if (!button) return;
    button.disabled = submitting || checkingOrder || !selectedItems().length;
    button.textContent = submitting ? '주문을 접수하고 있어요…'
      : checkingOrder ? '최신 상품 정보를 확인하고 있어요…'
      : confirmationNeedsAcknowledgement ? '변경 내용 확인하기'
      : '결제하기';
  }
  function renderConfirmation() {
    const items = selectedItems();
    const wrapper = $('#confirm-items');
    wrapper.replaceChildren();
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'confirm-item';
      const thumbnail = document.createElement('span');
      const safeColor = ['red','blue','yellow','green'].includes(item.color) ? item.color : 'neutral';
      thumbnail.className = 'item-color color-' + safeColor;
      const sourceCard = cards().find(card => card.dataset.id === String(item.id));
      if (sourceCard?.dataset.photo) { thumbnail.style.backgroundImage = `url("${sourceCard.dataset.photo}")`; thumbnail.style.backgroundSize = 'cover'; thumbnail.style.backgroundPosition = 'center'; }
      const info = document.createElement('div');
      const title = document.createElement('div'); title.textContent = item.name;
      const sub = document.createElement('small'); sub.textContent = money(item.price) + ' × ' + item.quantity + '개';
      info.append(title, sub);
      const price = document.createElement('b'); price.textContent = money(item.price * BigInt(item.quantity));
      row.append(thumbnail, info, price); wrapper.append(row);
    });
    const original = items.reduce((sum, item) => sum + item.price * BigInt(item.quantity), 0n);
    const payable = discountedTotal(items);
    const pointsInput = $('#points-to-use');
    const pointsCap = pointsInput ? Math.max(0, Math.trunc(Number(pointsInput.max) || 0)) : 0;
    const pointsLimit = Math.min(pointsCap, Number(payable / 100n));
    const pointsValue = pointsInput ? Math.max(0, Math.min(pointsLimit, Math.trunc(Number(pointsInput.value) || 0))) : 0;
    if (pointsInput) pointsInput.value = String(pointsValue);
    const cancelPointsButton = $('#points-cancel');
    if (cancelPointsButton) cancelPointsButton.hidden = pointsValue === 0;
    if ($('#confirm-points-used')) $('#confirm-points-used').textContent = '−' + money(BigInt(pointsValue) * 100n);
    $('#confirm-total').textContent = money(payable - BigInt(pointsValue) * 100n);
    if ($('#confirm-original')) $('#confirm-original').textContent = money(original);
    if ($('#confirm-savings')) $('#confirm-savings').textContent = '−' + money(original - payable);
    if ($('#confirm-points')) $('#confirm-points').textContent = money(((payable - BigInt(pointsValue) * 100n + 5000n) / 10000n) * 100n);
    renderLogisticsPanels();
    updateConfirmButton();
  }
  function logisticsVisible() {
    return Boolean($('#detail-logistics') && $('#product-dialog')?.open);
  }
  function logisticsElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function logisticsMetric(label, value, note, className = '') {
    const group = logisticsElement('div', 'logistics-metric ' + className);
    group.append(logisticsElement('dt', '', label), logisticsElement('dd', '', value));
    if (note) group.append(logisticsElement('dd', 'logistics-metric-note', note));
    return group;
  }
  function renderLogisticsPanel(panel, productIds, showNames) {
    if (!panel) return;
    const content = $('[data-logistics-content]', panel);
    content.replaceChildren();
    content.setAttribute('aria-busy', String(logisticsState.status === 'loading'));
    if (logisticsState.status === 'loading' || logisticsState.status === 'idle') {
      content.append(logisticsElement('p', 'logistics-loading', '최신 재고와 입고 기록을 확인하고 있어요…'));
      return;
    }
    if (logisticsState.status === 'error') {
      const error = logisticsElement('div', 'logistics-error');
      error.append(logisticsElement('p', '', '재고·입고 정보를 불러오지 못했습니다. 연결을 확인하고 다시 시도해 주세요.'));
      error.append(logisticsElement('p', 'logistics-error-note', '주문은 계속할 수 있으며, 최신 가격과 주문 가능 수량은 접수 전에 별도로 확인합니다.'));
      const retry = logisticsElement('button', 'logistics-retry', '물류 정보 다시 불러오기');
      retry.type = 'button';
      retry.dataset.retryLogistics = '';
      error.append(retry);
      content.append(error);
      return;
    }
    productIds.forEach(id => {
      const product = logisticsState.products.get(String(id));
      const entry = logisticsElement('article', 'logistics-product');
      const card = cards().find(item => item.dataset.id === String(id));
      if (showNames) entry.append(logisticsElement('h4', '', product?.name || card?.dataset.name || '선택한 상품'));
      if (!product) {
        entry.append(logisticsElement('p', 'logistics-unavailable', '이 상품의 최신 물류 정보를 확인할 수 없습니다. 상품 목록을 새로 확인해 주세요.'));
      } else {
        const metrics = logisticsElement('dl', 'logistics-metrics');
        metrics.append(logisticsMetric('현재 재고', numberFormat.format(product.stock) + '개', '조회 시점의 보유 수량', 'logistics-stock'));
        metrics.append(logisticsMetric('최근 입고 기록', product.last_received_label,
          product.last_received_at ? product.elapsed_label : '입고 경과시간 확인 불가', 'logistics-received'));
        const pending = product.pending_count > 0
          ? '입고 대기 ' + numberFormat.format(product.pending_quantity) + '개 · 발주 ' + numberFormat.format(product.pending_count) + '건'
          : '대기 중인 발주 없음';
        metrics.append(logisticsMetric('다음 입고', product.next_arrival_label, pending, 'logistics-next'));
        entry.append(metrics);
      }
      content.append(entry);
    });
    content.append(logisticsElement('p', 'logistics-schedule-note', '대기 발주는 입고가 완료되지 않은 수량이며, 입고 예정일은 현재 등록되어 있지 않습니다.'));
    const checked = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(logisticsState.checkedAt);
    if (checked) content.append(logisticsElement('p', 'logistics-checked-at', '물류 정보 확인 · ' + checked[2] + '.' + checked[3] + ' ' + checked[4] + ':' + checked[5]));
  }
  function renderLogisticsPanels() {
    if ($('#product-dialog')?.open && selectedDetailId) {
      renderLogisticsPanel($('#detail-logistics'), [selectedDetailId], false);
    }
  }
  function refreshLogistics({clear = false} = {}) {
    if (!form || !logisticsVisible()) return Promise.resolve(false);
    if (logisticsInFlight && !clear) return logisticsInFlight;
    if (clear) logisticsController?.abort();
    const serial = ++logisticsRequestSerial;
    const controller = new AbortController();
    logisticsController = controller;
    // Keep a readable, timestamped snapshot during a background refresh.
    // Opening a new view or retrying still clears old information explicitly.
    if (clear || logisticsState.status !== 'ready') {
      logisticsState = {status:'loading', products:new Map(), checkedAt:''};
      renderLogisticsPanels();
      updateConfirmButton();
    }
    logisticsInFlight = (async () => {
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch('/api/logistics', {cache:'no-store', credentials:'same-origin', signal:controller.signal});
        if (!response.ok) throw new Error('Logistics unavailable');
        const data = await response.json();
        if (data.database !== 'moblekurly' || !Array.isArray(data.products) || (data.checked_at !== null && typeof data.checked_at !== 'string')
            || !data.products.every(product => Number.isInteger(product.product_id)
              && typeof product.name === 'string' && Number.isInteger(product.stock) && product.stock >= 0
              && typeof product.last_received_label === 'string' && typeof product.elapsed_label === 'string'
              && (product.last_received_at === null || typeof product.last_received_at === 'string')
              && Number.isInteger(product.pending_quantity) && product.pending_quantity >= 0
              && Number.isInteger(product.pending_count) && product.pending_count >= 0
              && product.next_arrival_at === null && product.next_arrival_label === '일정 미등록'
              && product.stock_age_known === false)) throw new Error('Invalid logistics response');
        if (serial !== logisticsRequestSerial) return false;
        const unchanged = logisticsState.status === 'ready'
          && JSON.stringify([...logisticsState.products.values()]) === JSON.stringify(data.products)
          && logisticsState.checkedAt.slice(0,16) === (data.checked_at || '').slice(0,16);
        logisticsState = {status:'ready', products:new Map(data.products.map(product => [String(product.product_id), product])), checkedAt:data.checked_at || ''};
        if ($('#confirm-status')?.dataset.logisticsWarning) setConfirmStatus('');
        if (!unchanged) renderLogisticsPanels();
        return true;
      } catch {
        if (serial !== logisticsRequestSerial) return false;
        logisticsState = {status:'error', products:new Map(), checkedAt:''};
        renderLogisticsPanels();
        return false;
      } finally {
        clearTimeout(timeout);
        if (serial === logisticsRequestSerial) {
          logisticsInFlight = null;
          logisticsController = null;
          updateConfirmButton();
        }
      }
    })();
    return logisticsInFlight;
  }
  function setCatalogStatus(message, failed = false) {
    $('#catalog-sync-message').textContent = message;
    $('#catalog-sync-status').hidden = !message;
    $('#retry-catalog').hidden = !failed;
  }
  function applyCatalog(data) {
    const before = selectionSignature();
    const previousQuantities = Object.fromEntries(cards().map(card => [card.dataset.id, quantityFor($('.quantity input', card))]));
    const focusedInput = document.activeElement?.matches('.quantity input') ? document.activeElement.closest('.product-card').dataset.id : null;
    const html = data.html.trim();
    if (html !== catalogHtml) {
      grid.innerHTML = html;
      catalogHtml = html;
      inputs().forEach(input => { input.value = previousQuantities[input.closest('.product-card').dataset.id] || 0; });
      sortProducts();
      if (focusedInput) cards().find(card => card.dataset.id === focusedInput)?.querySelector('.quantity input')?.focus({preventScroll:true});
    }
    updateSummary();
    filterProducts();
    updateDetail();
    const changed = before !== selectionSignature();
    if ($('#cart-drawer')?.open) {
      window.MobleCartDrawer?.setStatus(changed
        ? '가격이나 재고가 변경되어 최신 정보로 반영했어요. 담긴 수량과 합계를 확인해 주세요.' : '');
    }
    if ($('#confirm-dialog').open) {
      if (changed) {
        confirmationNeedsAcknowledgement = true;
        setConfirmStatus(selectedItems().length
          ? 'DB의 상품 정보가 변경되어 가격과 주문 가능 수량을 다시 반영했습니다. 변경 내용을 확인한 뒤 주문을 다시 접수해 주세요.'
          : '선택하신 상품이 품절되었거나 판매 목록에서 제외되었습니다. 창을 닫고 다른 상품을 선택해 주세요.');
        renderConfirmation();
      } else {
        updateConfirmButton();
      }
    }
    return changed;
  }
  function refreshCatalog() {
    if (!form || submitting) return Promise.resolve(false);
    if (refreshInFlight) return refreshInFlight;
    refreshInFlight = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch('/api/products', {cache:'no-store', credentials:'same-origin', signal:controller.signal});
        if (!response.ok) throw new Error('Catalog unavailable');
        const data = await response.json();
        if (data.database !== 'moblekurly' || typeof data.html !== 'string' || !Array.isArray(data.products)) {
          throw new Error('Invalid catalog response');
        }
        applyCatalog(data);
        setCatalogStatus('');
        if (logisticsVisible()) void refreshLogistics();
        return true;
      } catch {
        setCatalogStatus('최신 상품 정보를 확인하지 못했습니다. 연결을 확인하고 다시 시도해 주세요. 최신 가격과 수량을 확인하기 전에는 주문이 접수되지 않습니다.', true);
        window.MobleCartDrawer?.setStatus('최신 가격과 재고를 확인하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.', true);
        if ($('#confirm-dialog').open) setConfirmStatus('최신 가격과 재고를 확인하지 못해 주문을 접수하지 않았습니다. 잠시 후 다시 눌러 주세요.');
        return false;
      } finally {
        clearTimeout(timeout);
        refreshInFlight = null;
      }
    })();
    return refreshInFlight;
  }

  [$('#cart-edit-panel'), $('#inline-cart')].filter(Boolean).forEach(panel => panel.addEventListener('click', event => {
    const change = event.target.closest('[data-cart-change]');
    if (change) {
      const card = cards().find(item => item.dataset.id === change.dataset.productId);
      const input = card?.querySelector('.quantity input');
      if (input) {
        const current = quantityFor(input);
        const max = Math.max(0, Number(input.max));
        const next = Math.max(0, Math.min(max, current + Number(change.dataset.cartChange)));
        if (next === current && Number(change.dataset.cartChange) > 0) {
          toast('현재 주문 가능한 재고 수량을 초과할 수 없어요.');
          return;
        }
        input.value = next;
        updateSummary();
      }
      return;
    }
    const remove = event.target.closest('[data-remove-product]');
    if (remove) {
      const card = cards().find(item => item.dataset.id === remove.dataset.removeProduct);
      const input = card?.querySelector('.quantity input');
      if (input) {
        input.value = 0;
        updateSummary();
        toast(card.dataset.name + ' 상품을 장바구니에서 삭제했어요.');
      }
    } else if (event.target.closest('#cart-clear')) {
      inputs().forEach(input => { input.value = 0; });
      updateSummary();
      toast('장바구니를 모두 비웠어요.');
    }
  }));

  // Delegation keeps controls working when a DB refresh replaces the cards.
  form?.addEventListener('input', event => {
    if (event.target.matches('.quantity input')) updateSummary();
  });
  form?.addEventListener('click', event => {
    const target = event.target.closest('button');
    if (!target) return;
    const card = target.closest('.product-card');
    if (!card) return;
    if (target.matches('.qty-btn')) {
      const input = $('.quantity input', card);
      input.value = quantityFor(input) + (target.classList.contains('plus') ? 1 : -1);
      updateSummary();
    } else if (target.matches('[data-add-product]')) {
      addOne(card);
    } else if (target.matches('[data-product-detail]')) {
      selectedDetailId = card.dataset.id;
      detailView = {x:window.scrollX, y:window.scrollY, opener:target, id:card.dataset.id};
      updateDetail();
      $('#product-dialog').showModal();
      window.scrollTo({left:detailView.x, top:detailView.y, behavior:'instant'});
      void refreshLogistics({clear:true});
    }
  });
  $$('.filter-tab').forEach(tab => tab.addEventListener('click', () => { activeColor = tab.dataset.color; filterProducts(); }));
  $$('[data-color-jump]').forEach(button => button.addEventListener('click', () => {
    activeColor = button.dataset.colorJump;
    if (search) search.value = '';
    filterProducts();
    $('#products')?.scrollIntoView({behavior:'smooth', block:'start'});
  }));
  if (form) {
    $('.header-search')?.addEventListener('submit', event => {
      event.preventDefault();
      filterProducts();
      $('#products').scrollIntoView({behavior:'smooth', block:'start'});
    });
    search?.addEventListener('input', filterProducts);
    $('#reset-filters').addEventListener('click', () => { activeColor = 'all'; if (search) search.value = ''; filterProducts(); });
    $('#product-sort').addEventListener('change', sortProducts);
    $('#retry-catalog').addEventListener('click', () => { void refreshCatalog(); });
  }
  $$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  $('#product-dialog')?.addEventListener('close', () => {
    selectedDetailId = null;
    const view = detailView;
    detailView = null;
    if (!view) return;
    const opener = view.opener?.isConnected ? view.opener : cards().find(card => card.dataset.id === view.id)?.querySelector('[data-product-detail]');
    opener?.focus({preventScroll:true});
    window.scrollTo({left:view.x, top:view.y, behavior:'instant'});
  });
  $$('dialog:not(.cart-drawer)').forEach(dialog => dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }));
  $('#detail-add')?.addEventListener('click', () => {
    const card = cards().find(item => item.dataset.id === selectedDetailId);
    if (card) addOne(card);
  });
  form?.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || checkingOrder || !selectedItems().length) return;
    checkingOrder = true;
    updateSummary();
    try {
      if (!await refreshCatalog()) return;
      if (!selectedItems().length) {
        toast('선택하신 상품의 주문 가능 수량이 변경되었습니다. 상품을 다시 선택해 주세요.');
        return;
      }
      confirmationNeedsAcknowledgement = false;
      setConfirmStatus('');
      renderConfirmation();
      $('#confirm-dialog').showModal();
    } finally {
      checkingOrder = false;
      updateSummary();
      updateConfirmButton();
    }
  });
  $('#points-to-use')?.addEventListener('input', () => { renderConfirmation(); });
  $('#points-use-all')?.addEventListener('click', () => {
    const input = $('#points-to-use');
    if (input) { input.value = input.max; renderConfirmation(); }
  });
  $('#points-cancel')?.addEventListener('click', () => {
    const input = $('#points-to-use');
    if (input) { input.value = '0'; renderConfirmation(); }
  });
  $('#confirm-order')?.addEventListener('click', async () => {
    if (submitting || checkingOrder || !selectedItems().length) return;
    if (window.MobleCheckout && !window.MobleCheckout.validate()) return;
    checkingOrder = true;
    updateSummary();
    updateConfirmButton();
    try {
      if (!await refreshCatalog()) return;
      if (!$('#confirm-dialog').open || !selectedItems().length) return;
      if (confirmationNeedsAcknowledgement) {
        confirmationNeedsAcknowledgement = false;
        setConfirmStatus('변경된 가격과 수량을 위에 표시했습니다. 내용을 확인한 뒤 결제하기를 한 번 더 눌러 주세요. 아직 주문은 접수되지 않았습니다.');
        return;
      }
      if (window.MobleCheckout && !await window.MobleCheckout.authorize()) return;
      if (!$('#confirm-dialog').open) return;
      submitting = true;
      updateConfirmButton();
      updateSummary();
      HTMLFormElement.prototype.submit.call(form);
    } finally {
      checkingOrder = false;
      if (!submitting) {
        updateSummary(); updateConfirmButton();
        if ($('#confirm-dialog')?.open && (document.activeElement === document.body || document.activeElement === $('#confirm-dialog'))) {
          $('#confirm-order')?.focus({preventScroll:true});
        }
      }
    }
  });

  try {
    if ($('#order-number')) sessionStorage.removeItem(storageKey);
    if (form) {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
      inputs().forEach(input => { input.value = saved[input.closest('.product-card').dataset.id] || 0; });
    }
  } catch {}
  updateSummary();
  filterProducts();
  document.addEventListener('moble:cart-refresh', () => { void refreshCatalog(); });
  if (form && new URLSearchParams(location.search).get('reorder') === '1') {
    fetch('/api/reorder-cart', {credentials:'same-origin'}).then(r => r.ok ? r.json() : null).then(data => {
      if (!data?.cart) return;
      Object.entries(data.cart).forEach(([id, count]) => {
        const card = cards().find(c => c.dataset.id === id);
        const input = card?.querySelector('.quantity input');
        if (input) input.value = Math.min(Number(input.max) || 0, Math.max(0, Number(count) || 0));
      });
      updateSummary();
      window.MobleCartDrawer?.open(document.querySelector('.bag-link'));
    }).catch(() => {});
  }
  if (form && new URLSearchParams(location.search).get('cart') === 'open') window.MobleCartDrawer?.open($('.bag-link'));
  if (form) {
    void refreshCatalog();
    setInterval(() => { if (!document.hidden && !submitting) void refreshCatalog(); }, 15000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refreshCatalog(); });
    window.addEventListener('focus', () => { void refreshCatalog(); });
  }
  window.addEventListener('pageshow', () => {
    submitting = false;
    checkingOrder = false;
    updateSummary();
    if (form) { updateConfirmButton(); void refreshCatalog(); }
  });
  $$('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      toast('주문번호를 복사했어요.');
    } catch {
      toast('주문번호를 길게 누르거나 드래그해서 복사해 주세요.');
    }
  }));
  $('#dismiss-announcement')?.addEventListener('click', () => { $('#announcement').hidden = true; });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-retry-logistics]')) void refreshLogistics({clear:true});
    const menu = $('.category-menu');
    if (menu?.open && !menu.contains(event.target)) menu.open = false;
  });
})();

