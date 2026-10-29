import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source=readFileSync(new URL('../static/js/order.js',import.meta.url),'utf8');
const renderSource=source.slice(source.indexOf('  function renderProductGuide('),source.indexOf('  function updateDetail('));
const render=vm.runInNewContext(renderSource+'\nrenderProductGuide');
function target(){return {dataset:{},calls:[],replaceChildren(...nodes){this.calls.push(nodes);}};}
function template(markup){return {innerHTML:markup,content:{cloneNode(deep){assert.equal(deep,true);return {cloned:markup};}}};}

test('Guide template is cloned when a product is opened or changed',()=>{
  const element=target();render(element,template('strawberry'));render(element,template('broccoli'));
  assert.equal(element.calls.length,2);assert.equal(element.calls[1][0].cloned,'broccoli');
});
test('Unchanged catalog refresh preserves open details and keyboard focus',()=>{
  const element=target();render(element,template('same'));render(element,template('same'));
  assert.equal(element.calls.length,1);
});
test('Missing template clears stale previous-product guidance',()=>{
  const element=target();render(element,template('old'));render(element,null);
  assert.equal(element.calls.length,2);assert.equal(element.calls[1].length,0);
  assert.doesNotThrow(()=>render(null,null));
});
