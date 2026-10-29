(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const advertising = $('#advertising-carousel');
  if (advertising) {
    const slides = [...advertising.querySelectorAll('[data-ad-slide]')];
    const dots = [...advertising.querySelectorAll('[data-ad-dot]')];
    const toggle = advertising.querySelector('[data-ad-toggle]');
    const controls = advertising.querySelector('.advertising-navigation');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const pauses = new Set();
    let index = 0;
    let playing = !reduced.matches;
    let timer;
    let touch;
    function schedule() {
      clearTimeout(timer);
      if (playing && !pauses.size && slides.length > 1) timer = setTimeout(() => show(index + 1), 5000);
    }
    function show(next) {
      index = (next + slides.length) % slides.length;
      slides.forEach((slide, i) => { slide.hidden = i !== index; slide.inert = i !== index; });
      dots.forEach((dot, i) => { dot.classList.toggle('is-active', i === index); dot.setAttribute('aria-current', String(i === index)); });
      advertising.querySelector('[data-ad-counter]').textContent = String(index + 1).padStart(2, '0') + ' / ' + String(slides.length).padStart(2, '0');
      schedule();
    }
    function pause(reason, value) { if (value) pauses.add(reason); else pauses.delete(reason); schedule(); }
    function playback() {
      toggle.setAttribute('aria-pressed', String(!playing));
      toggle.setAttribute('aria-label', playing ? '광고 자동 재생 일시정지' : '광고 자동 재생 시작');
      toggle.firstElementChild.textContent = playing ? 'Ⅱ' : '▶';
      schedule();
    }
    advertising.querySelector('[data-ad-prev]').addEventListener('click', () => show(index - 1));
    advertising.querySelector('[data-ad-next]').addEventListener('click', () => show(index + 1));
    dots.forEach((dot, i) => dot.addEventListener('click', () => show(i)));
    toggle.addEventListener('click', () => { playing = !playing; playback(); });
    advertising.addEventListener('mouseenter', () => pause('pointer', true));
    advertising.addEventListener('mouseleave', () => pause('pointer', false));
    advertising.addEventListener('focusin', () => pause('focus', true));
    advertising.addEventListener('focusout', () => queueMicrotask(() => pause('focus', advertising.contains(document.activeElement))));
    controls.addEventListener('keydown', event => {
      if (event.altKey || event.ctrlKey || event.metaKey || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
      event.preventDefault(); show(index + (event.key === 'ArrowRight' ? 1 : -1));
    });
    advertising.addEventListener('touchstart', event => { touch = event.touches.length === 1 ? {x:event.touches[0].clientX,y:event.touches[0].clientY} : null; pause('touch', true); }, {passive:true});
    advertising.addEventListener('touchend', event => {
      if (touch && event.changedTouches.length) {
        const x = event.changedTouches[0].clientX - touch.x;
        const y = event.changedTouches[0].clientY - touch.y;
        if (Math.abs(x) > 45 && Math.abs(x) > Math.abs(y) * 1.3) show(index + (x < 0 ? 1 : -1));
      }
      touch = null; pause('touch', false);
    }, {passive:true});
    advertising.addEventListener('touchcancel', () => { touch = null; pause('touch', false); }, {passive:true});
    document.addEventListener('visibilitychange', () => pause('hidden', document.hidden));
    const observer = new MutationObserver(() => pause('dialog', Boolean($('dialog[open]'))));
    document.querySelectorAll('dialog').forEach(item => observer.observe(item, {attributes:true,attributeFilter:['open']}));
    reduced.addEventListener('change', () => { if (reduced.matches) { playing = false; playback(); } });
    pause('hidden', document.hidden);
    pause('dialog', Boolean($('dialog[open]')));
    playback();
  }
  const dialog = $('#confirm-dialog');
  const region = $('#delivery-region');
  if (!dialog || !region) return;

  const fields = $('#checkout-choice-fields');
  const consent = $('#demo-consent');
  const status = $('#demo-payment-status');
  const scenario = $('#demo-scenario');
  const name = $('#recipient-name');
  const phone = $('#recipient-phone');
  const request = $('#delivery-request');
  const sms = $('#sms-consent');
  const feedback = $('#delivery-region-feedback');
  const regions = new Map([...region.options].filter(o => o.value).map(o => [o.value, o.textContent]));
  const methods = new Set(['card', 'wallet', 'transfer']);
  const preferenceKey = 'moble-kurly-demo-choices-v1';
  let generation = 0;
  let delayTimer;
  let finishDelay;

  const phoneDigits = () => phone.value.replace(/[\s-]/g, '');
  function renderReview() {
    $('#delivery-request-count').textContent = request.value.length + ' / 200';
    const digits = phoneDigits();
    const validPhone = /^01\d{8,9}$/.test(digits);
    $('#recipient-review').hidden = !name.value.trim() && !phone.value && !request.value && !sms.checked;
    $('#recipient-review-summary').textContent = (name.value.trim() || '받는 분 입력 전') + ' · ' + (validPhone ? digits.slice(0,3) + '-****-' + digits.slice(-4) : '연락처 확인 필요');
    $('#recipient-review-request').textContent = request.value.trim() ? '요청사항 · ' + request.value.trim() : '배송 요청사항 없음';
    $('#recipient-review-sms').textContent = sms.checked ? '배송 문자 · 수신 동의' : '배송 문자 · 수신하지 않음';
  }
  function clearPrivate() {
    name.value = name.defaultValue || ''; phone.value = phone.defaultValue || ''; request.value = ''; sms.checked = false;
    name.setCustomValidity(''); phone.setCustomValidity(''); request.setCustomValidity('');
    $('#recipient-review').hidden = true;
    $('#recipient-review-summary').textContent = '';
    $('#recipient-review-request').textContent = '';
    $('#recipient-review-sms').textContent = '';
    $('#delivery-request-count').textContent = '0 / 200';
  }

  function message(text, kind = 'info') {
    status.textContent = text;
    status.dataset.kind = kind;
    status.hidden = !text;
  }
  function choices() {
    return {region:region.value, method:document.querySelector('[name="demo-method-choice"]:checked')?.value || ''};
  }
  function sync() {
    const selected = choices();
    $('#checkout-region-value').value = selected.region;
    $('#checkout-method-value').value = selected.method;
    $('#checkout-ack-value').value = consent.checked ? '1' : '0';
    feedback.hidden = !regions.has(selected.region);
    feedback.textContent = regions.has(selected.region) ? '📍 선택한 권역 · ' + regions.get(selected.region) : '';
    try { sessionStorage.setItem(preferenceKey, JSON.stringify(selected)); } catch {}
    renderReview();
  }
  function validate() {
    name.setCustomValidity(''); phone.setCustomValidity(''); request.setCustomValidity('');
    if (!name.value.trim() || name.value.trim().length > 40 || /[\u0000-\u001f\u007f]/.test(name.value)) {
      name.setCustomValidity('받는 분 이름을 40자 이내로 입력해 주세요.');
      message('받는 분 이름을 확인해 주세요.', 'error'); name.focus(); name.reportValidity(); return false;
    }
    if (!/^01\d{8,9}$/.test(phoneDigits())) {
      phone.setCustomValidity('휴대전화 번호를 숫자 10~11자리로 입력해 주세요.');
      message('휴대전화 번호를 확인해 주세요.', 'error'); phone.focus(); phone.reportValidity(); return false;
    }
    if (request.value.length > 200) {
      request.setCustomValidity('배송 요청사항은 200자 이내로 적어 주세요.');
      message('배송 요청사항은 200자 이내로 적어 주세요.', 'error'); request.focus(); request.reportValidity(); return false;
    }
    if (!regions.has(region.value)) {
      message('배송 권역을 먼저 선택해 주세요.', 'error');
      region.focus();
      region.reportValidity();
      return false;
    }
    if (!methods.has(choices().method)) {
      message('결제 수단을 선택해 주세요.', 'error');
      document.querySelector('[name="demo-method-choice"]')?.focus();
      return false;
    }
    if (!consent.checked) {
      message('주문 상품과 입력 정보를 확인해 주세요.', 'error');
      consent.focus();
      consent.reportValidity();
      return false;
    }
    sync();
    return true;
  }
  function cancelPending() {
    generation++;
    clearTimeout(delayTimer);
    finishDelay?.();
    finishDelay = null;
    fields.disabled = false;
    dialog.removeAttribute('aria-busy');
    $('#checkout-ack-value').value = '0';
  }
  async function authorize() {
    if (!validate() || !dialog.open) return false;
    const serial = ++generation;
    const result = scenario?.value || 'success';
    const selection = choices();
    fields.disabled = true;
    dialog.setAttribute('aria-busy', 'true');
    message('주문 정보를 확인하고 있어요. 실제 금액은 청구되지 않습니다.');
    try {
      await new Promise(resolve => { finishDelay = resolve; delayTimer = setTimeout(resolve, 650); });
      finishDelay = null;
      if (serial !== generation || !dialog.open) return false;
      if (result !== 'success') {
        $('#checkout-ack-value').value = '0';
        message(result === 'cancel' ? '결제를 취소했습니다. 주문은 접수되지 않았어요.' : '처리를 완료하지 못했습니다. 주문은 접수되지 않았어요. 다시 시도해 주세요.', 'error');
        return false;
      }
      // These values describe only this mock checkout. No gateway or card data.
      $('#checkout-region-value').value = selection.region;
      $('#checkout-method-value').value = selection.method;
      $('#checkout-ack-value').value = '1';
      message('주문을 접수하고 있습니다. 잠시만 기다려 주세요.');
      return true;
    } finally {
      if (serial === generation) {
        fields.disabled = false;
        dialog.removeAttribute('aria-busy');
      }
    }
  }
  fields.addEventListener('change', () => { sync(); message(''); });
  [name, phone, request].forEach(input => input.addEventListener('input', () => {
    input.setCustomValidity(''); renderReview(); message('');
  }));
  phone.addEventListener('blur', () => {
    const digits = phoneDigits();
    if (/^01\d{8,9}$/.test(digits)) phone.value = digits.slice(0,3) + '-' + digits.slice(3,-4) + '-' + digits.slice(-4);
    renderReview();
  });
  dialog.addEventListener('close', () => {
    cancelPending();
    consent.checked = false;
    if (scenario) scenario.value = 'success';
    clearPrivate();
    message('');
  });
  try {
    const saved = JSON.parse(sessionStorage.getItem(preferenceKey) || '{}');
    if (regions.has(saved.region)) region.value = saved.region;
    if (methods.has(saved.method)) document.querySelector('[name="demo-method-choice"][value="' + saved.method + '"]').checked = true;
  } catch {}
  // Consent and outcome are never restored from browser storage.
  consent.checked = false;
  if (scenario) scenario.value = 'success';
  clearPrivate();
  sync();
  window.addEventListener('pagehide', clearPrivate);
  window.addEventListener('pageshow', () => { cancelPending(); consent.checked = false; if (scenario) scenario.value = 'success'; clearPrivate(); });
  window.MobleCheckout = Object.freeze({validate, authorize});
})();
