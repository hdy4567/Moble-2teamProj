import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source=readFileSync(new URL('../static/js/shopping.js',import.meta.url),'utf8');
function advertisingFixture(reduced=false){
  const events=new Map(),timers=new Map();let sequence=0,modal=false,mutation;
  function node(key){return {hidden:false,inert:false,textContent:'',attributes:{},firstElementChild:{textContent:''},
    classList:{toggle(){}},setAttribute(k,v){this.attributes[k]=v;},
    addEventListener(k,fn){events.set(key+':'+k,fn);}};}
  const carousel=node('carousel'),navigation=node('navigation'),toggle=node('toggle'),counter=node('counter');
  const next=node('next'),prev=node('prev');const slides=[node('slide0'),node('slide1')];
  slides[1].hidden=true;slides[1].inert=true;counter.textContent='01 / 02';
  const dots=[node('dot0'),node('dot1')];
  carousel.querySelectorAll=selector=>selector==='[data-ad-slide]'?slides:dots;
  carousel.querySelector=selector=>({'[data-ad-toggle]':toggle,'.advertising-navigation':navigation,'[data-ad-counter]':counter,'[data-ad-prev]':prev,'[data-ad-next]':next}[selector]);
  carousel.contains=()=>false;
  const document={hidden:false,activeElement:null,
    querySelector(selector){return selector==='#advertising-carousel'?carousel:selector==='dialog[open]'&&modal?{}:null;},
    querySelectorAll(){return [{}];},addEventListener(k,fn){events.set('document:'+k,fn);}};
  const media={matches:reduced,addEventListener(k,fn){events.set('media:'+k,fn);}};
  class MutationObserver{constructor(fn){mutation=fn;}observe(){}}
  vm.runInNewContext(source,{document,window:{matchMedia:()=>media},MutationObserver,Set,queueMicrotask,
    setTimeout(fn,delay){timers.set(++sequence,{fn,delay});return sequence;},clearTimeout(id){timers.delete(id);}});
  return {document,slides,toggle,counter,timers,events,media,
    fire(key,argument={}){events.get(key)(argument);},
    tick(){const [id,timer]=[...timers][0]||[];if(timer){timers.delete(id);timer.fn();}},
    modal(value){modal=value;mutation();}};
}
test('Advertisement advances after five seconds and inactive content stays inert',()=>{
  const f=advertisingFixture();assert.equal([...f.timers.values()][0].delay,5000);f.tick();
  assert.equal(f.counter.textContent,'02 / 02');assert.equal(f.slides[0].hidden,true);assert.equal(f.slides[0].inert,true);assert.equal(f.slides[1].hidden,false);
});
test('Manual next, previous and dot navigation wrap correctly',()=>{
  const f=advertisingFixture();f.fire('prev:click');assert.equal(f.counter.textContent,'02 / 02');
  f.fire('next:click');assert.equal(f.counter.textContent,'01 / 02');f.fire('dot1:click');assert.equal(f.counter.textContent,'02 / 02');
});
test('Pause/play and reduced motion preference control automatic playback',()=>{
  const f=advertisingFixture();f.fire('toggle:click');assert.equal(f.timers.size,0);assert.equal(f.toggle.attributes['aria-pressed'],'true');
  f.fire('toggle:click');assert.equal(f.timers.size,1);
  const quiet=advertisingFixture(true);assert.equal(quiet.timers.size,0);quiet.fire('next:click');assert.equal(quiet.counter.textContent,'02 / 02');
});
test('Hover, keyboard focus, hidden tab and open dialog pause automatic playback',()=>{
  const f=advertisingFixture();f.fire('carousel:mouseenter');assert.equal(f.timers.size,0);f.fire('carousel:mouseleave');assert.equal(f.timers.size,1);
  f.fire('carousel:focusin');assert.equal(f.timers.size,0);
  const visible=advertisingFixture();visible.document.hidden=true;visible.fire('document:visibilitychange');assert.equal(visible.timers.size,0);
  visible.document.hidden=false;visible.fire('document:visibilitychange');assert.equal(visible.timers.size,1);
  visible.modal(true);assert.equal(visible.timers.size,0);visible.modal(false);assert.equal(visible.timers.size,1);
});
