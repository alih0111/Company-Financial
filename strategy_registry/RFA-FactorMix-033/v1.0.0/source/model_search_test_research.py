import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from features import market_features,rank_transform,eligible_training_rows,forward_labels
from models import registry,policies,training_frame,feature_mask


def test_future_price_change_cannot_change_past_features():
    rng=np.random.default_rng(10)
    c=np.exp(np.cumsum(rng.normal(0,.02,(350,4)),axis=0));a=np.ones_like(c)*1e9
    first=market_features(c,a)
    c[280:]*=10;a[280:]*=3
    second=market_features(c,a)
    for k in first:np.testing.assert_allclose(first[k][:280],second[k][:280],equal_nan=True)


def test_rank_transform_is_within_date_and_missing_is_neutral():
    x=np.array([[1.,2.,np.nan],[3.,2.,1.]])
    a=rank_transform(x)
    x[1]=1000
    assert np.array_equal(a[0],rank_transform(x)[0])
    assert a[0,2]==0


def test_labels_crossing_fit_cutoff_are_purged():
    ends=np.array([3,4,5,6,-1])
    assert eligible_training_rows({},ends,4,np.arange(5)).tolist()==[0,1]


def test_training_frame_never_reads_unrealized_target():
    T,S=10,3
    d={'mark_age':np.zeros((T,S))}
    f={'label_end63':np.arange(T)+3,'sample_rows':np.arange(T),'allowed':np.ones((T,S),bool),
       'X':np.ones((T,S,2)),'y63':np.arange(T*S).reshape(T,S).astype(float)}
    a=training_frame(d,f,63,np.array([0,1]),6)
    f['y63'][4:]=999999
    b=training_frame(d,f,63,np.array([0,1]),6)
    assert np.array_equal(a[1],b[1]);assert max(a[3])==3


def test_forward_target_uses_available_next_open_not_decision_close():
    T,S=12,12
    d={'close':np.ones((T,S))*20,'opening':np.ones((T,S))*10,
       'locked':np.zeros((T,S),bool),'mark_age':np.zeros((T,S))}
    d['opening'][1,0]=np.nan;d['opening'][2,0]=5
    y,ends=forward_labels(d,5)
    assert ends[0]==5
    assert y[0,0]>y[0,1]
    assert np.isnan(y[-1]).all()


def test_model_registry_and_weight_search_are_reproducible():
    a=registry();b=registry();assert a==b
    assert len(a)>200 and len({x['id'] for x in a})==len(a)
    for m in a:
        if m['kind']=='blocks':
            assert min(m['weights'])>=0
            assert np.isclose(sum(m['weights']),1)
    assert len(policies())==14


def test_fundamental_mask_excludes_market_factors():
    f={'names':np.array(['sales_growth_3m','price_momentum_30d','missing_price_momentum_30d','mom_63']),
       'groups':np.array(['fundamental','fundamental','missing','market'])}
    assert feature_mask(f,'fundamental').tolist()==[0]
    assert feature_mask(f,'market').tolist()==[1,3]
