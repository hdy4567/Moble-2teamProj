import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// Exercise the actual storefront helpers without a browser or a live database.
const source = readFileSync(new URL('../static/js/order.js', import.meta.url), 'utf8');
const helpers = source.slice(source.indexOf('  function priceCents('), source.indexOf('  function quantityFor('));
assert.ok(helpers.includes('function money('), 'Storefront money helpers must be available.');
const {priceCents, money} = vm.runInNewContext(helpers + '\n({priceCents, money})', {
  numberFormat: new Intl.NumberFormat('ko-KR'),
});

for (const [value, cents, shown] of [
  ['12000.00', 1200000n, '12,000원'],
  ['1234.50', 123450n, '1,234.5원'],
  ['1234.56', 123456n, '1,234.56원'],
  ['0.00', 0n, '0원'],
  ['0.10', 10n, '0.1원'],
  ['-0.10', -10n, '-0.1원'],
]) {
  test(`DB DECIMAL ${value} is retained exactly`, () => {
    assert.equal(priceCents(value), cents);
    assert.equal(money(cents), shown);
  });
}

test('Decimal cart totals do not accumulate floating point error', () => {
  assert.equal(money(priceCents('0.10') + priceCents('0.20')), '0.3원');
  assert.equal(money(priceCents('1234.56') * 2n), '2,469.12원');
});

test('Large DB prices and stock remain exact beyond Number integer precision', () => {
  assert.equal(money(priceCents('99999999.99') * 2147483647n), '214,748,364,678,525,163.53원');
});

test('Invalid values cannot silently become a made-up price', () => {
  for (const value of ['', 'NaN', 'Infinity', 'not-a-price', '1.234', '1e3']) {
    assert.throws(() => priceCents(value));
  }
});
