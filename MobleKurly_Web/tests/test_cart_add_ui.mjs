import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../static/js/order.js', import.meta.url), 'utf8');
const addSource = source.slice(source.indexOf('  function addOne('), source.indexOf('  let activeColor'));

function setup({quantity = 0, stock = 30, disabled = false, detailOpen = false} = {}) {
  const steps = [];
  const button = {id:'visible-product-add'};
  const input = {value:quantity, max:stock, disabled};
  const card = {dataset:{name:'딸기 500g'}};
  const detail = {open:detailOpen, close(){this.open=false; steps.push('close-detail');}};
  const api = {open(){throw new Error('Adding must never open the basket');},
    added(){steps.push('basket-feedback');}};
  const add = vm.runInNewContext(addSource + '\naddOne', {
    $: selector => selector === '.quantity input' ? input : selector === '#product-dialog' ? detail : button,
    quantityFor: field => Number(field.value),
    updateSummary: () => steps.push('sync-cart'),
    toast: text => steps.push(['toast', text]),
    window:{MobleCartDrawer:api},
  });
  return {add, steps, button, input, card, detail};
}

test('Product add updates the floating basket without opening or focusing it', () => {
  const ui = setup();
  assert.equal(ui.add(ui.card, ui.button), true);
  assert.equal(ui.input.value, 1);
  assert.equal(ui.steps[0], 'sync-cart');
  assert.equal(ui.steps.at(-1), 'basket-feedback');
});

test('Detail add closes its modal and only gives basket feedback', () => {
  const ui = setup({detailOpen:true});
  ui.add(ui.card);
  assert.equal(ui.detail.open, false);
  assert.equal(ui.steps.at(-2), 'close-detail');
  assert.equal(ui.steps.at(-1), 'basket-feedback');
});

test('Sold out, disabled and stock-limit adds never open the cart or increase quantity', () => {
  for (const settings of [{stock:0}, {disabled:true}, {quantity:30}]) {
    const ui = setup(settings);
    assert.equal(ui.add(ui.card), false);
    assert.equal(ui.input.value, settings.quantity || 0);
    assert.equal(ui.steps.some(step => step === 'sync-cart' || step[0] === 'open-cart'), false);
  }
});
