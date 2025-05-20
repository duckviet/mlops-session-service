import polars as pl
from lightgbm.sklearn import LGBMRanker
import joblib
from process_pipeline import apply, pipeline, get_session_lenghts

train = pl.read_parquet('data/otto/test.parquet')
train_labels = pl.read_parquet('data/otto/test_labels.parquet')

 
train = apply(train.clone(), pipeline) 

type2id = {"clicks": 0, "carts": 1, "orders": 2}


train_labels = train_labels.explode('ground_truth').with_columns([
    pl.col('ground_truth').alias('aid'),
    pl.col('type').replace_strict(type2id, return_dtype=pl.UInt8).alias('type') 
])[['session', 'type', 'aid']] 

train_labels = train_labels.with_columns([
    pl.col('session').cast(pl.datatypes.Int32),
    pl.col('type').cast(pl.datatypes.UInt8), 
    pl.col('aid').cast(pl.datatypes.Int32)
])


train_labels = train_labels.with_columns(
    pl.lit(1).cast(pl.UInt8).alias('gt') 
)
train = train.join(
    train_labels, 
    how='left', 
    on=['session', 'type', 'aid']
).with_columns(pl.col('gt').fill_null(0))

session_lengths_train = get_session_lenghts(train)

ranker = LGBMRanker(
    objective="lambdarank",
    metric="ndcg",
    boosting_type="dart",
    n_estimators=20,
    importance_type='gain',
)
feature_cols = ['aid', 'type', 'action_num_reverse_chrono', 'session_length', 'log_recency_score', 'type_weighted_log_recency_score']
target = 'gt'
ranker = ranker.fit(
    train[feature_cols].to_pandas(),
    train[target].to_pandas(),
    group=session_lengths_train,
)
joblib.dump(ranker, 'model/lgbm_ranker.joblib')