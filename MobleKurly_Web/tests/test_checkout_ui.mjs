import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source=readFileSync(new URL('../static/js/shopping.js',import.meta.url),'utf8');
function fixture(saved={}) {
  const listeners=new Map(), timers=new Map(), elements=new Map();
  let timerId=0, focused=null;
  function node(id, extra={}) {
    const item={value:'',checked:false,hidden:false,disabled:false,dataset:{},textContent:'',
      addEventListener(type,fn){listeners.set(id+':'+type,fn);},
      setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];},
      focus(){focused=id;},reportValidity(){return false;},setCustomValidity(value){this.validationMessage=value;},...extra};
    elements.set('#'+id,item);return item;
  }
  const dialog=node('confirm-dialog',{open:true});
  const region=node('delivery-region',{options:[{value:'',textContent:'선택'},
    {value:'SEOUL',textContent:'서울'},{value:'GYEONGGI',textContent:'경기도'},{value:'CHUNGCHEONG',textContent:'충청도'}]});
  const fields=node('checkout-choice-fields'), consent=node('demo-consent'), status=node('demo-payment-status');
  const scenario=node('demo-scenario',{value:'success'});
  const name=node('recipient-name'),phone=node('recipient-phone'),request=node('delivery-request'),sms=node('sms-consent');
  for(const id of ['delivery-request-count','recipient-review','recipient-review-summary','recipient-review-request','recipient-review-sms']) node(id);
  for(const id of ['delivery-region-feedback','checkout-region-value','checkout-method-value','checkout-ack-value']) node(id);
  const radios=['card','wallet','transfer'].map(value=>node('radio-'+value,{value,checked:value==='card'}));
  const memory=new Map([['moble-kurly-demo-choices-v1',JSON.stringify(saved)]]);
  const sessionStorage={getItem:key=>memory.get(key),setItem:(key,val)=>memory.set(key,val)};
  const document={querySelector(selector){
    if(elements.has(selector))return elements.get(selector);
    if(selector==='[name="demo-method-choice"]:checked')return radios.find(r=>r.checked);
    if(selector==='[name="demo-method-choice"]')return radios[0];
    const match=/\[value="([a-z]+)"\]/.exec(selector);
    if(match)return radios.find(r=>r.value===match[1]);
    return null;
  }};
  const window={addEventListener(type,fn){listeners.set('window:'+type,fn);}};
  vm.runInNewContext(source,{document,window,sessionStorage,Map,Set,JSON,Object,
    setTimeout(fn){timers.set(++timerId,fn);return timerId;},clearTimeout(id){timers.delete(id);}});
  return {api:window.MobleCheckout,region,fields,consent,status,scenario,dialog,elements,radios,name,phone,request,sms,memory,
    input(id){listeners.get(id+':input')?.();},change(){listeners.get('checkout-choice-fields:change')();},
    pagehide(){listeners.get('window:pagehide')();},pageshow(){listeners.get('window:pageshow')();},
    focus:()=>focused,flush(){for(const [id,fn] of timers){timers.delete(id);fn();}},
    close(){dialog.open=false;listeners.get('confirm-dialog:close')();},
    ready(){region.value='GYEONGGI';consent.checked=true;name.value='테스트받는분';phone.value='010-0000-0000';}};
}
test('Region is mandatory before mock payment',()=>{
  const f=fixture();f.ready();f.region.value='';assert.equal(f.api.validate(),false);assert.equal(f.focus(),'delivery-region');
});
test('Consent is mandatory and not restored from storage',()=>{
  const f=fixture({region:'GYEONGGI',method:'wallet',consent:true});
  assert.equal(f.region.value,'GYEONGGI');assert.equal(f.consent.checked,false);
  f.name.value='테스트받는분';f.phone.value='010-0000-0000';
  assert.equal(f.api.validate(),false);assert.equal(f.focus(),'demo-consent');
});
test('Success authorizes only mock choices; does not perform a network payment',async()=>{
  const f=fixture();f.ready();const pending=f.api.authorize();assert.equal(f.fields.disabled,true);
  f.flush();assert.equal(await pending,true);assert.equal(f.fields.disabled,false);
  assert.equal(f.elements.get('#checkout-region-value').value,'GYEONGGI');
  assert.equal(f.elements.get('#checkout-ack-value').value,'1');
});
for(const result of ['failure','cancel']) test(result+' never authorizes order submission',async()=>{
  const f=fixture();f.ready();f.scenario.value=result;const pending=f.api.authorize();f.flush();
  assert.equal(await pending,false);assert.equal(f.elements.get('#checkout-ack-value').value,'0');
  assert.equal(f.status.dataset.kind,'error');assert.equal(f.fields.disabled,false);
});
test('Closing while processing cancels pending authorization',async()=>{
  const f=fixture();f.ready();const pending=f.api.authorize();f.close();
  assert.equal(await pending,false);assert.equal(f.consent.checked,false);assert.equal(f.fields.disabled,false);
});
test('Invalid persisted choices do not become accepted destinations',()=>{
  const f=fixture({region:'elsewhere',method:'real-card'});
  assert.equal(f.region.value,'');assert.equal(f.api.validate(),false);
});
test('Recipient name and phone are required, requests are bounded',()=>{
  const f=fixture();f.ready();f.name.value='';assert.equal(f.api.validate(),false);assert.equal(f.focus(),'recipient-name');
  f.name.value='테스트';f.phone.value='wrong';assert.equal(f.api.validate(),false);assert.equal(f.focus(),'recipient-phone');
  f.phone.value='01000000000';f.request.value='a'.repeat(201);assert.equal(f.api.validate(),false);assert.equal(f.focus(),'delivery-request');
});
test('SMS is optional, defaults off, and is not required for authorization',async()=>{
  const f=fixture();f.ready();assert.equal(f.sms.checked,false);const pending=f.api.authorize();f.flush();assert.equal(await pending,true);
});
test('Personal fields and SMS choices never enter browser storage; review masks phone',()=>{
  const f=fixture();f.ready();f.request.value='<script>synthetic request</script>';f.sms.checked=true;f.change();
  assert.equal(f.elements.get('#recipient-review-summary').textContent,'테스트받는분 · 010-****-0000');
  assert.equal(f.elements.get('#recipient-review-request').textContent,'요청사항 · <script>synthetic request</script>');
  const saved=[...f.memory.values()].join('');
  for(const privateValue of ['테스트받는분','010','synthetic','sms']) assert.equal(saved.includes(privateValue),false);
  assert.equal(f.elements.get('#recipient-review-sms').textContent,'배송 문자 · 수신 동의');
});
test('Closing and page transitions clear personal fields, request review and SMS',()=>{
  for(const action of ['close','pagehide','pageshow']){
    const f=fixture();f.ready();f.request.value='테스트요청';f.sms.checked=true;f.change();f[action]();
    for(const field of [f.name,f.phone,f.request]) assert.equal(field.value,'');
    assert.equal(f.sms.checked,false);assert.equal(f.elements.get('#recipient-review-summary').textContent,'');
    assert.equal(f.elements.get('#recipient-review').hidden,true);
  }
});
