import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../static/js/order.js', import.meta.url), 'utf8');
function pricing(discount) {
  const part = source.slice(source.indexOf('  const memberDiscount ='), source.indexOf('  function updateSummary()'));
  return vm.runInNewContext(part + '\n({discountedUnit, discountedTotal})', {
    window:{MOBLE_MEMBER_DISCOUNT:discount}, BigInt,
  });
}

test('Member unit prices match Decimal half-up rounding before multiplying quantity', () => {
  const p = pricing(5);
  assert.equal(p.discountedUnit(1200000n), 1140000n);
  assert.equal(p.discountedUnit(123456n), 117300n);
  assert.equal(p.discountedTotal([{price:123456n,quantity:3}]), 351900n);
});
test('Guest pricing keeps DB decimal cents exactly', () => {
  const p = pricing(0);
  assert.equal(p.discountedUnit(123456n),123456n);
});
test('Both cart views share thumbnail rows and non-submitting quantity controls', () => {
  assert.ok(source.includes("thumbnail.className = 'cart-product-thumbnail'"));
  assert.ok(source.includes("row.append(thumbnail, info, controls)"));
  assert.ok(source.includes('row.cloneNode(true)'));
  assert.ok(source.includes("remove.type = 'button'"));
  assert.ok(source.includes("minus.type = 'button'"));
  assert.ok(source.includes("plus.type = 'button'"));
  assert.ok(source.includes('focus({preventScroll:true})'));
});
test('Point-use cancellation clears the field and refreshes the shown payment amount', () => {
  const start = source.indexOf("  $('#points-cancel')?.addEventListener");
  const handler = source.slice(start, source.indexOf("  $('#confirm-order')", start));
  let click;
  const input = {value:'500'};
  let renders = 0;
  vm.runInNewContext(handler, {
    $: selector => selector === '#points-cancel' ? {addEventListener:(_, fn) => {click=fn;}} : input,
    renderConfirmation:() => {renders++;},
  });
  click();
  assert.equal(input.value,'0');
  assert.equal(renders,1);
});
