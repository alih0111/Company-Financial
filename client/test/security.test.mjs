import test, {beforeEach} from 'node:test';
import assert from 'node:assert/strict';

const storage=new Map();
globalThis.localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
const redirects=[];
globalThis.window={location:{origin:'https://example.com',protocol:'https:',host:'example.com',pathname:'/portfolio',search:'',replace:value=>redirects.push(value)},addEventListener(){},dispatchEvent(){}};
const session=await import('./.generated/security.mjs');
beforeEach(()=>{storage.clear();redirects.length=0;session.clearSession();});

function signInAs(username){
  globalThis.fetch=async (_url,init)=>{
    assert.equal(init.credentials,'same-origin');
    assert.equal(new Headers(init.headers).has('Authorization'),false);
    return new Response(JSON.stringify({username,isAdmin:false}),{status:200});
  };
  return session.refreshSession();
}

test('credentials stay out of browser storage and forged local JWT cannot grant access',async()=>{
  storage.set('token','forged-old-jwt');
  assert.equal(session.getAuthStatus().username,null);
  await signInAs('alice');
  assert.equal(storage.has('token'),false);
  assert.deepEqual(session.getAuthStatus(),{username:'alice',isAdmin:false});
  assert.deepEqual(session.sessionHeaders(),{});
});

test('logout waits for server invalidation; a failed logout preserves the active UI',async()=>{
  await signInAs('alice');
  globalThis.fetch=async()=>new Response('',{status:503});
  await assert.rejects(session.logoutSession());
  assert.equal(session.getAuthStatus().username,'alice');
  globalThis.fetch=async(url,init)=>{
    assert.equal(url,'/api/logout');assert.equal(init.method,'POST');
    return new Response('',{status:200});
  };
  await session.logoutSession();
  assert.equal(session.getAuthStatus().username,null);
});

test('watchlists and price alerts are separated between signed-in accounts',async()=>{
  await signInAs('alice');
  session.toggleWatch({key:'stock',label:'Stock',kind:'stock'});
  session.setAlert({key:'stock',label:'Stock',above:true,price:100});
  await signInAs('bob');
  assert.equal(session.getWatchlist().length,0);assert.equal(session.getAlerts().length,0);
  await signInAs('alice');
  assert.equal(session.getWatchlist().length,1);assert.equal(session.getAlerts().length,1);
});

test('revoked cookie session clears the cached identity and returns to sign-in',async()=>{
  await signInAs('alice');
  globalThis.fetch=async()=>new Response('',{status:401});
  await session.apiFetch('/api/portfolio');
  assert.equal(session.getAuthStatus().username,null);
  assert.deepEqual(redirects,['/login?next=%2Fportfolio']);
});

test('production authentication refuses plaintext HTTP even on localhost',()=>{
  window.location.protocol='http:';
  assert.equal(session.requiresSecureAuth(),true);
  window.location.protocol='https:';
  assert.equal(session.requiresSecureAuth(),false);
});

test('data quota errors preserve login and show the server message',async()=>{
 await signInAs('alice');
 globalThis.fetch=async()=>Response.json({code:'data_quota_exceeded',error:'سهمیهٔ امروز تمام شده است.'},{status:429});
 await assert.rejects(session.apiFetch('/api/summary'),/سهمیه/);
 assert.equal(session.getAuthStatus().username,'alice');assert.deepEqual(redirects,[]);
});
