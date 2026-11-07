import numpy as np, blocks as b, common as c, pickle, sys, time, os
B,cols,mask=pickle.load(open('cache.pkl','rb'))
K=list(b.W033)+['mom_12_1']
rng=np.random.default_rng(int(sys.argv[1])); n=int(sys.argv[2])
out=[]
t=time.time()
for i in range(n):
    v=rng.dirichlet(np.ones(len(K))*0.7)
    w={k:float(v[j]) for j,k in enumerate(K[:8])}; ex={'mom_12_1':float(v[8])}
    s=b.score(B,mask,w,ex,cols); D=b.data_with(s)
    navs=[c.run(data=D,sched=c.monthly(d))['nav'] for d in (5,15,25)]
    out.append((v,np.mean(navs,0).astype(np.float32)))
    if time.time()-t>150: break
pickle.dump(out,open(f'wf_{sys.argv[1]}.pkl','wb'))
print(len(out),time.time()-t)
