"use strict";
// Synthetic structural replay of sanitized Run 54998652 evidence.
// Explicit-role positives below are controls, NOT observations of the live tab.
const fs = require('fs'), vm = require('vm'), path = require('path');
class El {
  constructor(tag='div', attrs={}, text='') { this.tagName=tag.toUpperCase(); this.attrs=attrs; this.innerText=this.textContent=text; this.children=[]; this.parentElement=null; this.id=''; }
  add(node) { node.parentElement=this; this.children.push(node); return node; }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs,k) ? this.attrs[k] : null; }
  getAttributeNames() { return Object.keys(this.attrs); }
  contains(n) { return n===this || this.children.some(c=>c.contains(n)); }
  matches(s) { if(s==='*') return true; if(s[0]==='.') return (this.attrs.class||'').split(' ').includes(s.slice(1)); const m=s.match(/^\[([^=\]]+)(?:=['"]([^'"]*)['"])?\]$/); return m ? this.getAttribute(m[1])!==null && (m[2]===undefined || this.getAttribute(m[1])===m[2]) : s.toUpperCase()===this.tagName; }
  querySelectorAll(s) { return this.children.flatMap(c=>[c,...c.querySelectorAll('*')]).filter(c=>s.split(',').some(p=>c.matches(p.trim()))); }
  compareDocumentPosition(n) { if(this===n)return 0; if(this.contains(n))return 20; if(n.contains(this))return 10; const nodes=[main,...main.querySelectorAll('*')]; return nodes.indexOf(this)<nodes.indexOf(n)?4:2; }
}
let main, api;
function fixture() {
  main=new El('main'); const turn=main.add(new El('div',{'data-turn-key':'synthetic'}));
  const user=turn.add(new El('div',{class:'bg-user-message'},'USER marker plus quoted REPLY'));
  user.add(new El('div',{},'USER marker plus quoted REPLY'));
  const response=turn.add(new El('div',{'data-response-body':''},'REPLY'));
  let leaf=response; for(let i=0;i<6;i++)leaf=leaf.add(new El()); leaf=leaf.add(new El('p')).add(new El('span',{},'REPLY'));
  return {turn,user,response,leaf};
}
const doc={readyState:'loading',addEventListener(){},querySelector:s=>s==='main'?main:null,querySelectorAll:s=>main.querySelectorAll(s)};
const context={window:{location:{hostname:'chatgpt.com',origin:'https://chatgpt.com'}}, document:doc, chrome:{runtime:{onMessage:{addListener(){}}}},setTimeout,clearTimeout};
vm.createContext(context);
const source=fs.readFileSync(path.join(__dirname,'../transport/extension/content.js'),'utf8');
const hook='globalThis.testBoundary={latestReply,assistantCandidates,anchor:(node)=>{lastConfirmedUserTurn=node;}};})();';
if(!/\}\)\(\);\s*$/.test(source))throw Error('Test hook insertion failed');
vm.runInContext(source.replace(/\}\)\(\);\s*$/,hook),context); api=context.testBoundary;
const checks=[]; function check(name,ok){checks.push({name,pass:!!ok});}
let f=fixture(); api.anchor(null);
check('response_body_without_confirmed_user_is_not_author',api.latestReply()===null);
api.anchor(f.user);
check('exact_later_response_body_still_not_author',api.latestReply()===null);
check('shared_turn_key_not_a_message_author_or_boundary',api.assistantCandidates().length===0);
check('quoted_reply_marker_in_user_not_read_back',api.latestReply()===null);
f.response.attrs['data-message-author-role']='assistant';
check('explicit_assistant_after_confirmed_user_positive',api.latestReply()?.text==='REPLY');
check('positive_uses_explicit_role_strategy',api.latestReply()?.strategy==='role_attribute');
api.anchor(null);
check('explicit_role_without_current_send_anchor_rejected',api.latestReply()===null);
f=fixture(); api.anchor(f.user); f.user.children[0].attrs['data-message-author-role']='assistant';
check('author_marker_inside_user_boundary_rejected',api.latestReply()===null);
f=fixture(); api.anchor(f.user); f.turn.attrs['data-message-author-role']='assistant';
check('shared_user_reply_container_even_with_role_rejected',api.latestReply()===null);
f=fixture(); api.anchor(f.user); const old=new El('div',{'data-message-author-role':'assistant'},'OLD'); old.parentElement=f.turn; f.turn.children.unshift(old);
check('older_explicit_reply_rejected',api.latestReply()===null);
console.log(JSON.stringify({all_pass:checks.every(c=>c.pass),checks},null,2)); process.exitCode=checks.every(c=>c.pass)?0:1;
